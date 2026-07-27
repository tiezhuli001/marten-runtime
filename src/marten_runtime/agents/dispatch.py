from __future__ import annotations

import time
from dataclasses import dataclass

from marten_runtime.agents.registry import AgentRegistry
from marten_runtime.runtime.llm_client import ConversationMessage, LLMRequest
from marten_runtime.runtime.request_flow import (
    generation_input_payload,
    generation_output_payload,
    usage_payload,
)
from marten_runtime.runtime.provider_retry import (
    ProviderTransportError,
    normalize_provider_error,
)
from marten_runtime.session.models import SessionMessage
from marten_runtime.tools.registry import ToolSnapshot


ROUTING_OBSERVATION_POLICY = "metadata_only"


@dataclass(frozen=True)
class AgentDispatchResult:
    target_agent_id: str
    route_run_id: str


class AgentDispatchError(ValueError):
    def __init__(self, *, route_run_id: str, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.route_run_id = route_run_id
        self.error_code = error_code


class AgentDispatchService:
    def __init__(self, *, registry: AgentRegistry, run_history, observer) -> None:  # noqa: ANN001
        self.registry = registry
        self.run_history = run_history
        self.observer = observer

    def dispatch(
        self,
        *,
        source_agent_id: str,
        session_id: str,
        trace_id: str,
        message: str,
        recent_messages: list[SessionMessage],
        llm_client,
        model_profile_name: str | None,
        tokenizer_family: str | None,
        config_snapshot_id: str,
    ) -> AgentDispatchResult:
        catalog = self.registry.routing_catalog(source_agent_id)
        snapshot = _routing_tool_snapshot(list(catalog))
        request = LLMRequest(
            session_id=session_id,
            trace_id=trace_id,
            message=message,
            agent_id=source_agent_id,
            model_name=getattr(llm_client, "model_name", None),
            tokenizer_family=tokenizer_family,
            system_prompt=_routing_system_prompt(catalog),
            conversation_messages=[
                ConversationMessage(role=item.role, content=item.content)
                for item in recent_messages[-6:]
                if item.role in {"user", "assistant"}
            ],
            available_tools=["agent_route"],
            tool_snapshot=snapshot,
            requested_tool_name="agent_route",
            request_kind="agent_routing",
            bootstrap_manifest_id="agent_main_routing",
            prompt_mode="routing",
        )
        run = self.run_history.start(
            session_id=session_id,
            trace_id=trace_id,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id="agent_main_routing",
            tool_snapshot_id=snapshot.tool_snapshot_id,
            observation_policy=ROUTING_OBSERVATION_POLICY,
        )
        started = time.perf_counter()
        trace_handle = self.observer.start_run_trace(
            name="agent.routing",
            trace_id=f"{trace_id}:routing",
            input_text=message,
            metadata={
                "run_id": run.run_id,
                "source_agent_id": source_agent_id,
                "model_profile": model_profile_name,
            },
            tags=["agent-routing"],
            observation_policy=ROUTING_OBSERVATION_POLICY,
        )
        self.run_history.set_external_observability_refs(
            run.run_id,
            langfuse_trace_id=trace_handle.trace_id,
            langfuse_url=trace_handle.url,
        )
        llm_started = time.perf_counter()
        try:
            reply = llm_client.complete(request)
            llm_ms = _elapsed_ms(llm_started)
            self.observer.observe_generation(
                trace_handle,
                name="agent.routing.decision",
                model=getattr(llm_client, "model_name", None),
                provider=getattr(llm_client, "provider_name", None),
                input_payload=generation_input_payload(request),
                output_payload=generation_output_payload(reply),
                usage=usage_payload(reply.usage),
                status="success",
                latency_ms=llm_ms,
                metadata={"request_kind": "agent_routing"},
                observation_policy=ROUTING_OBSERVATION_POLICY,
            )
            target_agent_id = _validate_route_reply(reply, catalog)
            self.run_history.record_tool_call(
                run.run_id,
                tool_name="agent_route",
                tool_payload={"target_agent_id": target_agent_id},
                tool_result={"ok": True, "target_agent_id": target_agent_id},
                observation_policy=ROUTING_OBSERVATION_POLICY,
            )
            self.run_history.set_llm_request_count(run.run_id, 1)
            self.run_history.set_stage_timing(
                run.run_id, stage="llm_first", elapsed_ms=llm_ms
            )
            if reply.usage is not None:
                self.run_history.set_actual_usage(
                    run.run_id, reply.usage, stage="llm_first"
                )
            provider_diagnostics = getattr(llm_client, "last_call_diagnostics", None)
            if provider_diagnostics is not None:
                self.run_history.record_provider_call(
                    run.run_id,
                    stage="llm_first",
                    diagnostics=provider_diagnostics,
                )
            self.run_history.set_final_text(run.run_id, target_agent_id)
            self.run_history.finalize_total_timing(
                run.run_id, elapsed_ms=_elapsed_ms(started)
            )
            self.run_history.finish(run.run_id, delivery_status="internal")
            self.observer.finalize_run(
                trace_handle,
                status="success",
                final_text=target_agent_id,
                usage=usage_payload(reply.usage),
                total_ms=_elapsed_ms(started),
                metadata={"target_agent_id": target_agent_id},
                observation_policy=ROUTING_OBSERVATION_POLICY,
            )
            return AgentDispatchResult(
                target_agent_id=target_agent_id,
                route_run_id=run.run_id,
            )
        except Exception as exc:
            normalized = _normalize_dispatch_error(exc)
            error_code = str(
                getattr(normalized, "error_code", "") or "AGENT_ROUTING_FAILED"
            )
            self.run_history.set_llm_request_count(run.run_id, 1)
            self.run_history.finalize_total_timing(
                run.run_id, elapsed_ms=_elapsed_ms(started)
            )
            self.run_history.fail(run.run_id, error_code=error_code)
            self.observer.finalize_run(
                trace_handle,
                status="error",
                error_code=error_code,
                total_ms=_elapsed_ms(started),
                observation_policy=ROUTING_OBSERVATION_POLICY,
            )
            raise AgentDispatchError(
                route_run_id=run.run_id,
                error_code=error_code,
                detail=str(normalized),
            ) from exc


def _routing_system_prompt(catalog: dict[str, str]) -> str:
    lines = [
        "你是 main 顶层 agent 的内部路由阶段。",
        "选择一个 agent 完成本轮用户请求，并调用 agent_route。",
        "可选 agent：",
    ]
    lines.extend(f"- {agent_id}: {description}" for agent_id, description in catalog.items())
    return "\n".join(lines)


def _routing_tool_snapshot(agent_ids: list[str]) -> ToolSnapshot:
    schema = {
        "type": "object",
        "properties": {
            "target_agent_id": {
                "type": "string",
                "enum": list(agent_ids),
            }
        },
        "required": ["target_agent_id"],
        "additionalProperties": False,
    }
    return ToolSnapshot(
        tool_snapshot_id="tool_agent_route",
        builtin_tools=["agent_route"],
        tool_metadata={
            "agent_route": {
                "source_kind": "builtin",
                "server_id": "",
                "backend_id": "",
                "description": "Select the top-level agent that should handle the current user turn.",
                "parameters_schema": schema,
                "observation_policy": ROUTING_OBSERVATION_POLICY,
            }
        },
    )


def _validate_route_reply(reply, catalog: dict[str, str]) -> str:  # noqa: ANN001
    if str(reply.tool_name or "").strip() != "agent_route":
        raise ValueError("agent routing model did not call agent_route")
    target_agent_id = str(reply.tool_payload.get("target_agent_id") or "").strip()
    if target_agent_id not in catalog:
        raise ValueError(f"agent routing selected unauthorized target {target_agent_id}")
    return target_agent_id


def _normalize_dispatch_error(exc: Exception) -> Exception:
    if isinstance(exc, ProviderTransportError):
        return exc
    if isinstance(exc, (TimeoutError, OSError)) or str(exc).startswith("provider_"):
        return normalize_provider_error(exc)
    return exc


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
