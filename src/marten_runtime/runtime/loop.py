import time
from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.runtime.context import assemble_runtime_context
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import ConversationMessage, LLMClient, LLMRequest, ToolExchange
from marten_runtime.runtime.provider_retry import ProviderTransportError, normalize_provider_error
from marten_runtime.runtime.tool_calls import ToolCallRejected, ToolExecutionFailed, resolve_tool_call
from marten_runtime.session.models import SessionMessage
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.tools.registry import ToolRegistry


def _tool_rejection_text(error_code: str) -> str:
    if error_code == "TOOL_NOT_ALLOWED":
        return "当前操作未被允许，请换个说法或缩小范围。"
    if error_code == "TOOL_NOT_FOUND":
        return "当前所需工具不可用，请稍后重试。"
    return error_code.lower()


class RuntimeLoop:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        history: InMemoryRunHistory,
        *,
        self_improve_recorder: SelfImproveRecorder | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.history = history
        self.self_improve_recorder = self_improve_recorder
        self.request_count = 0
        self.last_request_count = 0
        self.max_tool_rounds = 8

    def run(
        self,
        session_id: str,
        message: str,
        trace_id: str | None = None,
        system_prompt: str | None = None,
        agent: AgentSpec | None = None,
        config_snapshot_id: str = "cfg_bootstrap",
        bootstrap_manifest_id: str = "boot_default",
        skill_snapshot_id: str = "skill_default",
        session_messages: list[SessionMessage] | None = None,
        skill_snapshot: SkillSnapshot | None = None,
        skill_heads_text: str | None = None,
        capability_catalog_text: str | None = None,
        always_on_skill_text: str | None = None,
        activated_skill_ids: list[str] | None = None,
        activated_skill_bodies: list[str] | None = None,
    ) -> list[OutboundEvent]:
        trace_id = trace_id or f"trace_{uuid4().hex[:8]}"
        self.last_request_count = 0
        run_started_at = time.perf_counter()
        resolved_agent = agent or AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=self.tools.list(),
        )
        tool_snapshot = self.tools.build_snapshot(resolved_agent.allowed_tools)
        runtime_context = assemble_runtime_context(
            session_id=session_id,
            current_message=message,
            system_prompt=system_prompt,
            session_messages=session_messages,
            tool_snapshot=tool_snapshot,
            skill_snapshot=skill_snapshot,
            activated_skill_ids=activated_skill_ids,
            skill_heads_text=skill_heads_text,
            capability_catalog_text=capability_catalog_text,
            always_on_skill_text=always_on_skill_text,
            activated_skill_bodies=activated_skill_bodies,
        )
        resolved_skill_snapshot_id = (
            skill_snapshot.skill_snapshot_id if skill_snapshot is not None else skill_snapshot_id
        )
        run = self.history.start(
            session_id=session_id,
            trace_id=trace_id,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id=bootstrap_manifest_id,
            context_snapshot_id=runtime_context.context_snapshot_id,
            skill_snapshot_id=resolved_skill_snapshot_id,
            tool_snapshot_id=tool_snapshot.tool_snapshot_id,
        )
        events = [
            OutboundEvent(
                session_id=session_id,
                run_id=run.run_id,
                event_id=f"evt_{uuid4().hex[:8]}",
                event_type="progress",
                sequence=1,
                trace_id=trace_id,
                payload={"text": "running"},
                created_at=datetime.now(timezone.utc),
            )
        ]
        first_request = LLMRequest(
            session_id=session_id,
            trace_id=trace_id,
            message=message,
            agent_id=resolved_agent.agent_id,
            app_id=resolved_agent.app_id,
            system_prompt=runtime_context.system_prompt,
            conversation_messages=[
                ConversationMessage(role=item.role, content=item.content)
                for item in runtime_context.conversation_messages
            ],
            working_context=runtime_context.working_context,
            working_context_text=runtime_context.working_context_text,
            context_snapshot_id=runtime_context.context_snapshot_id,
            skill_snapshot_id=runtime_context.skill_snapshot.skill_snapshot_id,
            activated_skill_ids=runtime_context.activated_skill_ids,
            skill_heads_text=runtime_context.skill_heads_text,
            capability_catalog_text=runtime_context.capability_catalog_text,
            always_on_skill_text=runtime_context.always_on_skill_text,
            activated_skill_bodies=runtime_context.activated_skill_bodies,
            prompt_mode=resolved_agent.prompt_mode,
            bootstrap_manifest_id=bootstrap_manifest_id,
            available_tools=tool_snapshot.available_tools(),
            tool_snapshot=tool_snapshot,
        )
        tool_history: list[ToolExchange] = []
        current_request = first_request
        for _ in range(self.max_tool_rounds + 1):
            try:
                self.request_count += 1
                self.last_request_count += 1
                llm_started_at = time.perf_counter()
                reply = self.llm.complete(current_request)
                self.history.set_stage_timing(
                    run.run_id,
                    stage="llm_first" if not tool_history else "llm_second",
                    elapsed_ms=_elapsed_ms(llm_started_at),
                )
                try:
                    tool_started_at = time.perf_counter()
                    tool_result = resolve_tool_call(reply, self.tools, tool_snapshot)
                    if tool_result is not None:
                        self.history.set_stage_timing(
                            run.run_id,
                            stage="tool",
                            elapsed_ms=_elapsed_ms(tool_started_at),
                        )
                except ToolCallRejected as exc:
                    events.append(
                        OutboundEvent(
                            session_id=session_id,
                            run_id=run.run_id,
                            event_id=f"evt_{uuid4().hex[:8]}",
                            event_type="error",
                            sequence=2,
                            trace_id=trace_id,
                            payload={"code": exc.error_code, "text": _tool_rejection_text(exc.error_code)},
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                    self.history.fail(run.run_id, error_code=exc.error_code)
                    self.history.finalize_total_timing(run.run_id, elapsed_ms=_elapsed_ms(run_started_at))
                    self.history.set_llm_request_count(run.run_id, self.last_request_count)
                    return events
                except ToolExecutionFailed as exc:
                    self._record_failure(
                        agent_id=resolved_agent.agent_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        error_code=exc.error_code,
                        error_stage="tool",
                        message=message,
                        summary=str(exc),
                    )
                    events.append(
                        OutboundEvent(
                            session_id=session_id,
                            run_id=run.run_id,
                            event_id=f"evt_{uuid4().hex[:8]}",
                            event_type="error",
                            sequence=2,
                            trace_id=trace_id,
                            payload={
                                "code": exc.error_code,
                                "text": "工具执行失败，请重试。",
                            },
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                    self.history.fail(run.run_id, error_code=exc.error_code)
                    self.history.set_stage_timing(
                        run.run_id,
                        stage="tool",
                        elapsed_ms=_elapsed_ms(tool_started_at),
                    )
                    self.history.finalize_total_timing(run.run_id, elapsed_ms=_elapsed_ms(run_started_at))
                    self.history.set_llm_request_count(run.run_id, self.last_request_count)
                    return events
            except Exception as exc:
                self.history.set_stage_timing(
                    run.run_id,
                    stage="llm_first" if not tool_history else "llm_second",
                    elapsed_ms=_elapsed_ms(llm_started_at),
                )
                if _is_provider_failure(exc):
                    normalized = normalize_provider_error(exc)
                    self._record_failure(
                        agent_id=resolved_agent.agent_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        error_code=normalized.error_code,
                        error_stage="llm",
                        message=message,
                        summary=str(exc),
                        provider_name=getattr(self.llm, "provider_name", None),
                    )
                    events.append(
                        OutboundEvent(
                            session_id=session_id,
                            run_id=run.run_id,
                            event_id=f"evt_{uuid4().hex[:8]}",
                            event_type="error",
                            sequence=2,
                            trace_id=trace_id,
                            payload={
                                "code": normalized.error_code,
                                "text": "暂时没有生成可见回复，请重试。",
                            },
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                    self.history.fail(run.run_id, error_code=normalized.error_code)
                    self.history.finalize_total_timing(run.run_id, elapsed_ms=_elapsed_ms(run_started_at))
                    self.history.set_llm_request_count(run.run_id, self.last_request_count)
                    return events
                self._record_failure(
                    agent_id=resolved_agent.agent_id,
                    run_id=run.run_id,
                    trace_id=trace_id,
                    session_id=session_id,
                    error_code="RUNTIME_LOOP_FAILED",
                    error_stage="runtime",
                    message=message,
                    summary=str(exc),
                )
                events.append(
                    OutboundEvent(
                        session_id=session_id,
                        run_id=run.run_id,
                        event_id=f"evt_{uuid4().hex[:8]}",
                        event_type="error",
                        sequence=2,
                        trace_id=trace_id,
                        payload={
                            "code": "RUNTIME_LOOP_FAILED",
                            "text": "暂时没有生成可见回复，请重试。",
                        },
                        created_at=datetime.now(timezone.utc),
                    )
                )
                self.history.fail(run.run_id, error_code="RUNTIME_LOOP_FAILED")
                self.history.finalize_total_timing(run.run_id, elapsed_ms=_elapsed_ms(run_started_at))
                self.history.set_llm_request_count(run.run_id, self.last_request_count)
                return events
            if tool_result is None:
                final_text = (reply.final_text or "").strip()
                if not final_text:
                    events.append(
                        OutboundEvent(
                            session_id=session_id,
                            run_id=run.run_id,
                            event_id=f"evt_{uuid4().hex[:8]}",
                            event_type="error",
                            sequence=2,
                            trace_id=trace_id,
                            payload={
                                "code": "EMPTY_FINAL_RESPONSE",
                                "text": "暂时没有生成可见回复，请重试。",
                            },
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                    self.history.fail(run.run_id, error_code="EMPTY_FINAL_RESPONSE")
                    self.history.finalize_total_timing(run.run_id, elapsed_ms=_elapsed_ms(run_started_at))
                    self.history.set_llm_request_count(run.run_id, self.last_request_count)
                    return events
                events.append(
                    OutboundEvent(
                        session_id=session_id,
                        run_id=run.run_id,
                        event_id=f"evt_{uuid4().hex[:8]}",
                        event_type="final",
                        sequence=2,
                        trace_id=trace_id,
                        payload={"text": final_text},
                        created_at=datetime.now(timezone.utc),
                    )
                )
                self.history.finish(run.run_id, delivery_status="final")
                self.history.finalize_total_timing(run.run_id, elapsed_ms=_elapsed_ms(run_started_at))
                self.history.set_llm_request_count(run.run_id, self.last_request_count)
                self._record_recovery(
                    agent_id=resolved_agent.agent_id,
                    run_id=run.run_id,
                    trace_id=trace_id,
                    message=message,
                )
                return events
            tool_history.append(
                ToolExchange(
                    tool_name=reply.tool_name or "",
                    tool_payload=reply.tool_payload,
                    tool_result=tool_result,
                )
            )
            self.history.record_tool_call(
                run.run_id,
                tool_name=reply.tool_name or "",
                tool_payload=reply.tool_payload,
                tool_result=tool_result,
            )
            current_request = first_request.model_copy(
                update={
                    "tool_history": list(tool_history),
                    "tool_result": tool_result,
                    "requested_tool_name": reply.tool_name,
                    "requested_tool_payload": reply.tool_payload,
                }
            )
        events.append(
            OutboundEvent(
                session_id=session_id,
                run_id=run.run_id,
                event_id=f"evt_{uuid4().hex[:8]}",
                event_type="error",
                sequence=2,
                trace_id=trace_id,
                payload={"code": "TOOL_LOOP_LIMIT_EXCEEDED", "text": "tool_loop_limit_exceeded"},
                created_at=datetime.now(timezone.utc),
            )
        )
        self.history.fail(run.run_id, error_code="TOOL_LOOP_LIMIT_EXCEEDED")
        self.history.finalize_total_timing(run.run_id, elapsed_ms=_elapsed_ms(run_started_at))
        self.history.set_llm_request_count(run.run_id, self.last_request_count)
        self._record_failure(
            agent_id=resolved_agent.agent_id,
            run_id=run.run_id,
            trace_id=trace_id,
            session_id=session_id,
            error_code="TOOL_LOOP_LIMIT_EXCEEDED",
            error_stage="tool_loop",
            message=message,
            summary="tool loop limit exceeded",
        )
        return events

    def _record_failure(
        self,
        *,
        agent_id: str,
        run_id: str,
        trace_id: str,
        session_id: str,
        error_code: str,
        error_stage: str,
        message: str,
        summary: str,
        tool_name: str | None = None,
        provider_name: str | None = None,
    ) -> None:
        if self.self_improve_recorder is None:
            return
        self.self_improve_recorder.record_failure(
            agent_id=agent_id,
            run_id=run_id,
            trace_id=trace_id,
            session_id=session_id,
            error_code=error_code,
            error_stage=error_stage,
            tool_name=tool_name,
            provider_name=provider_name,
            summary=summary,
            message=message,
        )

    def _record_recovery(
        self,
        *,
        agent_id: str,
        run_id: str,
        trace_id: str,
        message: str,
    ) -> None:
        if self.self_improve_recorder is None:
            return
        self.self_improve_recorder.record_recovery(
            agent_id=agent_id,
            run_id=run_id,
            trace_id=trace_id,
            message=message,
            fix_summary="later successful completion on a compatible request",
            success_evidence="final reply generated",
        )


def _is_provider_failure(exc: Exception) -> bool:
    if isinstance(exc, (ProviderTransportError, TimeoutError, OSError)):
        return True
    return str(exc).startswith("provider_")


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))
