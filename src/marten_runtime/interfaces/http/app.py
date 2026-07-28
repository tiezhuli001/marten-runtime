import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from tempfile import SpooledTemporaryFile
from uuid import uuid4

from pydantic import BaseModel

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from marten_runtime.gateway.ingress import ingest_message
from marten_runtime.interfaces.http.bootstrap import (
    HTTPRuntimeState,
    _process_inbound_envelope,
    _process_automation_dispatch,
    build_manual_automation_dispatch,
    build_http_runtime,
    render_metrics,
)
from marten_runtime.interfaces.http.eval_routes import build_eval_router
from marten_runtime.interfaces.http.knowledge_routes import (
    KnowledgeRouteError,
    MAX_UPLOAD_REQUEST_BYTES,
    build_knowledge_router,
    declared_upload_error,
    error_envelope,
    operator_authorized,
)
from marten_runtime.interfaces.http.runtime_diagnostics import (
    serialize_runtime_diagnostics,
)
from marten_runtime.runtime.lanes import LaneLease
from marten_runtime.runtime.event_loop_cleanup import close_idle_event_loops
from marten_runtime.runtime.observation_policy import REDACTED_TEXT


logger = logging.getLogger(__name__)


class KnowledgeUploadSizeLimitMiddleware:
    def __init__(
        self,
        app,
        *,
        max_bytes: int = MAX_UPLOAD_REQUEST_BYTES,
        operator_token: str = "",
    ) -> None:  # noqa: ANN001
        self.app = app
        self.max_bytes = int(max_bytes)
        self.operator_token = str(operator_token)

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        path = str(scope.get("path") or "")
        limited = (
            scope.get("type") == "http"
            and str(scope.get("method") or "").upper() == "POST"
            and path.startswith("/knowledge/")
            and path.endswith("/uploads")
        )
        if not limited:
            await self.app(scope, receive, send)
            return
        headers = {
            bytes(name).decode("latin-1").lower(): bytes(value).decode("latin-1")
            for name, value in scope.get("headers") or []
        }
        if not self.operator_token or not operator_authorized(
            headers.get("authorization"),
            self.operator_token,
        ):
            await self.app(scope, receive, send)
            return
        declared_error = declared_upload_error(headers.get("content-length"))
        if declared_error is not None:
            response = JSONResponse(
                status_code=declared_error.status_code,
                content=error_envelope(declared_error.code, declared_error.message),
            )
            await response(scope, receive, send)
            return
        received = 0
        buffered = SpooledTemporaryFile(max_size=1024 * 1024)
        try:
            while True:
                message = await receive()
                if message.get("type") != "http.request":
                    break
                chunk = bytes(message.get("body") or b"")
                received += len(chunk)
                if received > self.max_bytes:
                    response = JSONResponse(
                        status_code=413,
                        content=error_envelope(
                            "KNOWLEDGE_UPLOAD_TOO_LARGE",
                            "upload exceeds 10 MiB",
                        ),
                    )
                    await response(scope, receive, send)
                    return
                buffered.write(chunk)
                if not message.get("more_body", False):
                    break
            buffered.seek(0)

            async def replay_receive():  # noqa: ANN202
                chunk = buffered.read(64 * 1024)
                return {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": bool(chunk),
                }

            await self.app(scope, replay_receive, send)
        finally:
            buffered.close()


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
) -> FastAPI:
    runtime = build_http_runtime(
        repo_root=repo_root,
        env=env,
        load_env_file=load_env_file,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = runtime
        if getattr(runtime, "compaction_worker", None) is not None:
            runtime.compaction_worker.start()
        if (
            runtime.channels_config.feishu.enabled
            and runtime.channels_config.feishu.connection_mode == "websocket"
            and runtime.channels_config.feishu.auto_start
        ):
            await runtime.feishu_socket_service.start_background()
        try:
            yield
        finally:
            try:
                if getattr(runtime, "compaction_worker", None) is not None:
                    runtime.compaction_worker.stop()
            except Exception as exc:
                logger.warning("compaction_worker.stop failed: %s", exc, exc_info=True)
            try:
                runtime.subagent_service.shutdown()
            except Exception as exc:
                logger.warning("subagent_service.shutdown failed: %s", exc, exc_info=True)
            finally:
                try:
                    mcp_client = getattr(runtime, "mcp_client", None)
                    shutdown = getattr(mcp_client, "shutdown", None)
                    if callable(shutdown):
                        shutdown()
                except Exception as exc:
                    logger.warning("mcp_client.shutdown failed: %s", exc, exc_info=True)
                try:
                    await runtime.feishu_socket_service.stop_background()
                except Exception as exc:
                    logger.warning(
                        "feishu_socket_service.stop_background failed: %s",
                        exc,
                        exc_info=True,
                    )
                finally:
                    try:
                        runtime.langfuse_observer.flush()
                    except Exception as exc:
                        logger.warning(
                            "langfuse_observer.flush failed: %s",
                            exc,
                            exc_info=True,
                        )
                    finally:
                        try:
                            runtime.langfuse_observer.shutdown()
                        except Exception as exc:
                            logger.warning(
                                "langfuse_observer.shutdown failed: %s",
                                exc,
                                exc_info=True,
                            )
                        finally:
                            try:
                                close_idle_event_loops()
                            except Exception as exc:
                                logger.warning(
                                    "close_idle_event_loops failed: %s",
                                    exc,
                                    exc_info=True,
                                )

    app = FastAPI(title="marten-runtime", lifespan=lifespan)
    app.state.runtime = runtime
    operator_token = str(getattr(runtime, "env", {}).get("KNOWLEDGE_OPERATOR_TOKEN") or "").strip()

    @app.middleware("http")
    async def knowledge_operator_boundary(request: Request, call_next):  # noqa: ANN001, ANN202
        if operator_token and request.url.path.startswith("/knowledge/"):
            if not operator_authorized(request.headers.get("authorization"), operator_token):
                return JSONResponse(
                    status_code=401,
                    content=error_envelope(
                        "KNOWLEDGE_OPERATOR_UNAUTHORIZED",
                        "operator authorization failed",
                    ),
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if request.method == "POST" and request.url.path.endswith("/uploads"):
                declared_error = declared_upload_error(request.headers.get("content-length"))
                if declared_error is not None:
                    return JSONResponse(
                        status_code=declared_error.status_code,
                        content=error_envelope(declared_error.code, declared_error.message),
                    )
        return await call_next(request)

    @app.exception_handler(KnowledgeRouteError)
    async def knowledge_route_error_handler(_request: Request, exc: KnowledgeRouteError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(exc.code, exc.message, retryable=exc.retryable),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.url.path.startswith("/knowledge/"):
            return JSONResponse(
                status_code=422,
                content=error_envelope(
                    "KNOWLEDGE_REQUEST_INVALID",
                    "knowledge request validation failed",
                ),
            )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    if operator_token:
        app.include_router(
            build_knowledge_router(runtime, operator_token=operator_token),
            prefix="/knowledge",
        )
    app.include_router(
        build_eval_router(
            getattr(runtime, "repo_root", Path.cwd()),
            env=getattr(runtime, "env", {}),
        ),
        prefix="/evals",
    )

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
            conversation_id=f"conversation_{runtime.session_store.count() + 1}",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.default_prompt_manifest_id,
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
            runtime.subagent_service.release_deferred_background_starts()
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
        response = _process_automation_dispatch(runtime, dispatch)
        runtime.subagent_service.release_deferred_background_starts()
        return response

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
            return _serialize_session_diagnostics(runtime.session_store.get(session_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND") from exc

    @app.get("/diagnostics/sessions")
    def list_sessions() -> dict[str, object]:
        items = [
            _serialize_session_catalog_item(item)
            for item in runtime.session_store.list_sessions()
        ]
        return {"count": len(items), "items": items}

    @app.get("/diagnostics/run/{run_id}")
    def get_run(run_id: str) -> dict[str, object]:
        try:
            return runtime.run_history.get(run_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="RUN_NOT_FOUND") from exc

    @app.get("/diagnostics/subagents")
    def list_subagents() -> dict[str, object]:
        items = [item.model_dump(mode="json") for item in runtime.subagent_service.store.list_tasks()]
        return {"items": items, "count": len(items)}

    @app.get("/diagnostics/subagent/{task_id}")
    def get_subagent(task_id: str) -> dict[str, object]:
        try:
            return runtime.subagent_service.store.get(task_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="SUBAGENT_NOT_FOUND") from exc

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

    app.add_middleware(
        KnowledgeUploadSizeLimitMiddleware,
        operator_token=operator_token,
    )
    return app


def _serialize_session_catalog_item(record) -> dict[str, object]:  # noqa: ANN001
    sensitive = _is_bazi_session(record)
    return {
        "session_id": record.session_id,
        "conversation_id": record.conversation_id,
        "channel_id": record.channel_id,
        "user_id": record.user_id,
        "agent_id": record.agent_id or record.active_agent_id,
        "session_title": REDACTED_TEXT if sensitive and record.session_title else record.session_title,
        "session_preview": REDACTED_TEXT if sensitive and record.session_preview else record.session_preview,
        "message_count": record.message_count,
        "state": record.state,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "last_event_at": (
            record.last_event_at.isoformat() if record.last_event_at is not None else None
        ),
    }


def _serialize_session_diagnostics(record) -> dict[str, object]:  # noqa: ANN001
    payload = record.model_dump(mode="json")
    if not _is_bazi_session(record):
        return payload
    payload["session_title"] = REDACTED_TEXT if record.session_title else ""
    payload["session_preview"] = REDACTED_TEXT if record.session_preview else ""
    payload["history"] = [
        {**message, "content": REDACTED_TEXT if str(message.get("content") or "").strip() else ""}
        for message in payload.get("history") or []
        if isinstance(message, dict)
    ]
    payload["latest_compacted_context"] = None
    payload["recent_tool_outcome_summaries"] = []
    payload["sensitive_projection"] = "sensitive_bazi"
    return payload


def _is_bazi_session(record) -> bool:  # noqa: ANN001
    return str(record.agent_id or record.active_agent_id or "").strip() == "bazi"


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
