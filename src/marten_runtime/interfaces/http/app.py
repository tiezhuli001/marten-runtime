from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from marten_runtime.gateway.ingress import ingest_message
from marten_runtime.interfaces.http.bootstrap import (
    HTTPRuntimeState,
    _process_inbound_envelope,
    _process_automation_dispatch,
    build_manual_automation_dispatch,
    build_http_runtime,
    render_metrics,
)


class MessageRequest(BaseModel):
    channel_id: str
    user_id: str
    conversation_id: str
    message_id: str
    body: str


def create_app(
    *,
    repo_root=None,
    env=None,
    load_env_file: bool = True,
    use_compat_json: bool = True,
) -> FastAPI:
    runtime = build_http_runtime(
        repo_root=repo_root,
        env=env,
        load_env_file=load_env_file,
        use_compat_json=use_compat_json,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = runtime
        if (
            runtime.channels_config.feishu.enabled
            and runtime.channels_config.feishu.connection_mode == "websocket"
            and runtime.channels_config.feishu.auto_start
        ):
            await runtime.feishu_socket_service.start_background()
        try:
            yield
        finally:
            await runtime.feishu_socket_service.stop_background()

    app = FastAPI(title="marten-runtime", lifespan=lifespan)
    app.state.runtime = runtime

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return render_metrics(runtime)

    @app.post("/sessions")
    def create_session() -> dict[str, str]:
        record = runtime.session_store.get_or_create_for_conversation(
            conversation_id=f"conversation_{len(runtime.session_store._items) + 1}",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        return {"session_id": record.session_id}

    @app.post("/messages")
    def post_message(request: MessageRequest) -> dict[str, object]:
        envelope = ingest_message(request.model_dump())
        lease = runtime.lane_manager.acquire(
            channel_id=envelope.channel_id,
            conversation_id=envelope.conversation_id,
            run_id=f"run_{uuid4().hex[:8]}",
            trace_id=envelope.trace_id,
        )
        try:
            return _process_inbound_envelope(runtime, envelope)
        finally:
            runtime.lane_manager.release(
                channel_id=envelope.channel_id,
                conversation_id=envelope.conversation_id,
                run_id=lease.run_id,
            )

    @app.post("/automations/{automation_id}/trigger")
    def trigger_automation(automation_id: str) -> dict[str, object]:
        try:
            dispatch = build_manual_automation_dispatch(runtime, automation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="AUTOMATION_NOT_FOUND") from exc
        return _process_automation_dispatch(runtime, dispatch)

    @app.get("/automations")
    def list_automations() -> dict[str, object]:
        items = [
            {
                "automation_id": job.automation_id,
                "name": job.name,
                "schedule_kind": job.schedule_kind,
                "schedule_expr": job.schedule_expr,
                "timezone": job.timezone,
                "delivery_channel": job.delivery_channel,
                "delivery_target": job.delivery_target,
                "skill_id": job.skill_id,
                "enabled": job.enabled,
            }
            for job in runtime.automation_store.list_public(include_disabled=True)
        ]
        return {"items": items, "count": len(items)}

    @app.get("/diagnostics/trace/{trace_id}")
    def get_trace(trace_id: str) -> dict[str, object]:
        item = runtime.trace_index.get(
            trace_id,
            {"run_ids": [], "job_ids": [], "event_ids": [], "external_refs": {"langfuse": None, "langsmith": None}},
        )
        return {"trace_id": trace_id, **item}

    @app.get("/diagnostics/session/{session_id}")
    def get_session(session_id: str) -> dict[str, object]:
        try:
            return runtime.session_store.get(session_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND") from exc

    @app.get("/diagnostics/run/{run_id}")
    def get_run(run_id: str) -> dict[str, object]:
        try:
            return runtime.run_history.get(run_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="RUN_NOT_FOUND") from exc

    @app.get("/diagnostics/runs")
    def list_runs(limit: int = 20) -> dict[str, object]:
        capped_limit = max(1, min(limit, 100))
        items = sorted(
            runtime.run_history.list_runs(),
            key=lambda item: item.started_at or datetime.min,
            reverse=True,
        )[:capped_limit]
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "count": len(items),
        }

    @app.get("/diagnostics/queue")
    def get_queue() -> dict[str, object]:
        return runtime.lane_manager.stats()

    @app.get("/diagnostics/runtime")
    def get_runtime() -> dict[str, object]:
        retry_policy = getattr(runtime.runtime_loop.llm, "retry_policy", None)
        latest_candidate = runtime.self_improve_store.latest_candidate(agent_id=runtime.default_agent.agent_id)
        latest_rejected_candidate = runtime.self_improve_store.latest_candidate(
            agent_id=runtime.default_agent.agent_id,
            status="rejected",
        )
        latest_active_lesson = runtime.self_improve_store.latest_active_lesson(
            agent_id=runtime.default_agent.agent_id
        )
        return {
            "config_snapshot_id": runtime.config_snapshot.config_snapshot_id,
            "app_id": runtime.app_manifest.app_id,
            "default_agent_id": runtime.app_manifest.default_agent,
            "llm_provider": getattr(runtime.runtime_loop.llm, "provider_name", "unknown"),
            "llm_model": getattr(runtime.runtime_loop.llm, "model_name", "unknown"),
            "llm_profile": getattr(runtime.runtime_loop.llm, "profile_name", "unknown"),
            "tool_count": len(runtime.tool_registry.list()),
            "mcp_server_count": len(runtime.mcp_servers),
            "mcp_servers": [
                {
                    "server_id": server.server_id,
                    "transport": server.transport,
                    "enabled": server.enabled,
                    "source_layers": server.source_layers,
                    "tool_count": len(server.tools),
                    "tool_names": [tool.name for tool in server.tools],
                    "discovery": runtime.mcp_discovery.get(
                        server.server_id,
                        {"state": "unknown", "tool_count": len(server.tools), "error": None},
                    ),
                }
                for server in runtime.mcp_servers
            ],
            "server": {
                "host": runtime.platform_config.server.host,
                "port": runtime.platform_config.server.port,
                "public_base_url": runtime.platform_config.server.public_base_url,
            },
            "provider_retry_policy": (
                asdict(retry_policy) if retry_policy is not None and is_dataclass(retry_policy) else None
            ),
            "self_improve": {
                "enabled": True,
                "agent_id": runtime.default_agent.agent_id,
                "active_lessons_count": len(
                    runtime.self_improve_store.list_active_lessons(agent_id=runtime.default_agent.agent_id)
                ),
                "latest_candidate_status": latest_candidate.status if latest_candidate is not None else None,
                "latest_candidate_created_at": (
                    latest_candidate.created_at.isoformat() if latest_candidate is not None else None
                ),
                "latest_lesson_created_at": (
                    latest_active_lesson.created_at.isoformat() if latest_active_lesson is not None else None
                ),
                "latest_accepted_lesson_summary": (
                    latest_active_lesson.lesson_text if latest_active_lesson is not None else None
                ),
                "latest_rejected_lesson_summary": (
                    latest_rejected_candidate.candidate_text if latest_rejected_candidate is not None else None
                ),
            },
            "lanes": runtime.lane_manager.stats(),
            "channels": {
                "http": {"enabled": runtime.channels_config.http.enabled},
                "cli": {"enabled": runtime.channels_config.cli.enabled},
                "feishu": {
                    "enabled": runtime.channels_config.feishu.enabled,
                    "connection_mode": runtime.channels_config.feishu.connection_mode,
                    "auto_start": runtime.channels_config.feishu.auto_start,
                    "routing_policy": {
                        "allowed_chat_types": runtime.channels_config.feishu.allowed_chat_types,
                        "allowed_chat_ids": runtime.channels_config.feishu.allowed_chat_ids,
                    },
                    "receipt_store": runtime.feishu_receipts.stats(),
                    "delivery_sessions": runtime.feishu_delivery.session_store.stats(),
                    "dead_letter": runtime.feishu_delivery.dead_letter_queue.stats(),
                    "retry_policy": runtime.feishu_delivery.retry_policy.model_dump(),
                    "websocket": runtime.feishu_socket_service.stats(),
                },
            },
            "env_loaded": runtime.env_load_result.loaded,
        }

    return app
