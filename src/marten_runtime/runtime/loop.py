import json
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.runtime.context import RuntimeContext, assemble_runtime_context
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.history import CompactionDiagnostics, InMemoryRunHistory
from marten_runtime.runtime.direct_rendering import maybe_render_tool_followup_text
from marten_runtime.runtime.recovery_flow import (
    is_generic_tool_failure_text,
    recover_successful_tool_followup_text,
    recover_tool_result_text,
)
from marten_runtime.runtime.llm_client import (
    ConversationMessage,
    LLMClient,
    LLMReply,
    LLMRequest,
    ToolExchange,
    estimate_request_usage,
    estimate_request_tokens,
)
from marten_runtime.runtime.provider_retry import (
    ProviderTransportError,
    normalize_provider_error,
)
from marten_runtime.runtime.tool_calls import (
    ToolCallRejected,
    ToolExecutionFailed,
    resolve_tool_call,
)
from marten_runtime.runtime.tool_episode_summary_prompt import (
    ToolEpisodeSummaryDraft,
)
from marten_runtime.runtime.tool_outcome_extractor import extract_tool_outcome_summary
from marten_runtime.runtime.tool_outcome_flow import (
    collect_structured_hint_facts,
    infer_episode_source_kind,
    merge_tool_episode_facts,
    resolve_summary_volatile_flag,
)
from marten_runtime.session.compaction_trigger import (
    CompactionDecision,
    CompactionSettings,
    decide_compaction,
    has_continuation_demand,
    is_reactive_compaction_error,
)
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.compaction_runner import run_compaction
from marten_runtime.session.models import SessionMessage
from marten_runtime.session.tool_outcome_summary import (
    ToolOutcomeFact,
    ToolOutcomeSummary,
)
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.tools.registry import ToolRegistry, ToolSnapshot
from marten_runtime.tools.builtins.runtime_tool import (
    annotate_runtime_context_status_peak,
    render_runtime_context_status_text,
)


