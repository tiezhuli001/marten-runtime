from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel

from fastapi import FastAPI, HTTPException, Request
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
from marten_runtime.interfaces.http.runtime_diagnostics import (
    serialize_runtime_diagnostics,
)
from marten_runtime.runtime.lanes import LaneLease


class MessageRequest(BaseModel):
    channel_id: str
    user_id: str
    conversation_id: str
    message_id: str
    body: str
    requested_agent_id: str | None = None


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
        envelope.enqueued_at = lease.enqueued_at
        envelope.started_at = lease.started_at
        try:
            response = _process_inbound_envelope(runtime, envelope)
            _bind_queue_observation_to_response(runtime, response, lease)
            return response
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
            {"run_ids": [], "job_ids": [], "event_ids": [], "external_refs": {}},
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
    def get_runtime(request: Request) -> dict[str, object]:
        return serialize_runtime_diagnostics(runtime, request)

    return app


def _bind_queue_observation_to_response(
    runtime: HTTPRuntimeState,
    response: dict[str, object],
    lease: LaneLease,
) -> None:
    for event in response.get("events", []):
        if not isinstance(event, dict):
            continue
        run_id = str(event.get("run_id", "")).strip()
        if not run_id:
            continue
        runtime.run_history.set_queue_diagnostics(
            run_id,
            queue_depth_at_enqueue=lease.queue_depth_at_enqueue,
            queue_wait_ms=lease.queue_wait_ms,
        )
