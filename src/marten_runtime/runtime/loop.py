import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4


from marten_runtime.agents.specs import AgentSpec
from marten_runtime.observability.langfuse import (
    LangfuseObserver,
    build_langfuse_observer,
)
from marten_runtime.runtime.context import RuntimeContext, assemble_runtime_context
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.history import CompactionDiagnostics, InMemoryRunHistory
from marten_runtime.runtime.run_outcome_flow import (
    elapsed_ms,
    finish_run_error,
    finish_run_success,
    is_provider_failure,
    provider_failure_text,
    record_failure,
    tool_rejection_text,
)
from marten_runtime.runtime.recovery_flow import (
    FinalizationAssessmentDetails,
    assess_finalization_text_with_details,
    derive_finalization_contract_flags,
    recover_successful_tool_followup_text_with_meta,
    recover_tool_result_text,
    violates_current_session_identity_contract,
    violates_session_switch_contract,
    violates_spawn_subagent_acceptance_contract,
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
from marten_runtime.runtime.llm_failover import (
    next_fallback_profile,
    should_failover,
)
from marten_runtime.runtime.provider_retry import normalize_provider_error
from marten_runtime.runtime.tool_calls import (
    ToolCallRejected,
    ToolExecutionFailed,
    resolve_tool_call,
)
from marten_runtime.runtime.tool_episode_summary_prompt import (
    ToolEpisodeSummaryDraft,
)
from marten_runtime.runtime.tool_followup_support import (
    append_tool_exchange,
    build_finalization_evidence_ledger,
    build_finalization_retry_request,
    build_tool_followup_request,
    normalize_tool_result_for_followup,
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
from marten_runtime.session.store import SessionStore
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.tools.registry import ToolRegistry, ToolSnapshot


DEFAULT_ALLOWED_TOOLS = [
    "automation",
    "mcp",
    "runtime",
    "self_improve",
    "session",
    "skill",
    "time",
]


def _build_contract_repair_request(
    base_request: LLMRequest,
    *,
    invalid_final_text: str,
) -> LLMRequest:
    return base_request.model_copy(
        update={
            "tool_history": [],
            "tool_result": None,
            "requested_tool_name": None,
            "requested_tool_payload": {},
            "request_kind": "contract_repair",
            "invalid_final_text": str(invalid_final_text or "").strip(),
        }
    )


def _is_duplicate_spawn_subagent_followup(
    request: LLMRequest,
    reply: LLMReply,
    tool_history: list[ToolExchange],
) -> bool:
    if str(request.requested_tool_name or "").strip() != "spawn_subagent":
        return False
    if str(reply.tool_name or "").strip() != "spawn_subagent":
        return False
    if not tool_history:
        return False
    latest = tool_history[-1]
    if latest.tool_name != "spawn_subagent":
        return False
    if not isinstance(latest.tool_result, dict):
        return False
    return str(latest.tool_result.get("status") or "").strip() == "accepted"


def _build_current_turn_evidence_ledger(
    *,
    user_message: str,
    tool_history: list[ToolExchange],
    model_request_count: int,
):
    requires_result_coverage, requires_round_trip_report = derive_finalization_contract_flags(
        user_message
    )
    return build_finalization_evidence_ledger(
        user_message=user_message,
        tool_history=tool_history,
        model_request_count=model_request_count,
        requires_result_coverage=requires_result_coverage,
        requires_round_trip_report=requires_round_trip_report,
    )


def _record_finalization_diagnostics(
    history: InMemoryRunHistory,
    *,
    run_id: str,
    request_kind: str,
    details: FinalizationAssessmentDetails,
    retry_triggered: bool,
    recovered_from_fragments: bool = False,
    invalid_final_text: str | None = None,
) -> None:
    history.set_finalization_state(
        run_id,
        assessment=details.assessment,
        request_kind=request_kind,
        required_evidence_count=len(details.required_evidence_items),
        missing_evidence_items=list(details.missing_evidence_items),
        retry_triggered=retry_triggered,
        recovered_from_fragments=recovered_from_fragments,
        invalid_final_text=invalid_final_text,
    )



class RuntimeLoop:

    @staticmethod
    def _raise_if_interrupted(
        stop_event: threading.Event | None,
        deadline_monotonic: float | None,
    ) -> None:
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("SUBAGENT_CANCELLED")
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            raise TimeoutError("SUBAGENT_TIMED_OUT")

    @staticmethod
    def _remaining_timeout_seconds(deadline_monotonic: float | None) -> float | None:
        if deadline_monotonic is None:
            return None
        return max(0.05, deadline_monotonic - time.monotonic())

    def _append_post_turn_summary(
        self,
        *,
        history: InMemoryRunHistory,
        user_message: str,
        tool_history: list[ToolExchange],
        final_text: str,
        combined_summary_draft: ToolEpisodeSummaryDraft | None,
        run_id: str,
        tool_snapshot: ToolSnapshot,
    ) -> None:
        from marten_runtime.runtime.run_outcome_flow import append_post_turn_summary

        append_post_turn_summary(
            history=history,
            user_message=user_message,
            tool_history=tool_history,
            final_text=final_text,
            combined_summary_draft=combined_summary_draft,
            run_id=run_id,
            tool_snapshot=tool_snapshot,
        )

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        history: InMemoryRunHistory,
        *,
        langfuse_observer: LangfuseObserver | None = None,
        self_improve_recorder: SelfImproveRecorder | None = None,
        self_improve_post_commit_callback=None,
        profile_runtime_resolver: Callable[[str], tuple[LLMClient, object]] | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.history = history
        self.langfuse_observer = (
            langfuse_observer if langfuse_observer is not None else build_langfuse_observer(env={})
        )
        self.self_improve_recorder = self_improve_recorder
        self.self_improve_post_commit_callback = self_improve_post_commit_callback
        self.profile_runtime_resolver = profile_runtime_resolver
        self.request_count = 0
        self.last_request_count = 0
        self.max_tool_rounds = 8

    @staticmethod
    def _request_for_client(
        request: LLMRequest,
        llm_client: LLMClient,
        *,
        tokenizer_family: str | None,
        timeout_seconds_override: float | None,
        stop_event: threading.Event | None,
        deadline_monotonic: float | None,
    ) -> LLMRequest:
        return request.model_copy(
            update={
                "model_name": getattr(llm_client, "model_name", None),
                "tokenizer_family": tokenizer_family,
                "timeout_seconds_override": timeout_seconds_override
                if timeout_seconds_override is not None
                else RuntimeLoop._remaining_timeout_seconds(deadline_monotonic),
                "cooperative_stop_event": stop_event,
                "cooperative_deadline_monotonic": deadline_monotonic,
            }
        )

    @staticmethod
    def _usage_payload(usage) -> dict[str, int] | None:  # noqa: ANN001
        if usage is None:
            return None
        return {
            "input_tokens": int(usage.input_tokens),
            "output_tokens": int(usage.output_tokens),
            "total_tokens": int(usage.total_tokens),
        }

    @staticmethod
    def _cumulative_usage_payload(run) -> dict[str, int] | None:  # noqa: ANN001
        total_tokens = int(run.actual_cumulative_total_tokens)
        if total_tokens <= 0:
            return None
        return {
            "input_tokens": int(run.actual_cumulative_input_tokens),
            "output_tokens": int(run.actual_cumulative_output_tokens),
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _generation_input_payload(request: LLMRequest) -> dict[str, object]:
        return {
            "message": request.message,
            "available_tools": list(request.available_tools),
            "requested_tool_name": request.requested_tool_name,
            "tool_history_count": len(request.tool_history),
        }

    @staticmethod
    def _generation_output_payload(reply: LLMReply) -> dict[str, object]:
        if reply.tool_name:
            return {
                "tool_name": reply.tool_name,
                "tool_payload": dict(reply.tool_payload),
            }
        return {"final_text": reply.final_text or ""}

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
            "memory_text": ctx.memory_text,
            "working_context_text": ctx.working_context_text,
            "skill_heads_text": ctx.skill_heads_text,
            "capability_catalog_text": ctx.capability_catalog_text,
            "always_on_skill_text": ctx.always_on_skill_text,
            "channel_protocol_instruction_text": channel_protocol_instruction_text,
            "activated_skill_bodies": ctx.activated_skill_bodies,
            "tool_snapshot": tool_snapshot,
            "request_kind": request_kind,
            "cooperative_stop_event": overrides.get("cooperative_stop_event"),
            "cooperative_deadline_monotonic": overrides.get("cooperative_deadline_monotonic"),
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
        memory_text: str | None = None,
        activated_skill_ids: list[str] | None = None,
        activated_skill_bodies: list[str] | None = None,
        compact_settings: CompactionSettings | None = None,
        recent_tool_outcome_summaries: list[dict[str, object]] | None = None,
        session_replay_user_turns: int = 8,
        request_kind: str = "interactive",
        parent_run_id: str | None = None,
        channel_id: str | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
        source_transport: str | None = None,
        session_store: SessionStore | None = None,
        stop_event: threading.Event | None = None,
        deadline_monotonic: float | None = None,
        timeout_seconds_override: float | None = None,
    ) -> list[OutboundEvent]:
        trace_id = trace_id or f"trace_{uuid4().hex[:8]}"
        llm_request_count = 0
        run_started_at = time.perf_counter()
        resolved_agent = agent or AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=list(DEFAULT_ALLOWED_TOOLS),
        )
        resolved_llm = llm_client or self.llm
        active_profile_name = (
            model_profile_name
            or getattr(resolved_llm, "profile_name", None)
            or "default"
        )
        active_tokenizer_family = tokenizer_family
        attempted_profiles: list[str] = [active_profile_name]
        attempted_providers: list[str] = [
            getattr(resolved_llm, "provider_name", "unknown")
        ]
        failover_trigger: str | None = None
        failover_stage: str | None = None
        failover_candidates: list[str] = []
        resolved_compact_settings = compact_settings or CompactionSettings()
        tool_snapshot = self.tools.build_snapshot(resolved_agent.allowed_tools)
        resolved_compacted_context = compacted_context
        active_context_session_id = session_id
        active_session_messages = list(session_messages or [])
        active_recent_tool_outcome_summaries = list(recent_tool_outcome_summaries or [])

        def register_failover_candidates(profile) -> None:  # noqa: ANN001
            for fallback_name in list(getattr(profile, "fallback_profiles", [])):
                if fallback_name in failover_candidates:
                    continue
                failover_candidates.append(fallback_name)

        if self.profile_runtime_resolver is not None:
            try:
                _, initial_profile = self.profile_runtime_resolver(active_profile_name)
            except ValueError:
                initial_profile = None
            if initial_profile is not None:
                register_failover_candidates(initial_profile)
        rough_request = LLMRequest(
            session_id=session_id,
            trace_id=trace_id,
            message=message,
            agent_id=resolved_agent.agent_id,
            app_id=resolved_agent.app_id,
            model_name=getattr(resolved_llm, "model_name", None),
            tokenizer_family=active_tokenizer_family,
            system_prompt=system_prompt,
            conversation_messages=[
                ConversationMessage(role=item.role, content=item.content)
                for item in active_session_messages
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
            cooperative_stop_event=stop_event,
            cooperative_deadline_monotonic=deadline_monotonic,
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
                        for item in active_session_messages
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
                session_id=active_context_session_id,
                current_message=message,
                session_messages=active_session_messages,
                preserved_tail_user_turns=session_replay_user_turns,
                trigger_kind="context_pressure_proactive",
            )
            if resolved_compacted_context is not None:
                if session_store is not None:
                    session_store.set_compacted_context(
                        active_context_session_id,
                        resolved_compacted_context,
                    )
                elif on_compacted is not None:
                    on_compacted(resolved_compacted_context)
        runtime_context = assemble_runtime_context(
            session_id=active_context_session_id,
            current_message=message,
            system_prompt=system_prompt,
            session_messages=active_session_messages,
            tool_snapshot=tool_snapshot,
            compacted_context=resolved_compacted_context,
            skill_snapshot=skill_snapshot,
            activated_skill_ids=activated_skill_ids,
            skill_heads_text=skill_heads_text,
            capability_catalog_text=capability_catalog_text,
            always_on_skill_text=always_on_skill_text,
            channel_protocol_instruction_text=channel_protocol_instruction_text,
            memory_text=memory_text,
            activated_skill_bodies=activated_skill_bodies,
            recent_tool_outcome_summaries=active_recent_tool_outcome_summaries,
            replay_user_turns=session_replay_user_turns,
        )
        resolved_skill_snapshot_id = (
            skill_snapshot.skill_snapshot_id
            if skill_snapshot is not None
            else skill_snapshot_id
        )
        pre_compact_runtime_context = assemble_runtime_context(
            session_id=active_context_session_id,
            current_message=message,
            system_prompt=system_prompt,
            session_messages=active_session_messages,
            tool_snapshot=tool_snapshot,
            compacted_context=None,
            skill_snapshot=skill_snapshot,
            activated_skill_ids=activated_skill_ids,
            skill_heads_text=skill_heads_text,
            capability_catalog_text=capability_catalog_text,
            always_on_skill_text=always_on_skill_text,
            channel_protocol_instruction_text=channel_protocol_instruction_text,
            memory_text=memory_text,
            activated_skill_bodies=activated_skill_bodies,
            recent_tool_outcome_summaries=active_recent_tool_outcome_summaries,
            replay_user_turns=session_replay_user_turns,
        )
        run = self.history.start(
            session_id=session_id,
            trace_id=trace_id,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id=bootstrap_manifest_id,
            context_snapshot_id=runtime_context.context_snapshot_id,
            skill_snapshot_id=resolved_skill_snapshot_id,
            tool_snapshot_id=tool_snapshot.tool_snapshot_id,
            parent_run_id=parent_run_id,
        )
        trace_handle = self.langfuse_observer.start_run_trace(
            name="runtime.turn",
            trace_id=trace_id,
            input_text=message,
            metadata={
                "run_id": run.run_id,
                "session_id": session_id,
                "agent_id": resolved_agent.agent_id,
                "app_id": resolved_agent.app_id,
                "channel_id": channel_id,
                "request_kind": request_kind,
                "config_snapshot_id": config_snapshot_id,
                "bootstrap_manifest_id": bootstrap_manifest_id,
                "parent_run_id": parent_run_id,
            },
            tags=[request_kind],
        )
        self.history.set_external_observability_refs(
            run.run_id,
            langfuse_trace_id=trace_handle.trace_id,
            langfuse_url=trace_handle.url,
        )
        request_base = dict(
            session_id=active_context_session_id,
            trace_id=trace_id,
            message=message,
            agent_id=resolved_agent.agent_id,
            app_id=resolved_agent.app_id,
            model_name=getattr(resolved_llm, "model_name", None),
            tokenizer_family=active_tokenizer_family,
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
        if (
            self.self_improve_recorder is not None
            and resolved_compacted_context is not None
            and decision == CompactionDecision.PROACTIVE
        ):
            self.self_improve_recorder.record_pre_compaction_learning_flush(
                agent_id=resolved_agent.agent_id,
                run_id=run.run_id,
                trace_id=trace_id,
                message=message,
                estimated_tokens_before=pre_compact_request_estimate,
                estimated_tokens_after=first_request_estimate,
                channel_id=channel_id,
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
        self.history.set_failover_state(
            run.run_id,
            provider_ref=getattr(resolved_llm, "provider_name", None),
            attempted_profiles=attempted_profiles,
            attempted_providers=attempted_providers,
            failover_trigger=failover_trigger,
            failover_stage=failover_stage,
            final_provider_ref=getattr(resolved_llm, "provider_name", None),
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

        def finalize_success(*, final_text: str) -> None:
            self.history.set_failover_state(
                run.run_id,
                provider_ref=attempted_providers[0] if attempted_providers else None,
                attempted_profiles=attempted_profiles,
                attempted_providers=attempted_providers,
                failover_trigger=failover_trigger,
                failover_stage=failover_stage,
                final_provider_ref=getattr(resolved_llm, "provider_name", None),
            )
            run_record = self.history.get(run.run_id)
            cumulative_usage_payload = self._cumulative_usage_payload(run_record)
            self.history.set_external_observability_refs(
                run.run_id,
                langfuse_trace_id=trace_handle.trace_id,
                langfuse_url=trace_handle.url,
            )
            self.langfuse_observer.finalize_run(
                trace_handle,
                status="succeeded",
                final_text=final_text,
                usage=cumulative_usage_payload,
                total_ms=elapsed_ms(run_started_at),
                metadata={
                    "llm_request_count": llm_request_count,
                    "request_kind": request_kind,
                    "agent_id": resolved_agent.agent_id,
                    "channel_id": channel_id,
                },
            )

        def finalize_error(*, error_code: str) -> None:
            self.history.set_failover_state(
                run.run_id,
                provider_ref=attempted_providers[0] if attempted_providers else None,
                attempted_profiles=attempted_profiles,
                attempted_providers=attempted_providers,
                failover_trigger=failover_trigger,
                failover_stage=failover_stage,
                final_provider_ref=getattr(resolved_llm, "provider_name", None),
            )
            run_record = self.history.get(run.run_id)
            cumulative_usage_payload = self._cumulative_usage_payload(run_record)
            self.history.set_external_observability_refs(
                run.run_id,
                langfuse_trace_id=trace_handle.trace_id,
                langfuse_url=trace_handle.url,
            )
            self.langfuse_observer.finalize_run(
                trace_handle,
                status="failed",
                error_code=error_code,
                usage=cumulative_usage_payload,
                total_ms=elapsed_ms(run_started_at),
                metadata={
                    "llm_request_count": llm_request_count,
                    "request_kind": request_kind,
                    "agent_id": resolved_agent.agent_id,
                    "channel_id": channel_id,
                },
            )

        def try_failover(*, stage: str, error_code: str) -> bool:
            nonlocal resolved_llm
            nonlocal active_profile_name
            nonlocal active_tokenizer_family
            nonlocal failover_trigger
            nonlocal failover_stage
            nonlocal current_request
            nonlocal first_request
            if self.profile_runtime_resolver is None:
                return False
            if not should_failover(error_code, stage):
                return False
            while True:
                fallback_name = next_fallback_profile(
                    active_profile_name,
                    failover_candidates,
                    attempted_profiles,
                )
                if fallback_name is None:
                    return False
                try:
                    fallback_llm, fallback_profile = self.profile_runtime_resolver(fallback_name)
                except ValueError as exc:
                    attempted_profiles.append(fallback_name)
                    self.history.record_failover_skipped_profile(
                        run.run_id,
                        profile_name=fallback_name,
                        reason=str(exc),
                    )
                    continue
                resolved_llm = fallback_llm
                active_profile_name = fallback_name
                active_tokenizer_family = getattr(fallback_profile, "tokenizer_family", None)
                register_failover_candidates(fallback_profile)
                attempted_profiles.append(fallback_name)
                attempted_providers.append(
                    getattr(fallback_llm, "provider_name", "unknown")
                )
                failover_trigger = error_code
                failover_stage = stage
                first_request = self._request_for_client(
                    first_request,
                    fallback_llm,
                    tokenizer_family=active_tokenizer_family,
                    timeout_seconds_override=timeout_seconds_override,
                    stop_event=stop_event,
                    deadline_monotonic=deadline_monotonic,
                )
                current_request = self._request_for_client(
                    current_request,
                    fallback_llm,
                    tokenizer_family=active_tokenizer_family,
                    timeout_seconds_override=timeout_seconds_override,
                    stop_event=stop_event,
                    deadline_monotonic=deadline_monotonic,
                )
                self.history.set_failover_state(
                    run.run_id,
                    provider_ref=attempted_providers[0] if attempted_providers else None,
                    attempted_profiles=attempted_profiles,
                    attempted_providers=attempted_providers,
                        failover_trigger=failover_trigger,
                        failover_stage=failover_stage,
                        final_provider_ref=getattr(fallback_llm, "provider_name", None),
                    )
                return True
        first_request = self._build_request_from_context(
            **request_base,
            ctx=runtime_context,
            include_available_tools=True,
            bootstrap_manifest_id=bootstrap_manifest_id,
            prompt_mode=resolved_agent.prompt_mode,
            timeout_seconds_override=timeout_seconds_override,
            cooperative_stop_event=stop_event,
            cooperative_deadline_monotonic=deadline_monotonic,
        )
        tool_history: list[ToolExchange] = []
        current_request = first_request
        latest_actual_usage = None
        finalization_retry_used = False
        contract_repair_used = False

        def rebind_same_turn_session_context(target_session_id: str) -> None:
            nonlocal active_context_session_id
            nonlocal active_session_messages
            nonlocal active_recent_tool_outcome_summaries
            nonlocal resolved_compacted_context
            nonlocal runtime_context
            nonlocal pre_compact_runtime_context
            nonlocal request_base
            nonlocal first_request
            nonlocal current_request
            nonlocal latest_actual_usage
            normalized_target = str(target_session_id or "").strip()
            if not normalized_target or normalized_target == active_context_session_id:
                return
            active_context_session_id = normalized_target
            if session_store is not None:
                target_session = session_store.get(active_context_session_id)
                active_session_messages = list(target_session.history)
                active_recent_tool_outcome_summaries = list(
                    session_store.list_recent_tool_outcome_summaries(
                        active_context_session_id,
                        limit=3,
                    )
                )
                resolved_compacted_context = target_session.latest_compacted_context
                latest_actual_usage = target_session.latest_actual_usage
                runtime_context = assemble_runtime_context(
                    session_id=active_context_session_id,
                    current_message=message,
                    system_prompt=system_prompt,
                    session_messages=active_session_messages,
                    tool_snapshot=tool_snapshot,
                    compacted_context=resolved_compacted_context,
                    skill_snapshot=skill_snapshot,
                    activated_skill_ids=activated_skill_ids,
                    skill_heads_text=skill_heads_text,
                    capability_catalog_text=capability_catalog_text,
                    always_on_skill_text=always_on_skill_text,
                    channel_protocol_instruction_text=channel_protocol_instruction_text,
                    memory_text=memory_text,
                    activated_skill_bodies=activated_skill_bodies,
                    recent_tool_outcome_summaries=active_recent_tool_outcome_summaries,
                    replay_user_turns=session_replay_user_turns,
                )
                pre_compact_runtime_context = assemble_runtime_context(
                    session_id=active_context_session_id,
                    current_message=message,
                    system_prompt=system_prompt,
                    session_messages=active_session_messages,
                    tool_snapshot=tool_snapshot,
                    compacted_context=None,
                    skill_snapshot=skill_snapshot,
                    activated_skill_ids=activated_skill_ids,
                    skill_heads_text=skill_heads_text,
                    capability_catalog_text=capability_catalog_text,
                    always_on_skill_text=always_on_skill_text,
                    channel_protocol_instruction_text=channel_protocol_instruction_text,
                    memory_text=memory_text,
                    activated_skill_bodies=activated_skill_bodies,
                    recent_tool_outcome_summaries=active_recent_tool_outcome_summaries,
                    replay_user_turns=session_replay_user_turns,
                )
            else:
                first_request = first_request.model_copy(
                    update={"session_id": active_context_session_id}
                )
                current_request = current_request.model_copy(
                    update={"session_id": active_context_session_id}
                )
            request_base["session_id"] = active_context_session_id
            first_request = self._build_request_from_context(
                **request_base,
                ctx=runtime_context,
                include_available_tools=True,
                bootstrap_manifest_id=bootstrap_manifest_id,
                prompt_mode=resolved_agent.prompt_mode,
                timeout_seconds_override=timeout_seconds_override,
                cooperative_stop_event=stop_event,
                cooperative_deadline_monotonic=deadline_monotonic,
            )
            current_request = first_request

        for _ in range(self.max_tool_rounds + 1):
            generation_name = "llm.first" if not tool_history else "llm.followup"
            generation_stage = "llm_first" if not tool_history else "llm_second"
            generation_observed = False
            try:
                self._raise_if_interrupted(stop_event, deadline_monotonic)
                self.request_count += 1
                llm_request_count += 1
                llm_started_at = time.perf_counter()
                current_request = current_request.model_copy(
                    update={
                        "timeout_seconds_override": timeout_seconds_override
                        if timeout_seconds_override is not None
                        else self._remaining_timeout_seconds(deadline_monotonic),
                        "cooperative_stop_event": stop_event,
                        "cooperative_deadline_monotonic": deadline_monotonic,
                    }
                )
                reply = resolved_llm.complete(current_request)
                self.langfuse_observer.observe_generation(
                    trace_handle,
                    name=generation_name,
                    model=getattr(resolved_llm, "model_name", None),
                    provider=getattr(resolved_llm, "provider_name", None),
                    input_payload=self._generation_input_payload(current_request),
                    output_payload=self._generation_output_payload(reply),
                    usage=self._usage_payload(reply.usage),
                    status="success",
                    latency_ms=elapsed_ms(llm_started_at),
                    metadata={
                        "stage": generation_stage,
                        "request_kind": current_request.request_kind,
                        "model_profile": active_profile_name,
                    },
                )
                generation_observed = True
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
                    elapsed_ms=elapsed_ms(llm_started_at),
                )
                if current_request.request_kind == "finalization_retry" and reply.tool_name:
                    finalization_evidence_ledger = _build_current_turn_evidence_ledger(
                        user_message=message,
                        tool_history=tool_history,
                        model_request_count=llm_request_count,
                    )
                    finalization_details = assess_finalization_text_with_details(
                        tool_history,
                        "",
                        user_message=message,
                        model_request_count=llm_request_count,
                        finalization_evidence_ledger=finalization_evidence_ledger,
                    )
                    recovered_text = recover_successful_tool_followup_text_with_meta(
                        tool_history,
                        model_request_count=llm_request_count,
                        finalization_evidence_ledger=finalization_evidence_ledger,
                    )
                    if recovered_text:
                        _record_finalization_diagnostics(
                            self.history,
                            run_id=run.run_id,
                            request_kind=current_request.request_kind,
                            details=finalization_details,
                            retry_triggered=True,
                            recovered_from_fragments=True,
                        )
                        finalize_success(final_text=recovered_text)
                        return finish_run_success(history=self.history, self_improve_recorder=self.self_improve_recorder, append_post_turn_summary_callback=self._append_post_turn_summary, post_commit_callback=self.self_improve_post_commit_callback,
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
                            channel_id=channel_id,
                        )
                    _record_finalization_diagnostics(
                        self.history,
                        run_id=run.run_id,
                        request_kind=current_request.request_kind,
                        details=finalization_details,
                        retry_triggered=True,
                    )
                    finalize_error(error_code="EMPTY_FINAL_RESPONSE")
                    return finish_run_error(history=self.history,
                        events=events,
                        session_id=session_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        error_code="EMPTY_FINAL_RESPONSE",
                        error_text="暂时没有生成可见回复，请重试。",
                        agent_id=resolved_agent.agent_id,
                        post_commit_callback=self.self_improve_post_commit_callback,
                    )
                if _is_duplicate_spawn_subagent_followup(
                    current_request,
                    reply,
                    tool_history,
                ):
                    finalization_evidence_ledger = _build_current_turn_evidence_ledger(
                        user_message=message,
                        tool_history=tool_history,
                        model_request_count=llm_request_count,
                    )
                    recovered_text = recover_successful_tool_followup_text_with_meta(
                        tool_history,
                        model_request_count=llm_request_count,
                        finalization_evidence_ledger=finalization_evidence_ledger,
                    )
                    if recovered_text:
                        finalization_details = assess_finalization_text_with_details(
                            tool_history,
                            recovered_text,
                            user_message=message,
                            model_request_count=llm_request_count,
                            finalization_evidence_ledger=finalization_evidence_ledger,
                        )
                        _record_finalization_diagnostics(
                            self.history,
                            run_id=run.run_id,
                            request_kind=current_request.request_kind,
                            details=finalization_details,
                            retry_triggered=finalization_retry_used,
                            recovered_from_fragments=True,
                        )
                        finalize_success(final_text=recovered_text)
                        return finish_run_success(history=self.history, self_improve_recorder=self.self_improve_recorder, append_post_turn_summary_callback=self._append_post_turn_summary, post_commit_callback=self.self_improve_post_commit_callback,
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
                            channel_id=channel_id,
                        )
                try:
                    self._raise_if_interrupted(stop_event, deadline_monotonic)
                    tool_started_at = time.perf_counter()
                    tool_result = resolve_tool_call(
                        reply,
                        self.tools,
                        tool_snapshot,
                        tool_context={
                            "run_id": run.run_id,
                            "session_id": active_context_session_id,
                            "trace_id": trace_id,
                            "message": message,
                            "channel_id": channel_id,
                            "conversation_id": conversation_id,
                            "user_id": user_id,
                            "source_transport": source_transport,
                            "agent_id": resolved_agent.agent_id,
                            "app_id": resolved_agent.app_id,
                            "allowed_tools": list(resolved_agent.allowed_tools),
                            "model_profile": active_profile_name,
                            "llm_client": resolved_llm,
                            "session_replay_user_turns": session_replay_user_turns,
                            "current_request": current_request,
                            "latest_actual_usage": latest_actual_usage,
                            "compact_settings": resolved_compact_settings,
                            "compacted_context": resolved_compacted_context,
                            "stop_event": stop_event,
                            "deadline_monotonic": deadline_monotonic,
                            "timeout_seconds_override": timeout_seconds_override
                            if timeout_seconds_override is not None
                            else self._remaining_timeout_seconds(deadline_monotonic),
                        },
                    )
                    if tool_result is not None:
                        tool_metadata = tool_snapshot.tool_metadata.get(
                            reply.tool_name or "", {}
                        )
                        self.langfuse_observer.observe_tool_call(
                            trace_handle,
                            name="tool.call",
                            tool_name=reply.tool_name or "",
                            tool_payload=reply.tool_payload,
                            tool_result=tool_result,
                            status="success",
                            latency_ms=elapsed_ms(tool_started_at),
                            metadata={
                                "stage": "tool",
                                "source_kind": tool_metadata.get("source_kind"),
                                "server_id": tool_metadata.get("server_id"),
                            },
                        )
                        self.history.set_stage_timing(
                            run.run_id,
                            stage="tool",
                            elapsed_ms=elapsed_ms(tool_started_at),
                        )
                except ToolCallRejected as exc:
                    tool_metadata = tool_snapshot.tool_metadata.get(
                        reply.tool_name or "", {}
                    )
                    self.langfuse_observer.observe_tool_call(
                        trace_handle,
                        name="tool.call",
                        tool_name=reply.tool_name or "",
                        tool_payload=reply.tool_payload,
                        tool_result={},
                        status="error",
                        latency_ms=elapsed_ms(tool_started_at),
                        metadata={
                            "stage": "tool",
                            "source_kind": tool_metadata.get("source_kind"),
                            "server_id": tool_metadata.get("server_id"),
                        },
                        error_code=exc.error_code,
                    )
                    self.history.record_tool_call(
                        run.run_id,
                        tool_name=reply.tool_name or "",
                        tool_payload=reply.tool_payload,
                        tool_result={
                            "ok": False,
                            "is_error": True,
                            "error_code": exc.error_code,
                            "error_text": tool_rejection_text(exc.error_code),
                        },
                    )
                    if tool_history:
                        recovered_text = recover_tool_result_text(tool_history)
                        if recovered_text:
                            finalize_success(final_text=recovered_text)
                            return finish_run_success(history=self.history, self_improve_recorder=self.self_improve_recorder, append_post_turn_summary_callback=self._append_post_turn_summary, post_commit_callback=self.self_improve_post_commit_callback,
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
                                channel_id=channel_id,
                            )
                    finalize_error(error_code=exc.error_code)
                    return finish_run_error(history=self.history, 
                        events=events,
                        session_id=session_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        error_code=exc.error_code,
                        error_text=tool_rejection_text(exc.error_code),
                        agent_id=resolved_agent.agent_id,
                        post_commit_callback=self.self_improve_post_commit_callback,
                    )
                except ToolExecutionFailed as exc:
                    tool_metadata = tool_snapshot.tool_metadata.get(
                        reply.tool_name or "", {}
                    )
                    self.langfuse_observer.observe_tool_call(
                        trace_handle,
                        name="tool.call",
                        tool_name=reply.tool_name or "",
                        tool_payload=reply.tool_payload,
                        tool_result={},
                        status="error",
                        latency_ms=elapsed_ms(tool_started_at),
                        metadata={
                            "stage": "tool",
                            "source_kind": tool_metadata.get("source_kind"),
                            "server_id": tool_metadata.get("server_id"),
                        },
                        error_code=exc.error_code,
                    )
                    record_failure(self.self_improve_recorder, 
                        agent_id=resolved_agent.agent_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        channel_id=channel_id,
                        error_code=exc.error_code,
                        error_stage="tool",
                        message=message,
                        summary=str(exc),
                    )
                    self.history.record_tool_call(
                        run.run_id,
                        tool_name=reply.tool_name or "",
                        tool_payload=reply.tool_payload,
                        tool_result={
                            "ok": False,
                            "is_error": True,
                            "error_code": exc.error_code,
                            "error_text": str(exc),
                        },
                    )
                    self.history.set_stage_timing(
                        run.run_id,
                        stage="tool",
                        elapsed_ms=elapsed_ms(tool_started_at),
                    )
                    finalize_error(error_code=exc.error_code)
                    return finish_run_error(history=self.history, 
                        events=events,
                        session_id=session_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        error_code=exc.error_code,
                        error_text="工具执行失败，请重试。",
                        agent_id=resolved_agent.agent_id,
                        post_commit_callback=self.self_improve_post_commit_callback,
                    )
            except Exception as exc:
                if not generation_observed:
                    error_code = (
                        normalize_provider_error(exc).error_code
                        if is_provider_failure(exc)
                        else "RUNTIME_LOOP_FAILED"
                    )
                    self.langfuse_observer.observe_generation(
                        trace_handle,
                        name=generation_name,
                        model=getattr(resolved_llm, "model_name", None),
                        provider=getattr(resolved_llm, "provider_name", None),
                        input_payload=self._generation_input_payload(current_request),
                        output_payload={},
                        usage=None,
                        status="error",
                        latency_ms=elapsed_ms(llm_started_at),
                        metadata={
                            "stage": generation_stage,
                            "request_kind": request_kind,
                            "model_profile": active_profile_name,
                        },
                        error_code=error_code,
                    )
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
                    elapsed_ms=elapsed_ms(llm_started_at),
                )
                if is_provider_failure(exc):
                    normalized = normalize_provider_error(exc)
                    if (
                        resolved_compacted_context is None
                        and is_reactive_compaction_error(exc)
                    ):
                        decision = CompactionDecision.REACTIVE
                        resolved_compacted_context = run_compaction(
                            llm=compact_llm_client or resolved_llm,
                            session_id=active_context_session_id,
                            current_message=message,
                            session_messages=active_session_messages,
                            preserved_tail_user_turns=session_replay_user_turns,
                            trigger_kind="context_pressure_reactive",
                        )
                        if resolved_compacted_context is not None:
                            if session_store is not None:
                                session_store.set_compacted_context(
                                    active_context_session_id,
                                    resolved_compacted_context,
                                )
                            elif on_compacted is not None:
                                on_compacted(resolved_compacted_context)
                            runtime_context = assemble_runtime_context(
                                session_id=active_context_session_id,
                                current_message=message,
                                system_prompt=system_prompt,
                                session_messages=active_session_messages,
                                compacted_context=resolved_compacted_context,
                                tool_snapshot=tool_snapshot,
                                skill_snapshot=skill_snapshot,
                                activated_skill_ids=activated_skill_ids,
                                skill_heads_text=skill_heads_text,
                                capability_catalog_text=capability_catalog_text,
                                always_on_skill_text=always_on_skill_text,
                                channel_protocol_instruction_text=channel_protocol_instruction_text,
                                memory_text=memory_text,
                                activated_skill_bodies=activated_skill_bodies,
                                recent_tool_outcome_summaries=active_recent_tool_outcome_summaries,
                                replay_user_turns=session_replay_user_turns,
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
                                    "timeout_seconds_override": timeout_seconds_override
                                    if timeout_seconds_override is not None
                                    else self._remaining_timeout_seconds(deadline_monotonic),
                                    "cooperative_stop_event": stop_event,
                                    "cooperative_deadline_monotonic": deadline_monotonic,
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
                    if try_failover(
                        stage="llm_first" if not tool_history else "llm_second",
                        error_code=normalized.error_code,
                    ):
                        continue
                    if tool_history:
                        recovered_text = recover_tool_result_text(tool_history)
                        if recovered_text:
                            finalize_success(final_text=recovered_text)
                            return finish_run_success(history=self.history, self_improve_recorder=self.self_improve_recorder, append_post_turn_summary_callback=self._append_post_turn_summary, post_commit_callback=self.self_improve_post_commit_callback,
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
                                channel_id=channel_id,
                            )
                    record_failure(self.self_improve_recorder, 
                        agent_id=resolved_agent.agent_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        channel_id=channel_id,
                        error_code=normalized.error_code,
                        error_stage="llm",
                        message=message,
                        summary=str(exc),
                        provider_name=getattr(resolved_llm, "provider_name", None),
                    )
                    finalize_error(error_code=normalized.error_code)
                    return finish_run_error(history=self.history, 
                        events=events,
                        session_id=session_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        error_code=normalized.error_code,
                        error_text=provider_failure_text(normalized.error_code),
                        agent_id=resolved_agent.agent_id,
                        post_commit_callback=self.self_improve_post_commit_callback,
                    )
                record_failure(self.self_improve_recorder, 
                    agent_id=resolved_agent.agent_id,
                    run_id=run.run_id,
                    trace_id=trace_id,
                    session_id=session_id,
                    channel_id=channel_id,
                    error_code="RUNTIME_LOOP_FAILED",
                    error_stage="runtime",
                    message=message,
                    summary=str(exc),
                )
                finalize_error(error_code="RUNTIME_LOOP_FAILED")
                return finish_run_error(history=self.history, 
                    events=events,
                    session_id=session_id,
                    run_id=run.run_id,
                    trace_id=trace_id,
                    run_started_at=run_started_at,
                    llm_request_count=llm_request_count,
                    error_code="RUNTIME_LOOP_FAILED",
                    error_text="暂时没有生成可见回复，请重试。",
                    agent_id=resolved_agent.agent_id,
                    post_commit_callback=self.self_improve_post_commit_callback,
                )
            if tool_result is None:
                final_text = (reply.final_text or "").strip()
                invalid_first_turn_finalization_contract = (
                    violates_session_switch_contract(tool_history, final_text)
                    or violates_current_session_identity_contract(tool_history, final_text)
                    or violates_spawn_subagent_acceptance_contract(tool_history, final_text)
                )
                if invalid_first_turn_finalization_contract and not tool_history:
                    if not contract_repair_used:
                        self.history.set_finalization_state(
                            run.run_id,
                            assessment="retryable_degraded",
                            request_kind=current_request.request_kind,
                            required_evidence_count=0,
                            missing_evidence_items=[],
                            retry_triggered=True,
                            invalid_final_text=final_text,
                        )
                        contract_repair_used = True
                        self.history.set_contract_repair_state(
                            run.run_id,
                            triggered=True,
                            reason="invalid_first_turn_finalization_contract",
                            attempt_count=1,
                            outcome="retrying",
                            selected_tool=None,
                            provider_ref=getattr(resolved_llm, "provider_name", None),
                        )
                        current_request = _build_contract_repair_request(
                            first_request,
                            invalid_final_text=final_text,
                        ).model_copy(
                            update={
                                "timeout_seconds_override": timeout_seconds_override
                                if timeout_seconds_override is not None
                                else self._remaining_timeout_seconds(deadline_monotonic),
                                "cooperative_stop_event": stop_event,
                                "cooperative_deadline_monotonic": deadline_monotonic,
                            }
                        )
                        continue
                    self.history.set_finalization_state(
                        run.run_id,
                        assessment="unrecoverable",
                        request_kind=current_request.request_kind,
                        required_evidence_count=0,
                        missing_evidence_items=[],
                        retry_triggered=True,
                        invalid_final_text=final_text,
                    )
                    self.history.set_contract_repair_state(
                        run.run_id,
                        triggered=True,
                        reason="invalid_first_turn_finalization_contract",
                        attempt_count=1,
                        outcome="invalid_final_response",
                        selected_tool=None,
                        provider_ref=getattr(resolved_llm, "provider_name", None),
                    )
                if invalid_first_turn_finalization_contract:
                    if not tool_history:
                        self.history.set_finalization_state(
                            run.run_id,
                            assessment="unrecoverable",
                            request_kind=current_request.request_kind,
                            required_evidence_count=0,
                            missing_evidence_items=[],
                            retry_triggered=bool(
                                contract_repair_used
                                or current_request.request_kind == "contract_repair"
                            ),
                            invalid_final_text=final_text,
                        )
                        finalize_error(error_code="INVALID_FINAL_RESPONSE")
                        return finish_run_error(history=self.history,
                            events=events,
                            session_id=session_id,
                            run_id=run.run_id,
                            trace_id=trace_id,
                            run_started_at=run_started_at,
                            llm_request_count=llm_request_count,
                            error_code="INVALID_FINAL_RESPONSE",
                            error_text="暂时没有生成可见回复，请重试。",
                            agent_id=resolved_agent.agent_id,
                            post_commit_callback=self.self_improve_post_commit_callback,
                        )
                if tool_history:
                    finalization_evidence_ledger = _build_current_turn_evidence_ledger(
                        user_message=message,
                        tool_history=tool_history,
                        model_request_count=llm_request_count,
                    )
                    finalization_details = assess_finalization_text_with_details(
                        tool_history,
                        final_text,
                        user_message=message,
                        model_request_count=llm_request_count,
                        finalization_evidence_ledger=finalization_evidence_ledger,
                    )
                    if (
                        finalization_details.assessment == "retryable_degraded"
                        and not finalization_retry_used
                    ):
                        _record_finalization_diagnostics(
                            self.history,
                            run_id=run.run_id,
                            request_kind=current_request.request_kind,
                            details=finalization_details,
                            retry_triggered=True,
                            invalid_final_text=final_text,
                        )
                        finalization_retry_used = True
                        current_request = build_finalization_retry_request(
                            first_request,
                            tool_history=tool_history,
                            finalization_evidence_ledger=finalization_evidence_ledger,
                        ).model_copy(
                            update={
                                "timeout_seconds_override": timeout_seconds_override
                                if timeout_seconds_override is not None
                                else self._remaining_timeout_seconds(deadline_monotonic)
                            }
                        )
                        continue
                    if finalization_details.assessment == "retryable_degraded":
                        final_text = recover_successful_tool_followup_text_with_meta(
                            tool_history,
                            model_request_count=llm_request_count,
                            finalization_evidence_ledger=finalization_evidence_ledger,
                        )
                        _record_finalization_diagnostics(
                            self.history,
                            run_id=run.run_id,
                            request_kind=current_request.request_kind,
                            details=finalization_details,
                            retry_triggered=True,
                            recovered_from_fragments=bool(final_text),
                            invalid_final_text=(reply.final_text or "").strip(),
                        )
                    elif finalization_details.assessment == "unrecoverable":
                        _record_finalization_diagnostics(
                            self.history,
                            run_id=run.run_id,
                            request_kind=current_request.request_kind,
                            details=finalization_details,
                            retry_triggered=finalization_retry_used,
                            invalid_final_text=final_text,
                        )
                        final_text = ""
                    else:
                        _record_finalization_diagnostics(
                            self.history,
                            run_id=run.run_id,
                            request_kind=current_request.request_kind,
                            details=finalization_details,
                            retry_triggered=bool(
                                finalization_retry_used
                                or current_request.request_kind == "finalization_retry"
                            ),
                        )
                if not final_text:
                    if current_request.request_kind == "contract_repair":
                        self.history.set_contract_repair_state(
                            run.run_id,
                            triggered=True,
                            reason="invalid_first_turn_finalization_contract",
                            attempt_count=1,
                            outcome="empty_final_response",
                            selected_tool=None,
                            provider_ref=getattr(resolved_llm, "provider_name", None),
                        )
                    if not tool_history:
                        self.history.set_finalization_state(
                            run.run_id,
                            assessment="unrecoverable",
                            request_kind=current_request.request_kind,
                            required_evidence_count=0,
                            missing_evidence_items=[],
                            retry_triggered=bool(
                                contract_repair_used
                                or current_request.request_kind == "contract_repair"
                            ),
                            invalid_final_text=(reply.final_text or "").strip() or final_text,
                        )
                    if not tool_history and try_failover(
                        stage="llm_first" if not tool_history else "llm_second",
                        error_code="EMPTY_FINAL_RESPONSE",
                    ):
                        continue
                    finalize_error(error_code="EMPTY_FINAL_RESPONSE")
                    return finish_run_error(history=self.history, 
                        events=events,
                        session_id=session_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        error_code="EMPTY_FINAL_RESPONSE",
                        error_text="暂时没有生成可见回复，请重试。",
                        agent_id=resolved_agent.agent_id,
                        post_commit_callback=self.self_improve_post_commit_callback,
                    )
                if current_request.request_kind == "contract_repair":
                    self.history.set_contract_repair_state(
                        run.run_id,
                        triggered=True,
                        reason="invalid_first_turn_finalization_contract",
                        attempt_count=1,
                        outcome="final_text",
                        selected_tool=None,
                        provider_ref=getattr(resolved_llm, "provider_name", None),
                    )
                if not tool_history:
                    self.history.set_finalization_state(
                        run.run_id,
                        assessment="accepted",
                        request_kind=current_request.request_kind,
                        required_evidence_count=0,
                        missing_evidence_items=[],
                        retry_triggered=bool(
                            contract_repair_used
                            or current_request.request_kind == "contract_repair"
                        ),
                    )
                finalize_success(final_text=final_text)
                return finish_run_success(history=self.history, self_improve_recorder=self.self_improve_recorder, append_post_turn_summary_callback=self._append_post_turn_summary, post_commit_callback=self.self_improve_post_commit_callback,
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
                    channel_id=channel_id,
                )
            append_tool_exchange(
                tool_history,
                tool_name=reply.tool_name or "",
                tool_payload=reply.tool_payload,
                tool_result=tool_result,
            )
            self.history.record_tool_call(
                run.run_id,
                tool_name=reply.tool_name or "",
                tool_payload=reply.tool_payload,
                tool_result=tool_result,
            )
            if current_request.request_kind == "contract_repair":
                self.history.set_contract_repair_state(
                    run.run_id,
                    triggered=True,
                    reason="invalid_first_turn_finalization_contract",
                    attempt_count=1,
                    outcome="tool_call",
                    selected_tool=reply.tool_name or None,
                    provider_ref=getattr(resolved_llm, "provider_name", None),
                )
            run_record = self.history.get(run.run_id)
            tool_result, followup_render = normalize_tool_result_for_followup(
                tool_name=reply.tool_name or "",
                tool_payload=reply.tool_payload,
                tool_result=tool_result,
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
                message=message,
                tool_history_count=len(tool_history),
                tool_history=tool_history,
            )
            if isinstance(tool_result, dict):
                tool_history[-1].tool_result = tool_result
                tool_history[-1].recovery_fragment = followup_render.recovery_fragment
                if followup_render.terminal_text:
                    finalization_evidence_ledger = _build_current_turn_evidence_ledger(
                        user_message=message,
                        tool_history=tool_history,
                        model_request_count=llm_request_count,
                    )
                    finalization_details = assess_finalization_text_with_details(
                        tool_history,
                        followup_render.terminal_text,
                        user_message=message,
                        model_request_count=llm_request_count,
                        finalization_evidence_ledger=finalization_evidence_ledger,
                    )
                    _record_finalization_diagnostics(
                        self.history,
                        run_id=run.run_id,
                        request_kind=current_request.request_kind,
                        details=finalization_details,
                        retry_triggered=finalization_retry_used,
                    )
                    finalize_success(final_text=followup_render.terminal_text)
                    return finish_run_success(history=self.history, self_improve_recorder=self.self_improve_recorder, append_post_turn_summary_callback=self._append_post_turn_summary, post_commit_callback=self.self_improve_post_commit_callback,
                        events=events,
                        session_id=session_id,
                    run_id=run.run_id,
                    trace_id=trace_id,
                    run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        message=message,
                        agent_id=resolved_agent.agent_id,
                    final_text=followup_render.terminal_text,
                    tool_history=tool_history,
                    tool_snapshot=tool_snapshot,
                    channel_id=channel_id,
                )
                if str(reply.tool_name or "").strip() == "session":
                    transition = tool_result.get("transition")
                    if isinstance(transition, dict) and transition.get("binding_changed") is True:
                        target_session_id = str(
                            transition.get("target_session_id") or ""
                        ).strip()
                        if target_session_id:
                            rebind_same_turn_session_context(target_session_id)
            provisional_request = build_tool_followup_request(
                first_request,
                tool_history=tool_history,
                tool_result=tool_result,
                requested_tool_name=reply.tool_name,
                requested_tool_payload=reply.tool_payload,
                finalization_evidence_ledger=_build_current_turn_evidence_ledger(
                    user_message=message,
                    tool_history=tool_history,
                    model_request_count=llm_request_count,
                ),
            )
            followup_usage = estimate_request_usage(provisional_request)
            self.history.update_peak_preflight_usage(
                run.run_id,
                input_tokens_estimate=followup_usage.input_tokens_estimate,
                stage="tool_followup",
            )
            current_request = build_tool_followup_request(
                first_request,
                tool_history=tool_history,
                tool_result=tool_result,
                requested_tool_name=reply.tool_name,
                requested_tool_payload=reply.tool_payload,
                finalization_evidence_ledger=_build_current_turn_evidence_ledger(
                    user_message=message,
                    tool_history=tool_history,
                    model_request_count=llm_request_count,
                ),
            ).model_copy(
                update={
                    "timeout_seconds_override": timeout_seconds_override
                    if timeout_seconds_override is not None
                    else self._remaining_timeout_seconds(deadline_monotonic)
                }
            )
        record_failure(self.self_improve_recorder, 
            agent_id=resolved_agent.agent_id,
            run_id=run.run_id,
            trace_id=trace_id,
            session_id=session_id,
            channel_id=channel_id,
            error_code="TOOL_LOOP_LIMIT_EXCEEDED",
            error_stage="tool_loop",
            message=message,
            summary="tool loop limit exceeded",
        )
        finalize_error(error_code="TOOL_LOOP_LIMIT_EXCEEDED")
        return finish_run_error(history=self.history, 
            events=events,
            session_id=session_id,
            run_id=run.run_id,
            trace_id=trace_id,
            run_started_at=run_started_at,
            llm_request_count=llm_request_count,
            error_code="TOOL_LOOP_LIMIT_EXCEEDED",
            error_text="tool_loop_limit_exceeded",
            agent_id=resolved_agent.agent_id,
            post_commit_callback=self.self_improve_post_commit_callback,
        )