DEFAULT_ALLOWED_TOOLS = [
    "automation",
    "mcp",
    "runtime",
    "self_improve",
    "skill",
    "time",
]


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

    @staticmethod
    def _build_request_from_context(
        *,
        session_id: str,
        trace_id: str,
        message: str,
        agent_id: str,
        app_id: str,
        model_name: str | None,
        tokenizer_family: str | None,
        channel_protocol_instruction_text: str | None,
        tool_snapshot: ToolSnapshot,
        request_kind: str,
        ctx: RuntimeContext,
        include_available_tools: bool = False,
        bootstrap_manifest_id: str | None = None,
        prompt_mode: str | None = None,
        **overrides: object,
    ) -> LLMRequest:
        fields: dict[str, object] = {
            "session_id": session_id,
            "trace_id": trace_id,
            "message": message,
            "agent_id": agent_id,
            "app_id": app_id,
            "model_name": model_name,
            "tokenizer_family": tokenizer_family,
            "system_prompt": ctx.system_prompt,
            "conversation_messages": [
                ConversationMessage(role=item.role, content=item.content)
                for item in ctx.conversation_messages
            ],
            "compact_summary_text": ctx.compact_summary_text,
            "tool_outcome_summary_text": ctx.tool_outcome_summary_text,
            "working_context_text": ctx.working_context_text,
            "skill_heads_text": ctx.skill_heads_text,
            "capability_catalog_text": ctx.capability_catalog_text,
            "always_on_skill_text": ctx.always_on_skill_text,
            "channel_protocol_instruction_text": channel_protocol_instruction_text,
            "activated_skill_bodies": ctx.activated_skill_bodies,
            "tool_snapshot": tool_snapshot,
            "request_kind": request_kind,
        }
        if include_available_tools:
            fields["available_tools"] = tool_snapshot.available_tools()
        if ctx.working_context is not None:
            fields["working_context"] = ctx.working_context
        if ctx.context_snapshot_id:
            fields["context_snapshot_id"] = ctx.context_snapshot_id
        if ctx.skill_snapshot is not None:
            fields["skill_snapshot_id"] = ctx.skill_snapshot.skill_snapshot_id
            fields["activated_skill_ids"] = ctx.activated_skill_ids
        if bootstrap_manifest_id:
            fields["bootstrap_manifest_id"] = bootstrap_manifest_id
        if prompt_mode:
            fields["prompt_mode"] = prompt_mode
        fields.update(overrides)
        return LLMRequest(**fields)

    def run(
        self,
        session_id: str,
        message: str,
        trace_id: str | None = None,
        llm_client: LLMClient | None = None,
        system_prompt: str | None = None,
        agent: AgentSpec | None = None,
        config_snapshot_id: str = "cfg_bootstrap",
        bootstrap_manifest_id: str = "boot_default",
        model_profile_name: str | None = None,
        tokenizer_family: str | None = None,
        skill_snapshot_id: str = "skill_default",
        session_messages: list[SessionMessage] | None = None,
        compacted_context: CompactedContext | None = None,
        compact_llm_client: LLMClient | None = None,
        on_compacted: Callable[[CompactedContext], None] | None = None,
        skill_snapshot: SkillSnapshot | None = None,
        skill_heads_text: str | None = None,
        capability_catalog_text: str | None = None,
        always_on_skill_text: str | None = None,
        channel_protocol_instruction_text: str | None = None,
        activated_skill_ids: list[str] | None = None,
        activated_skill_bodies: list[str] | None = None,
        compact_settings: CompactionSettings | None = None,
        recent_tool_outcome_summaries: list[dict[str, object]] | None = None,
        request_kind: str = "interactive",
    ) -> list[OutboundEvent]:
        trace_id = trace_id or f"trace_{uuid4().hex[:8]}"
        llm_request_count = 0
        run_started_at = time.perf_counter()
        resolved_agent = agent or AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=list(DEFAULT_ALLOWED_TOOLS),
        )
        resolved_llm = llm_client or self.llm
        resolved_compact_settings = compact_settings or CompactionSettings()
        tool_snapshot = self.tools.build_snapshot(resolved_agent.allowed_tools)
        resolved_compacted_context = compacted_context
        rough_request = LLMRequest(
            session_id=session_id,
            trace_id=trace_id,
            message=message,
            agent_id=resolved_agent.agent_id,
            app_id=resolved_agent.app_id,
            model_name=getattr(resolved_llm, "model_name", None),
            tokenizer_family=tokenizer_family,
            system_prompt=system_prompt,
            conversation_messages=[
                ConversationMessage(role=item.role, content=item.content)
                for item in (session_messages or [])
                if item.role in {"user", "assistant"}
            ],
            skill_snapshot=skill_snapshot
            or SkillSnapshot(skill_snapshot_id=skill_snapshot_id),
            skill_heads_text=skill_heads_text,
            capability_catalog_text=capability_catalog_text,
            always_on_skill_text=always_on_skill_text,
            channel_protocol_instruction_text=channel_protocol_instruction_text,
            activated_skill_bodies=list(activated_skill_bodies or []),
            tool_snapshot=tool_snapshot,
            request_kind=request_kind,
        )
        estimated_tokens_before = estimate_request_tokens(rough_request)
        decision = (
            CompactionDecision.NONE
            if resolved_compacted_context is not None
            else decide_compaction(
                estimated_tokens=estimated_tokens_before,
                settings=resolved_compact_settings,
                has_follow_up_work=has_continuation_demand(
                    current_message=message,
                    recent_messages=[
                        item.content
                        for item in (session_messages or [])
                        if item.role in {"user", "assistant"}
                    ],
                ),
            )
        )
        if (
            resolved_compacted_context is None
            and decision == CompactionDecision.PROACTIVE
        ):
            resolved_compacted_context = run_compaction(
                llm=compact_llm_client or resolved_llm,
                session_id=session_id,
                current_message=message,
                session_messages=session_messages,
            )
            if resolved_compacted_context is not None and on_compacted is not None:
                on_compacted(resolved_compacted_context)
        runtime_context = assemble_runtime_context(
            session_id=session_id,
            current_message=message,
            system_prompt=system_prompt,
            session_messages=session_messages,
            tool_snapshot=tool_snapshot,
            compacted_context=resolved_compacted_context,
            skill_snapshot=skill_snapshot,
            activated_skill_ids=activated_skill_ids,
            skill_heads_text=skill_heads_text,
            capability_catalog_text=capability_catalog_text,
            always_on_skill_text=always_on_skill_text,
            channel_protocol_instruction_text=channel_protocol_instruction_text,
            activated_skill_bodies=activated_skill_bodies,
            recent_tool_outcome_summaries=recent_tool_outcome_summaries,
        )
        resolved_skill_snapshot_id = (
            skill_snapshot.skill_snapshot_id
            if skill_snapshot is not None
            else skill_snapshot_id
        )
        pre_compact_runtime_context = assemble_runtime_context(
            session_id=session_id,
            current_message=message,
            system_prompt=system_prompt,
            session_messages=session_messages,
            tool_snapshot=tool_snapshot,
            compacted_context=None,
            skill_snapshot=skill_snapshot,
            activated_skill_ids=activated_skill_ids,
            skill_heads_text=skill_heads_text,
            capability_catalog_text=capability_catalog_text,
            always_on_skill_text=always_on_skill_text,
            channel_protocol_instruction_text=channel_protocol_instruction_text,
            activated_skill_bodies=activated_skill_bodies,
            recent_tool_outcome_summaries=recent_tool_outcome_summaries,
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
        request_base = dict(
            session_id=session_id,
            trace_id=trace_id,
            message=message,
            agent_id=resolved_agent.agent_id,
            app_id=resolved_agent.app_id,
            model_name=getattr(resolved_llm, "model_name", None),
            tokenizer_family=tokenizer_family,
            channel_protocol_instruction_text=channel_protocol_instruction_text,
            tool_snapshot=tool_snapshot,
            request_kind=request_kind,
        )
        pre_compact_request_estimate = estimate_request_tokens(
            self._build_request_from_context(
                **request_base,
                ctx=pre_compact_runtime_context,
            )
        )
        first_request_estimate = estimate_request_tokens(
            self._build_request_from_context(
                **request_base,
                ctx=runtime_context,
            )
        )
        self.history.set_compaction(
            run.run_id,
            CompactionDiagnostics(
                decision=decision.value
                if hasattr(decision, "value")
                else str(decision),
                effective_window_tokens=resolved_compact_settings.effective_window,
                advisory_threshold_tokens=resolved_compact_settings.advisory_threshold,
                proactive_threshold_tokens=resolved_compact_settings.proactive_threshold,
                estimated_input_tokens_before=pre_compact_request_estimate,
                estimated_input_tokens_after=first_request_estimate,
                used_compacted_context=resolved_compacted_context is not None,
                compacted_context_id=(
                    resolved_compacted_context.compact_id
                    if resolved_compacted_context is not None
                    else None
                ),
            ),
        )
        first_request_usage = estimate_request_usage(
            self._build_request_from_context(
                **request_base,
                ctx=runtime_context,
                include_available_tools=True,
            )
        )
        self.history.set_preflight_usage(
            run.run_id,
            input_tokens_estimate=first_request_usage.input_tokens_estimate,
            estimator_kind=first_request_usage.estimator_kind,
            peak_input_tokens_estimate=first_request_usage.input_tokens_estimate,
            peak_stage="initial_request",
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
        first_request = self._build_request_from_context(
            **request_base,
            ctx=runtime_context,
            include_available_tools=True,
            bootstrap_manifest_id=bootstrap_manifest_id,
            prompt_mode=resolved_agent.prompt_mode,
        )
        tool_history: list[ToolExchange] = []
        current_request = first_request
        latest_actual_usage = None
        for _ in range(self.max_tool_rounds + 1):
            try:
                self.request_count += 1
                llm_request_count += 1
                llm_started_at = time.perf_counter()
                reply = resolved_llm.complete(current_request)
                provider_diagnostics = getattr(
                    resolved_llm, "last_call_diagnostics", None
                )
                if provider_diagnostics is not None:
                    self.history.record_provider_call(
                        run.run_id,
                        stage="llm_first" if not tool_history else "llm_second",
                        diagnostics=provider_diagnostics,
                    )
                if reply.usage is not None:
                    latest_actual_usage = reply.usage
                    self.history.set_actual_usage(
                        run.run_id,
                        reply.usage,
                        stage="llm_first" if not tool_history else "llm_second",
                    )
                self.history.set_stage_timing(
                    run.run_id,
                    stage="llm_first" if not tool_history else "llm_second",
                    elapsed_ms=_elapsed_ms(llm_started_at),
                )
                try:
                    tool_started_at = time.perf_counter()
                    tool_result = resolve_tool_call(
                        reply,
                        self.tools,
                        tool_snapshot,
                        tool_context={
                            "run_id": run.run_id,
                            "session_id": session_id,
                            "trace_id": trace_id,
                            "message": message,
                            "agent_id": resolved_agent.agent_id,
                            "app_id": resolved_agent.app_id,
                            "model_profile": model_profile_name
                            or getattr(resolved_llm, "profile_name", "unknown"),
                            "current_request": current_request,
                            "latest_actual_usage": latest_actual_usage,
                            "compact_settings": resolved_compact_settings,
                            "compacted_context": resolved_compacted_context,
                        },
                    )
                    if tool_result is not None:
                        self.history.set_stage_timing(
                            run.run_id,
                            stage="tool",
                            elapsed_ms=_elapsed_ms(tool_started_at),
                        )
                except ToolCallRejected as exc:
                    if tool_history:
                        recovered_text = recover_tool_result_text(tool_history)
                        if recovered_text:
                            return self._finish_run_success(
                                events=events,
                                session_id=session_id,
                                run_id=run.run_id,
                                trace_id=trace_id,
                                run_started_at=run_started_at,
                                llm_request_count=llm_request_count,
                                message=message,
                                agent_id=resolved_agent.agent_id,
                                final_text=recovered_text,
                                tool_history=tool_history,
                                tool_snapshot=tool_snapshot,
                            )
                    return self._finish_run_error(
                        events=events,
                        session_id=session_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        error_code=exc.error_code,
                        error_text=_tool_rejection_text(exc.error_code),
                    )
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
                    self.history.set_stage_timing(
                        run.run_id,
                        stage="tool",
                        elapsed_ms=_elapsed_ms(tool_started_at),
                    )
                    return self._finish_run_error(
                        events=events,
                        session_id=session_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        error_code=exc.error_code,
                        error_text="工具执行失败，请重试。",
                    )
            except Exception as exc:
                provider_diagnostics = getattr(
                    resolved_llm, "last_call_diagnostics", None
                )
                if provider_diagnostics is not None:
                    self.history.record_provider_call(
                        run.run_id,
                        stage="llm_first" if not tool_history else "llm_second",
                        diagnostics=provider_diagnostics,
                    )
                self.history.set_stage_timing(
                    run.run_id,
                    stage="llm_first" if not tool_history else "llm_second",
                    elapsed_ms=_elapsed_ms(llm_started_at),
                )
                if _is_provider_failure(exc):
                    normalized = normalize_provider_error(exc)
                    if (
                        resolved_compacted_context is None
                        and is_reactive_compaction_error(exc)
                    ):
                        decision = CompactionDecision.REACTIVE
                        resolved_compacted_context = run_compaction(
                            llm=compact_llm_client or resolved_llm,
                            session_id=session_id,
                            current_message=message,
                            session_messages=session_messages,
                        )
                        if resolved_compacted_context is not None:
                            if on_compacted is not None:
                                on_compacted(resolved_compacted_context)
                            runtime_context = assemble_runtime_context(
                                session_id=session_id,
                                current_message=message,
                                system_prompt=system_prompt,
                                session_messages=session_messages,
                                compacted_context=resolved_compacted_context,
                                tool_snapshot=tool_snapshot,
                                skill_snapshot=skill_snapshot,
                                activated_skill_ids=activated_skill_ids,
                                skill_heads_text=skill_heads_text,
                                capability_catalog_text=capability_catalog_text,
                                always_on_skill_text=always_on_skill_text,
                                channel_protocol_instruction_text=channel_protocol_instruction_text,
                                activated_skill_bodies=activated_skill_bodies,
                            )
                            first_request = first_request.model_copy(
                                update={
                                    "conversation_messages": [
                                        ConversationMessage(
                                            role=item.role, content=item.content
                                        )
                                        for item in runtime_context.conversation_messages
                                    ],
                                    "compact_summary_text": runtime_context.compact_summary_text,
                                    "working_context": runtime_context.working_context,
                                    "working_context_text": runtime_context.working_context_text,
                                    "context_snapshot_id": runtime_context.context_snapshot_id,
                                }
                            )
                            current_request = first_request.model_copy(
                                update={
                                    "tool_history": list(tool_history),
                                }
                            )
                            self.history.set_compaction(
                                run.run_id,
                                CompactionDiagnostics(
                                    decision=decision.value
                                    if hasattr(decision, "value")
                                    else str(decision),
                                    effective_window_tokens=resolved_compact_settings.effective_window,
                                    advisory_threshold_tokens=resolved_compact_settings.advisory_threshold,
                                    proactive_threshold_tokens=resolved_compact_settings.proactive_threshold,
                                    estimated_input_tokens_before=pre_compact_request_estimate,
                                    estimated_input_tokens_after=estimate_request_tokens(
                                        current_request
                                    ),
                                    used_compacted_context=True,
                                    compacted_context_id=resolved_compacted_context.compact_id,
                                ),
                            )
                            continue
                    if tool_history:
                        recovered_text = recover_tool_result_text(tool_history)
                        if recovered_text:
                            return self._finish_run_success(
                                events=events,
                                session_id=session_id,
                                run_id=run.run_id,
                                trace_id=trace_id,
                                run_started_at=run_started_at,
                                llm_request_count=llm_request_count,
                                message=message,
                                agent_id=resolved_agent.agent_id,
                                final_text=recovered_text,
                                tool_history=tool_history,
                                tool_snapshot=tool_snapshot,
                            )
                    self._record_failure(
                        agent_id=resolved_agent.agent_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        error_code=normalized.error_code,
                        error_stage="llm",
                        message=message,
                        summary=str(exc),
                        provider_name=getattr(resolved_llm, "provider_name", None),
                    )
                    return self._finish_run_error(
                        events=events,
                        session_id=session_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        error_code=normalized.error_code,
                        error_text="暂时没有生成可见回复，请重试。",
                    )
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
                return self._finish_run_error(
                    events=events,
                    session_id=session_id,
                    run_id=run.run_id,
                    trace_id=trace_id,
                    run_started_at=run_started_at,
                    llm_request_count=llm_request_count,
                    error_code="RUNTIME_LOOP_FAILED",
                    error_text="暂时没有生成可见回复，请重试。",
                )
            if tool_result is None:
                final_text = (reply.final_text or "").strip()
                if final_text and is_generic_tool_failure_text(final_text):
                    recovered_text = recover_successful_tool_followup_text(tool_history)
                    if recovered_text:
                        final_text = recovered_text
                if not final_text:
                    return self._finish_run_error(
                        events=events,
                        session_id=session_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        error_code="EMPTY_FINAL_RESPONSE",
                        error_text="暂时没有生成可见回复，请重试。",
                    )
                return self._finish_run_success(
                    events=events,
                    session_id=session_id,
                    run_id=run.run_id,
                    trace_id=trace_id,
                    run_started_at=run_started_at,
                    llm_request_count=llm_request_count,
                    message=message,
                    agent_id=resolved_agent.agent_id,
                    final_text=final_text,
                    tool_history=tool_history,
                    tool_snapshot=tool_snapshot,
                    combined_summary_draft=reply.tool_episode_summary_draft,
                )
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
            if isinstance(tool_result, dict) and (reply.tool_name or "") == "runtime":
                run_record = self.history.get(run.run_id)
                tool_result = annotate_runtime_context_status_peak(
                    tool_result,
                    peak_input_tokens_estimate=(
                        run_record.peak_preflight_input_tokens_estimate
                        or run_record.initial_preflight_input_tokens_estimate
                        or 0
                    ),
                    peak_stage=run_record.peak_preflight_stage or "initial_request",
                    actual_peak_input_tokens=run_record.actual_peak_input_tokens,
                    actual_peak_output_tokens=run_record.actual_peak_output_tokens,
                    actual_peak_total_tokens=run_record.actual_peak_total_tokens,
                    actual_peak_stage=run_record.actual_peak_stage,
                )
                tool_history[-1].tool_result = tool_result
                rendered_runtime_text = render_runtime_context_status_text(tool_result)
                if rendered_runtime_text:
                    return self._finish_run_success(
                        events=events,
                        session_id=session_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        message=message,
                        agent_id=resolved_agent.agent_id,
                        final_text=rendered_runtime_text,
                        tool_history=tool_history,
                        tool_snapshot=tool_snapshot,
                    )
            rendered_direct_text = maybe_render_tool_followup_text(
                reply.tool_name or "",
                tool_result,
                tool_payload=reply.tool_payload,
            )
            if rendered_direct_text:
                return self._finish_run_success(
                    events=events,
                    session_id=session_id,
                    run_id=run.run_id,
                    trace_id=trace_id,
                    run_started_at=run_started_at,
                    llm_request_count=llm_request_count,
                    message=message,
                    agent_id=resolved_agent.agent_id,
                    final_text=rendered_direct_text,
                    tool_history=tool_history,
                    tool_snapshot=tool_snapshot,
                )
            provisional_request = first_request.model_copy(
                update={
                    "tool_history": list(tool_history),
                    "tool_result": tool_result,
                    "requested_tool_name": reply.tool_name,
                    "requested_tool_payload": reply.tool_payload,
                }
            )
            followup_usage = estimate_request_usage(provisional_request)
            self.history.update_peak_preflight_usage(
                run.run_id,
                input_tokens_estimate=followup_usage.input_tokens_estimate,
                stage="tool_followup",
            )
            current_request = first_request.model_copy(
                update={
                    "tool_history": list(tool_history),
                    "tool_result": tool_result,
                    "requested_tool_name": reply.tool_name,
                    "requested_tool_payload": reply.tool_payload,
                }
            )
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
        return self._finish_run_error(
            events=events,
            session_id=session_id,
            run_id=run.run_id,
            trace_id=trace_id,
            run_started_at=run_started_at,
            llm_request_count=llm_request_count,
            error_code="TOOL_LOOP_LIMIT_EXCEEDED",
            error_text="tool_loop_limit_exceeded",
        )

    def _finish_run_success(
        self,
        *,
        events: list[OutboundEvent],
        session_id: str,
        run_id: str,
        trace_id: str,
        run_started_at: float,
        llm_request_count: int,
        message: str,
        agent_id: str,
        final_text: str,
        tool_history: list[ToolExchange],
        tool_snapshot: ToolSnapshot,
        combined_summary_draft: ToolEpisodeSummaryDraft | None = None,
    ) -> list[OutboundEvent]:
        events.append(
            OutboundEvent(
                session_id=session_id,
                run_id=run_id,
                event_id=f"evt_{uuid4().hex[:8]}",
                event_type="final",
                sequence=2,
                trace_id=trace_id,
                payload={"text": final_text},
                created_at=datetime.now(timezone.utc),
            )
        )
        self._append_post_turn_summary(
            user_message=message,
            history=tool_history,
            final_text=final_text,
            combined_summary_draft=combined_summary_draft,
            run_id=run_id,
            tool_snapshot=tool_snapshot,
        )
        self.history.finish(run_id, delivery_status="final")
        self.history.finalize_total_timing(
            run_id, elapsed_ms=_elapsed_ms(run_started_at)
        )
        self.history.set_llm_request_count(run_id, llm_request_count)
        self._record_recovery(
            agent_id=agent_id,
            run_id=run_id,
            trace_id=trace_id,
            message=message,
        )
        return events

    def _finish_run_error(
        self,
        *,
        events: list[OutboundEvent],
        session_id: str,
        run_id: str,
        trace_id: str,
        run_started_at: float,
        llm_request_count: int,
        error_code: str,
        error_text: str,
    ) -> list[OutboundEvent]:
        events.append(
            OutboundEvent(
                session_id=session_id,
                run_id=run_id,
                event_id=f"evt_{uuid4().hex[:8]}",
                event_type="error",
                sequence=2,
                trace_id=trace_id,
                payload={"code": error_code, "text": error_text},
                created_at=datetime.now(timezone.utc),
            )
        )
        self.history.fail(run_id, error_code=error_code)
        self.history.finalize_total_timing(
            run_id, elapsed_ms=_elapsed_ms(run_started_at)
        )
        self.history.set_llm_request_count(run_id, llm_request_count)
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

    def _append_post_turn_summary(
        self,
        *,
        user_message: str,
        history: list[ToolExchange],
        final_text: str,
        combined_summary_draft: ToolEpisodeSummaryDraft | None,
        run_id: str,
        tool_snapshot: ToolSnapshot,
    ) -> None:
        if not history or not final_text.strip():
            return
        latest = history[-1]
        if (
            latest.tool_name == "runtime"
            and str(
                (latest.tool_result or {}).get("action")
                or (latest.tool_payload or {}).get("action")
                or ""
            )
            == "context_status"
        ):
            return
        if any(item.tool_name in {"self_improve", "automation"} for item in history):
            return
        summary = self._summarize_completed_tool_episode(
            user_message=user_message,
            history=history,
            final_text=final_text,
            combined_summary_draft=combined_summary_draft,
            run_id=run_id,
            tool_snapshot=tool_snapshot,
        )
        if summary is not None:
            self.history.append_tool_outcome_summary(run_id, summary)

    def _summarize_completed_tool_episode(
        self,
        *,
        user_message: str,
        history: list[ToolExchange],
        final_text: str,
        combined_summary_draft: ToolEpisodeSummaryDraft | None,
        run_id: str,
        tool_snapshot: ToolSnapshot,
    ) -> ToolOutcomeSummary | None:
        try:
            fallback_summary = self._fallback_tool_episode_summary(
                run_id=run_id,
                history=history,
                final_text=final_text,
                tool_snapshot=tool_snapshot,
            )
            draft = combined_summary_draft
            if draft is not None and draft.summary.strip():
                structured_facts = collect_structured_hint_facts(history)
                fallback_facts = (
                    list(fallback_summary.facts) if fallback_summary is not None else []
                )
                facts = merge_tool_episode_facts(
                    draft.facts,
                    [*structured_facts, *fallback_facts]
                    if structured_facts
                    else fallback_facts,
                )
                volatile = resolve_summary_volatile_flag(
                    draft_volatile=draft.volatile,
                    facts=facts,
                    fallback_summary=fallback_summary,
                )
                keep_next_turn = bool(
                    (
                        draft.keep_next_turn
                        or bool(
                            fallback_summary is not None
                            and fallback_summary.keep_next_turn
                        )
                    )
                    and not bool(
                        fallback_summary is not None
                        and not fallback_summary.keep_next_turn
                    )
                    and not volatile
                )
                refresh_hint = draft.refresh_hint or (
                    fallback_summary.refresh_hint
                    if fallback_summary is not None
                    else ""
                )
                return ToolOutcomeSummary.create(
                    run_id=run_id,
                    source_kind=infer_episode_source_kind(history, tool_snapshot),
                    summary_text=draft.summary,
                    facts=facts,
                    volatile=volatile,
                    keep_next_turn=keep_next_turn,
                    refresh_hint=refresh_hint,
                )
        except Exception:
            logger.debug("tool episode summary extraction failed", exc_info=True)
        return self._fallback_tool_episode_summary(
            run_id=run_id,
            history=history,
            final_text=final_text,
            tool_snapshot=tool_snapshot,
        )

    def _fallback_tool_episode_summary(
        self,
        *,
        run_id: str,
        history: list[ToolExchange],
        final_text: str,
        tool_snapshot: ToolSnapshot,
    ) -> ToolOutcomeSummary | None:
        summary = self._extract_rule_based_tool_outcome_summary(
            run_id=run_id,
            history=history,
            tool_snapshot=tool_snapshot,
        )
        if summary is not None:
            return summary
        if not final_text.strip():
            return None
        return ToolOutcomeSummary.create(
            run_id=run_id,
            source_kind=infer_episode_source_kind(history, tool_snapshot),
            summary_text=f"上一轮工具调用完成：{final_text.strip()}",
        )

    def _extract_rule_based_tool_outcome_summary(
        self,
        *,
        run_id: str,
        history: list[ToolExchange],
        tool_snapshot: ToolSnapshot,
    ) -> ToolOutcomeSummary | None:
        latest = history[-1]
        return extract_tool_outcome_summary(
            run_id=run_id,
            tool_name=latest.tool_name,
            tool_payload=latest.tool_payload,
            tool_result=latest.tool_result,
            tool_metadata=tool_snapshot.tool_metadata.get(latest.tool_name, {}),
        )

def _is_provider_failure(exc: Exception) -> bool:
    if isinstance(exc, (ProviderTransportError, TimeoutError, OSError)):
        return True
    return str(exc).startswith("provider_")


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))
