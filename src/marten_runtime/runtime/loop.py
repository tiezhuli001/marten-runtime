import json
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo


from marten_runtime.agents.specs import AgentSpec
from marten_runtime.observability.langfuse import (
    LangfuseObserver,
    build_langfuse_observer,
)
from marten_runtime.runtime.context import assemble_runtime_context
from marten_runtime.runtime.bazi_output_contract import (
    BaziAnalysisDraft,
    bind_bazi_verification_facts,
    bazi_repair_source_text,
    bazi_timing_contract_violations,
    bazi_verification_group_violations,
    classify_bazi_contract_violations,
    deterministic_verification_event_violations,
    bazi_violation_sections,
    merge_bazi_repaired_sections,
    missing_bazi_sections,
    normalize_bazi_timing_contract_text,
    normalize_bazi_verification_candidate_reasons,
    parse_bazi_analysis_draft,
    parse_bazi_semantic_review,
    parse_bazi_verification_events_patch,
    prune_semantically_rejected_verification_events,
    render_bazi_analysis_draft,
)
from marten_runtime.runtime.llm_message_support import build_bazi_timing_fact_registry
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.finalization_contract_prompt import (
    FinalizationContractDraft,
    SessionSwitchClaimDraft,
)
from marten_runtime.runtime.history import CompactionDiagnostics, InMemoryRunHistory
from marten_runtime.runtime.observation_policy import (
    project_text,
    resolve_observation_policy,
)
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
    _apply_finalization_draft_to_evidence_ledger,
    _first_violated_finalization_contract,
    assess_finalization_text_with_details,
    is_generic_tool_failure_text,
    recover_successful_tool_followup_text_with_meta,
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
from marten_runtime.runtime.provider_retry import normalize_provider_error
from marten_runtime.runtime.provider_reliability import build_provider_call_diagnostics
from marten_runtime.runtime.usage_models import ProviderCallAttempt
from marten_runtime.runtime.finalization_flow import (
    build_contract_repair_request,
    build_current_turn_evidence_ledger,
    deprioritize_tool_evidence_requirements,
    failed_tool_details,
    final_text_masks_failed_tool_result,
    is_duplicate_spawn_subagent_followup,
    record_finalization_diagnostics,
    require_latest_failed_tool_evidence,
)
from marten_runtime.runtime.provider_flow import (
    build_provider_failover_state,
    set_history_failover_state,
    try_provider_failover,
)
from marten_runtime.runtime.request_timeout import (
    resolve_request_responses_api,
    resolve_request_timeout_seconds,
)
from marten_runtime.runtime.request_flow import (
    build_request_from_context,
    generation_input_payload,
    generation_output_payload,
    remaining_timeout_seconds,
    request_for_client,
    usage_payload,
)
from marten_runtime.runtime.run_lifecycle import RunLifecycleFinalizer
from marten_runtime.runtime.session_rebind_flow import (
    rebind_same_turn_session_context as rebind_same_turn_session_context_state,
)
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
    build_bazi_analysis_draft_repair_request,
    build_bazi_final_generation_request,
    build_bazi_output_repair_request,
    build_bazi_output_semantic_review_request,
    build_bazi_verification_event_repair_request,
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


logger = logging.getLogger(__name__)


def _host_orchestrated_bazi_tool_reply(
    request: LLMRequest,
    llm: LLMClient,
) -> LLMReply | None:
    if request.agent_id != "bazi" or not bool(
        getattr(llm, "host_orchestrated_bazi_pipeline", False)
    ):
        return None
    expected_tools = {
        "bazi_dayun_repair": "bazi",
        "bazi_knowledge_search": "knowledge",
        "bazi_case_search": "bazi_case",
    }
    expected_tool = expected_tools.get(request.request_kind)
    if expected_tool is None or request.requested_tool_name != expected_tool:
        return None
    payload = dict(request.requested_tool_payload or {})
    if not str(payload.get("action") or "").strip():
        return None
    return LLMReply(tool_name=expected_tool, tool_payload=payload)


DEFAULT_ALLOWED_TOOLS = [
    "automation",
    "mcp",
    "runtime",
    "self_improve",
    "session",
    "skill",
    "time",
]

# Compatibility exports for tests and older call sites.
_build_contract_repair_request = build_contract_repair_request




def _infer_required_first_turn_contract_from_text(
    final_text: str,
    *,
    user_message: str,
    actual_draft: FinalizationContractDraft | None = None,
) -> FinalizationContractDraft | None:
    normalized_text = " ".join(str(final_text or "").split())
    normalized_message = " ".join(str(user_message or "").split())
    if not normalized_text or not normalized_message:
        return actual_draft
    resume_cues = ("恢复", "切换", "继续")
    session_cues = ("旧会话", "已有会话", "历史会话", "sess_")
    previous_switch_confirmed = (
        actual_draft is not None
        and actual_draft.session_switch is not None
        and actual_draft.session_switch.kind == "resume_switch"
    )
    if (
        any(cue in normalized_message for cue in resume_cues)
        and any(cue in normalized_message for cue in session_cues)
        and any(cue in normalized_text for cue in ("已在", "已切换", "已恢复"))
        and any(cue in normalized_text for cue in session_cues)
        and not previous_switch_confirmed
    ):
        inferred = (actual_draft or FinalizationContractDraft()).model_copy(deep=True)
        inferred.session_switch = inferred.session_switch or SessionSwitchClaimDraft(
            kind="resume_switch"
        )
        return inferred
    return actual_draft


def _finalization_candidate_text(
    *, request_kind: str, normalized_final_text: str, raw_reply_text: str | None
) -> str:
    if request_kind == "bazi_output_repair":
        return normalized_final_text
    return str(raw_reply_text or "").strip()


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
    def _synthesized_provider_diagnostics(
        *,
        request: LLMRequest,
        llm: LLMClient,
        normalized_error,
        elapsed_ms: int,
    ):
        provider = getattr(llm, "provider", None)
        responses_api = resolve_request_responses_api(
            request,
            model_name=getattr(llm, "model_name", None),
            supports_responses_api=getattr(provider, "supports_responses_api", None),
            supports_chat_completions=getattr(provider, "supports_chat_completions", None),
        )
        return build_provider_call_diagnostics(
            request_kind=request.request_kind,
            timeout_seconds=resolve_request_timeout_seconds(
                request,
                model_name=getattr(llm, "model_name", None),
                responses_api=responses_api,
            ),
            max_attempts=1,
            completed=False,
            final_error_code=normalized_error.error_code,
            attempts=[
                ProviderCallAttempt(
                    attempt=1,
                    elapsed_ms=elapsed_ms,
                    ok=False,
                    error_code=normalized_error.error_code,
                    error_detail=getattr(normalized_error, "detail", str(normalized_error)),
                    retryable=bool(getattr(normalized_error, "retryable", False)),
                )
            ],
            provider_name=getattr(llm, "provider_name", None),
            model_name=getattr(llm, "model_name", None),
            profile_name=getattr(llm, "profile_name", None),
            error_detail=getattr(normalized_error, "detail", str(normalized_error)),
            retry_after_seconds=getattr(normalized_error, "retry_after_seconds", None),
        )

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
        repository_context_text: str | None = None,
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
        on_run_started: Callable[[str, datetime], None] | None = None,
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
            allowed_tools=list(DEFAULT_ALLOWED_TOOLS),
        )
        observation_policy = resolve_observation_policy(
            getattr(resolved_agent, "observation_policy", "standard")
        )
        observed_message = str(project_text(message, observation_policy) or "")
        resolved_llm = llm_client or self.llm
        provider_state = build_provider_failover_state(
            llm=resolved_llm,
            active_profile_name=(
                model_profile_name
                or getattr(resolved_llm, "profile_name", None)
                or "default"
            ),
            tokenizer_family=tokenizer_family,
            profile_runtime_resolver=self.profile_runtime_resolver,
        )
        resolved_compact_settings = compact_settings or CompactionSettings()
        tool_snapshot = self.tools.build_snapshot(resolved_agent.allowed_tools)
        def tool_observation_policy(tool_name: str) -> str:
            metadata = tool_snapshot.tool_metadata.get(tool_name, {})
            return resolve_observation_policy(
                observation_policy,
                str(metadata.get("observation_policy") or "standard"),
            )

        turn_tool_state: dict[str, object] = {}
        resolved_compacted_context = compacted_context
        active_context_session_id = session_id
        active_session_messages = list(session_messages or [])
        active_recent_tool_outcome_summaries = list(recent_tool_outcome_summaries or [])

        rough_request = LLMRequest(
            session_id=session_id,
            trace_id=trace_id,
            message=message,
            agent_id=resolved_agent.agent_id,
            model_name=getattr(resolved_llm, "model_name", None),
            tokenizer_family=provider_state.active_tokenizer_family,
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
            repository_context_text=repository_context_text,
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
            repository_context_text=repository_context_text,
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
            observation_policy=observation_policy,
        )
        if on_run_started is not None:
            on_run_started(run.run_id, run.started_at)
        trace_handle = self.langfuse_observer.start_run_trace(
            name="runtime.turn",
            trace_id=trace_id,
            input_text=message,
            metadata={
                "run_id": run.run_id,
                "session_id": session_id,
                "agent_id": resolved_agent.agent_id,
                "channel_id": channel_id,
                "request_kind": request_kind,
                "config_snapshot_id": config_snapshot_id,
                "bootstrap_manifest_id": bootstrap_manifest_id,
                "parent_run_id": parent_run_id,
            },
            tags=[request_kind],
            observation_policy=observation_policy,
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
            model_name=getattr(resolved_llm, "model_name", None),
            tokenizer_family=provider_state.active_tokenizer_family,
            channel_protocol_instruction_text=channel_protocol_instruction_text,
            tool_snapshot=tool_snapshot,
            request_kind=request_kind,
        )
        pre_compact_request_estimate = estimate_request_tokens(
            build_request_from_context(
                **request_base,
                ctx=pre_compact_runtime_context,
            )
        )
        first_request_estimate = estimate_request_tokens(
            build_request_from_context(
                **request_base,
                ctx=runtime_context,
            )
        )
        compaction_before_estimate = (
            estimated_tokens_before
            if resolved_compacted_context is not None
            else pre_compact_request_estimate
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
                estimated_input_tokens_before=compaction_before_estimate,
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
                message=observed_message,
                estimated_tokens_before=compaction_before_estimate,
                estimated_tokens_after=first_request_estimate,
                channel_id=channel_id,
            )
        first_request_usage = estimate_request_usage(
            build_request_from_context(
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
        set_history_failover_state(
            self.history,
            run_id=run.run_id,
            state=provider_state,
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

        lifecycle_finalizer = RunLifecycleFinalizer(
            history=self.history,
            langfuse_observer=self.langfuse_observer,
            trace_handle=trace_handle,
            run_id=run.run_id,
            run_started_at=run_started_at,
            provider_state=provider_state,
            request_kind=request_kind,
            agent_id=resolved_agent.agent_id,
            channel_id=channel_id,
            observation_policy=observation_policy,
        )

        def finalize_success(*, final_text: str) -> None:
            lifecycle_finalizer.finalize_success(
                final_text=final_text,
                final_provider_ref=getattr(resolved_llm, "provider_name", None),
                llm_request_count=llm_request_count,
            )

        def finalize_error(*, error_code: str) -> None:
            lifecycle_finalizer.finalize_error(
                error_code=error_code,
                final_provider_ref=getattr(resolved_llm, "provider_name", None),
                llm_request_count=llm_request_count,
            )

        def try_failover(*, stage: str, error_code: str) -> bool:
            nonlocal resolved_llm
            nonlocal first_request
            nonlocal current_request

            def adapt_request(
                request: LLMRequest,
                fallback_llm: LLMClient,
                fallback_tokenizer_family: str | None,
            ) -> LLMRequest:
                return request_for_client(
                    request,
                    fallback_llm,
                    tokenizer_family=fallback_tokenizer_family,
                    timeout_seconds_override=timeout_seconds_override,
                    stop_event=stop_event,
                    deadline_monotonic=deadline_monotonic,
                )

            result = try_provider_failover(
                state=provider_state,
                history=self.history,
                run_id=run.run_id,
                profile_runtime_resolver=self.profile_runtime_resolver,
                stage=stage,
                error_code=error_code,
                first_request=first_request,
                current_request=current_request,
                request_adapter=adapt_request,
            )
            if result is None:
                return False
            resolved_llm = result.llm
            first_request = result.first_request
            current_request = result.current_request
            return True

        first_request = build_request_from_context(
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
        bazi_chart_repair_used = False
        bazi_dayun_repair_used = False
        bazi_knowledge_repair_used = False
        bazi_case_repair_used = False
        bazi_analysis_repair_attempts = 0
        bazi_final_generation_used = False
        bazi_analysis_repair_source_text: str | None = None
        bazi_analysis_repair_sections: list[str] = []
        bazi_semantic_review_source_text: str | None = None
        bazi_pending_verification_violations: tuple[str, ...] = ()
        bazi_pending_rejected_event_labels: tuple[str, ...] = ()
        bazi_semantic_review_completed = False
        bazi_semantic_review_attempts = 0
        bazi_semantic_repair_attempts = 0
        bazi_analysis_draft: BaziAnalysisDraft | None = None
        bazi_fact_reference_violations: tuple[str, ...] = ()
        bazi_structured_generation_retry_used = False
        bazi_requires_complete_dayun = bool(
            getattr(resolved_llm, "host_orchestrated_bazi_pipeline", False)
        )

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
            rebound = rebind_same_turn_session_context_state(
                target_session_id=target_session_id,
                current_session_id=active_context_session_id,
                session_messages=active_session_messages,
                recent_tool_outcome_summaries=active_recent_tool_outcome_summaries,
                compacted_context=resolved_compacted_context,
                runtime_context=runtime_context,
                pre_compact_runtime_context=pre_compact_runtime_context,
                request_base=request_base,
                first_request=first_request,
                current_request=current_request,
                latest_actual_usage=latest_actual_usage,
                session_store=session_store,
                message=message,
                system_prompt=system_prompt,
                tool_snapshot=tool_snapshot,
                skill_snapshot=skill_snapshot,
                activated_skill_ids=activated_skill_ids,
                skill_heads_text=skill_heads_text,
                capability_catalog_text=capability_catalog_text,
                always_on_skill_text=always_on_skill_text,
                channel_protocol_instruction_text=channel_protocol_instruction_text,
                memory_text=memory_text,
                repository_context_text=repository_context_text,
                activated_skill_bodies=activated_skill_bodies,
                session_replay_user_turns=session_replay_user_turns,
                bootstrap_manifest_id=bootstrap_manifest_id,
                prompt_mode=resolved_agent.prompt_mode,
                timeout_seconds_override=timeout_seconds_override,
                stop_event=stop_event,
                deadline_monotonic=deadline_monotonic,
            )
            if rebound is None:
                return
            active_context_session_id = rebound.session_id
            active_session_messages = rebound.session_messages
            active_recent_tool_outcome_summaries = rebound.recent_tool_outcome_summaries
            resolved_compacted_context = rebound.compacted_context
            runtime_context = rebound.runtime_context
            pre_compact_runtime_context = rebound.pre_compact_runtime_context
            request_base = rebound.request_base
            first_request = rebound.first_request
            current_request = rebound.current_request
            latest_actual_usage = rebound.latest_actual_usage

        final_quality_rounds = 5 if resolved_agent.agent_id == "bazi" else 2
        for _ in range(self.max_tool_rounds + final_quality_rounds):
            generation_name = "llm.first" if not tool_history else "llm.followup"
            generation_stage = "llm_first" if not tool_history else "llm_second"
            generation_observed = False
            try:
                self._raise_if_interrupted(stop_event, deadline_monotonic)
                llm_started_at = time.perf_counter()
                current_request = current_request.model_copy(
                    update={
                        "timeout_seconds_override": timeout_seconds_override
                        if timeout_seconds_override is not None
                        else remaining_timeout_seconds(deadline_monotonic),
                        "cooperative_stop_event": stop_event,
                        "cooperative_deadline_monotonic": deadline_monotonic,
                    }
                )
                local_reply = _host_orchestrated_bazi_tool_reply(
                    current_request,
                    resolved_llm,
                )
                if local_reply is not None:
                    reply = local_reply
                    generation_observed = True
                else:
                    self.request_count += 1
                    llm_request_count += 1
                    reply = resolved_llm.complete(current_request)
                    reply = _enforce_bazi_repair_reply(current_request, reply)
                    self.langfuse_observer.observe_generation(
                    trace_handle,
                    name=generation_name,
                    model=getattr(resolved_llm, "model_name", None),
                    provider=getattr(resolved_llm, "provider_name", None),
                    input_payload=generation_input_payload(current_request),
                    output_payload=generation_output_payload(reply),
                    usage=usage_payload(reply.usage),
                    status="success",
                    latency_ms=elapsed_ms(llm_started_at),
                    metadata={
                        "stage": generation_stage,
                        "request_kind": current_request.request_kind,
                        "model_profile": provider_state.active_profile_name,
                    },
                    observation_policy=observation_policy,
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
                if (
                    current_request.request_kind
                    in {"finalization_retry", "bazi_final_generation"}
                    and reply.tool_name
                ):
                    finalization_evidence_ledger = build_current_turn_evidence_ledger(
                        user_message=message,
                        tool_history=tool_history,
                        model_request_count=llm_request_count,
                        base_ledger=current_request.finalization_evidence_ledger,
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
                        record_finalization_diagnostics(
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
                    record_finalization_diagnostics(
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
                if (
                    reply.tool_name
                    and resolved_agent.agent_id == "bazi"
                    and _bazi_required_analysis_complete(
                        message,
                        tool_history,
                        require_case_search="bazi_case" in first_request.available_tools,
                    )
                    and not bazi_final_generation_used
                ):
                    finalization_evidence_ledger = build_current_turn_evidence_ledger(
                        user_message=message,
                        tool_history=tool_history,
                        model_request_count=llm_request_count,
                        base_ledger=current_request.finalization_evidence_ledger,
                    )
                    bazi_final_generation_used = True
                    current_request = build_bazi_final_generation_request(
                        first_request,
                        tool_history=tool_history,
                        finalization_evidence_ledger=finalization_evidence_ledger,
                    ).model_copy(
                        update={
                            "timeout_seconds_override": timeout_seconds_override
                            if timeout_seconds_override is not None
                            else remaining_timeout_seconds(deadline_monotonic),
                            "cooperative_stop_event": stop_event,
                            "cooperative_deadline_monotonic": deadline_monotonic,
                        }
                    )
                    continue
                if is_duplicate_spawn_subagent_followup(
                    current_request,
                    reply,
                    tool_history,
                ):
                    finalization_evidence_ledger = build_current_turn_evidence_ledger(
                        user_message=message,
                        tool_history=tool_history,
                        model_request_count=llm_request_count,
                        base_ledger=current_request.finalization_evidence_ledger,
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
                        record_finalization_diagnostics(
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
                if reply.tool_name and len(tool_history) >= self.max_tool_rounds:
                    compact_summary_retry_eligible = bool(
                        str(first_request.compact_summary_text or "").strip()
                    )
                    if compact_summary_retry_eligible and not finalization_retry_used:
                        compaction_retry_ledger = deprioritize_tool_evidence_requirements(
                            build_current_turn_evidence_ledger(
                                user_message=message,
                                tool_history=tool_history,
                                model_request_count=llm_request_count,
                                base_ledger=current_request.finalization_evidence_ledger,
                            )
                        )
                        finalization_retry_used = True
                        current_request = build_finalization_retry_request(
                            first_request,
                            tool_history=tool_history,
                            finalization_evidence_ledger=compaction_retry_ledger,
                        ).model_copy(
                            update={
                                "timeout_seconds_override": timeout_seconds_override
                                if timeout_seconds_override is not None
                                else remaining_timeout_seconds(deadline_monotonic),
                                "cooperative_stop_event": stop_event,
                                "cooperative_deadline_monotonic": deadline_monotonic,
                            }
                        )
                        continue
                    break
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
                            "allowed_tools": list(resolved_agent.allowed_tools),
                            "allowed_knowledge_namespaces": (
                                list(resolved_agent.allowed_knowledge_namespaces)
                                if resolved_agent.allowed_knowledge_namespaces is not None
                                else None
                            ),
                            "allowed_knowledge_actions": (
                                list(resolved_agent.allowed_knowledge_actions)
                                if resolved_agent.allowed_knowledge_actions is not None
                                else None
                            ),
                            "model_profile": provider_state.active_profile_name,
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
                            else remaining_timeout_seconds(deadline_monotonic),
                            "turn_tool_state": turn_tool_state,
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
                            observation_policy=tool_observation_policy(
                                reply.tool_name or ""
                            ),
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
                        observation_policy=tool_observation_policy(
                            reply.tool_name or ""
                        ),
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
                        observation_policy=tool_observation_policy(
                            reply.tool_name or ""
                        ),
                    )
                    if tool_history:
                        recovered_text = recover_successful_tool_followup_text_with_meta(
                            tool_history,
                            model_request_count=llm_request_count,
                            finalization_evidence_ledger=build_current_turn_evidence_ledger(
                                user_message=message,
                                tool_history=tool_history,
                                model_request_count=llm_request_count,
                                base_ledger=current_request.finalization_evidence_ledger,
                            ),
                        ) or recover_tool_result_text(tool_history)
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
                        observation_policy=tool_observation_policy(
                            reply.tool_name or ""
                        ),
                    )
                    record_failure(self.self_improve_recorder, 
                        agent_id=resolved_agent.agent_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        channel_id=channel_id,
                        error_code=exc.error_code,
                        error_stage="tool",
                        message=observed_message,
                        summary=str(exc),
                        observation_policy=tool_observation_policy(
                            reply.tool_name or ""
                        ),
                    )
                    failed_tool_result = {
                        "ok": False,
                        "is_error": True,
                        "error_code": exc.error_code,
                        "error_text": str(exc),
                    }
                    self.history.record_tool_call(
                        run.run_id,
                        tool_name=reply.tool_name or "",
                        tool_payload=reply.tool_payload,
                        tool_result=failed_tool_result,
                        observation_policy=tool_observation_policy(
                            reply.tool_name or ""
                        ),
                    )
                    self.history.set_stage_timing(
                        run.run_id,
                        stage="tool",
                        elapsed_ms=elapsed_ms(tool_started_at),
                    )
                    if (
                        _is_repairable_memory_schema_failure(reply.tool_name, exc)
                        and not contract_repair_used
                    ):
                        append_tool_exchange(
                            tool_history,
                            tool_name=reply.tool_name or "",
                            tool_payload=reply.tool_payload,
                            tool_result=failed_tool_result,
                        )
                        self.history.set_finalization_state(
                            run.run_id,
                            assessment="retryable_degraded",
                            request_kind=current_request.request_kind,
                            required_evidence_count=0,
                            missing_evidence_items=[],
                            retry_triggered=True,
                            invalid_final_text=str(exc),
                        )
                        contract_repair_used = True
                        self.history.set_contract_repair_state(
                            run.run_id,
                            triggered=True,
                            reason="invalid_first_turn_finalization_contract",
                            attempt_count=1,
                            outcome="retrying",
                            selected_tool=reply.tool_name or None,
                            provider_ref=getattr(resolved_llm, "provider_name", None),
                        )
                        current_request = build_contract_repair_request(
                            first_request,
                            invalid_final_text=str(exc),
                        ).model_copy(
                            update={
                                "timeout_seconds_override": timeout_seconds_override
                                if timeout_seconds_override is not None
                                else remaining_timeout_seconds(deadline_monotonic),
                                "cooperative_stop_event": stop_event,
                                "cooperative_deadline_monotonic": deadline_monotonic,
                            }
                        )
                        continue
                    if tool_history:
                        recovered_text = recover_successful_tool_followup_text_with_meta(
                            tool_history,
                            model_request_count=llm_request_count,
                            finalization_evidence_ledger=build_current_turn_evidence_ledger(
                                user_message=message,
                                tool_history=tool_history,
                                model_request_count=llm_request_count,
                                base_ledger=current_request.finalization_evidence_ledger,
                            ),
                        ) or recover_tool_result_text(tool_history)
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
                        error_text="工具执行失败，请重试。",
                        agent_id=resolved_agent.agent_id,
                        post_commit_callback=self.self_improve_post_commit_callback,
                    )
            except Exception as exc:
                generation_elapsed_ms = elapsed_ms(llm_started_at)
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
                        input_payload=generation_input_payload(current_request),
                        output_payload={},
                        usage=None,
                        status="error",
                        latency_ms=generation_elapsed_ms,
                        metadata={
                            "stage": generation_stage,
                            "request_kind": request_kind,
                            "model_profile": provider_state.active_profile_name,
                        },
                        error_code=error_code,
                        observation_policy=observation_policy,
                    )
                normalized = normalize_provider_error(exc) if is_provider_failure(exc) else None
                provider_diagnostics = getattr(
                    resolved_llm, "last_call_diagnostics", None
                )
                if provider_diagnostics is None and normalized is not None:
                    provider_diagnostics = self._synthesized_provider_diagnostics(
                        request=current_request,
                        llm=resolved_llm,
                        normalized_error=normalized,
                        elapsed_ms=generation_elapsed_ms,
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
                    elapsed_ms=generation_elapsed_ms,
                )
                if normalized is not None:
                    if (
                        resolved_compacted_context is None
                        and is_reactive_compaction_error(exc)
                    ):
                        decision = CompactionDecision.REACTIVE
                        reactive_before_estimate = estimate_request_tokens(
                            current_request
                        )
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
                                repository_context_text=repository_context_text,
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
                                    else remaining_timeout_seconds(deadline_monotonic),
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
                                    estimated_input_tokens_before=reactive_before_estimate,
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
                    if current_request.request_kind == "finalization_retry" and tool_history:
                        finalization_evidence_ledger = build_current_turn_evidence_ledger(
                            user_message=message,
                            tool_history=tool_history,
                            model_request_count=llm_request_count,
                            base_ledger=current_request.finalization_evidence_ledger,
                        )
                        invalid_final_text = " ".join(
                            str(current_request.invalid_final_text or "").split()
                        ).strip()
                        finalization_details = assess_finalization_text_with_details(
                            tool_history,
                            invalid_final_text,
                            user_message=message,
                            model_request_count=llm_request_count,
                            finalization_evidence_ledger=finalization_evidence_ledger,
                            enforce_structured_contract=False,
                        )
                        if (
                            invalid_final_text
                            and finalization_details.assessment == "accepted"
                        ):
                            record_finalization_diagnostics(
                                self.history,
                                run_id=run.run_id,
                                request_kind=current_request.request_kind,
                                details=finalization_details,
                                retry_triggered=True,
                                recovered_from_fragments=True,
                                invalid_final_text=invalid_final_text,
                            )
                            finalize_success(final_text=invalid_final_text)
                            return finish_run_success(history=self.history, self_improve_recorder=self.self_improve_recorder, append_post_turn_summary_callback=self._append_post_turn_summary, post_commit_callback=self.self_improve_post_commit_callback,
                                events=events,
                                session_id=session_id,
                                run_id=run.run_id,
                                trace_id=trace_id,
                                run_started_at=run_started_at,
                                llm_request_count=llm_request_count,
                                message=message,
                                agent_id=resolved_agent.agent_id,
                                final_text=invalid_final_text,
                                tool_history=tool_history,
                                tool_snapshot=tool_snapshot,
                                channel_id=channel_id,
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
                    record_failure(self.self_improve_recorder, 
                        agent_id=resolved_agent.agent_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        channel_id=channel_id,
                        error_code=normalized.error_code,
                        error_stage="llm",
                        message=observed_message,
                        summary=str(exc),
                        provider_name=getattr(resolved_llm, "provider_name", None),
                        observation_policy=observation_policy,
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
                    message=observed_message,
                    summary=str(exc),
                    observation_policy=observation_policy,
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
                if resolved_agent.agent_id == "bazi":
                    if current_request.request_kind in {
                        "bazi_final_generation",
                        "bazi_analysis_draft_repair",
                    }:
                        parsed_draft = parse_bazi_analysis_draft(final_text)
                        if parsed_draft is None:
                            if not bool(
                                getattr(
                                    resolved_llm,
                                    "host_orchestrated_bazi_pipeline",
                                    False,
                                )
                            ):
                                final_text = normalize_bazi_timing_contract_text(
                                    final_text
                                )
                            elif not bazi_structured_generation_retry_used:
                                bazi_structured_generation_retry_used = True
                                current_request = build_bazi_final_generation_request(
                                    first_request,
                                    tool_history=tool_history,
                                ).model_copy(
                                    update={
                                        "invalid_final_text": (
                                            "上一版未返回可解析的 response schema JSON，请完整重新生成。"
                                        ),
                                        "timeout_seconds_override": timeout_seconds_override
                                        if timeout_seconds_override is not None
                                        else remaining_timeout_seconds(deadline_monotonic),
                                    }
                                )
                                continue
                            else:
                                finalize_error(error_code="BAZI_STRUCTURED_OUTPUT_FAILED")
                                return finish_run_error(
                                    history=self.history,
                                    events=events,
                                    session_id=session_id,
                                    run_id=run.run_id,
                                    trace_id=trace_id,
                                    run_started_at=run_started_at,
                                    llm_request_count=llm_request_count,
                                    error_code="BAZI_STRUCTURED_OUTPUT_FAILED",
                                    error_text="八字答案未能生成有效结构，请重试本次解盘。",
                                    agent_id=resolved_agent.agent_id,
                                    post_commit_callback=self.self_improve_post_commit_callback,
                                )
                        else:
                            normalized_draft = parsed_draft.model_copy(
                                update={
                                    "verification_candidates": normalize_bazi_verification_candidate_reasons(
                                        parsed_draft.verification_candidates,
                                        parsed_draft.verification_events,
                                    )
                                }
                            )
                            (
                                bazi_analysis_draft,
                                fact_findings,
                            ) = bind_bazi_verification_facts(
                                normalized_draft,
                                build_bazi_timing_fact_registry(tool_history),
                            )
                            bazi_fact_reference_violations = tuple(
                                finding.message for finding in fact_findings
                            )
                            final_text = render_bazi_analysis_draft(bazi_analysis_draft)
                    elif current_request.request_kind == "bazi_verification_event_repair":
                        patch = parse_bazi_verification_events_patch(final_text)
                        if patch is None or bazi_analysis_draft is None:
                            finalize_error(error_code="BAZI_EVENT_REPAIR_FAILED")
                            return finish_run_error(
                                history=self.history,
                                events=events,
                                session_id=session_id,
                                run_id=run.run_id,
                                trace_id=trace_id,
                                run_started_at=run_started_at,
                                llm_request_count=llm_request_count,
                                error_code="BAZI_EVENT_REPAIR_FAILED",
                                error_text="过三关修复未生成有效结构，请重试本次解盘。",
                                agent_id=resolved_agent.agent_id,
                                post_commit_callback=self.self_improve_post_commit_callback,
                            )
                        normalized_candidates = normalize_bazi_verification_candidate_reasons(
                            patch.verification_candidates,
                            patch.verification_events,
                        )
                        patched_draft = bazi_analysis_draft.model_copy(
                            update={
                                "verification_candidates": normalized_candidates,
                                "verification_events": patch.verification_events,
                            }
                        )
                        (
                            bazi_analysis_draft,
                            fact_findings,
                        ) = bind_bazi_verification_facts(
                            patched_draft,
                            build_bazi_timing_fact_registry(tool_history),
                        )
                        bazi_fact_reference_violations = tuple(
                            finding.message for finding in fact_findings
                        )
                        final_text = render_bazi_analysis_draft(bazi_analysis_draft)
                        bazi_semantic_review_completed = False
                    if (
                        current_request.request_kind == "bazi_output_semantic_review"
                        and bazi_semantic_review_source_text is not None
                    ):
                        review = parse_bazi_semantic_review(final_text)
                        reviewed_text = bazi_semantic_review_source_text
                        bazi_semantic_review_source_text = None
                        review_violations = tuple(
                            dict.fromkeys(
                                (
                                    *bazi_pending_verification_violations,
                                    *review.violations,
                                )
                            )
                        )
                        rejected_event_labels = tuple(
                            dict.fromkeys(
                                (
                                    *bazi_pending_rejected_event_labels,
                                    *review.rejected_events,
                                )
                            )
                        )
                        bazi_pending_verification_violations = ()
                        bazi_pending_rejected_event_labels = ()
                        bazi_semantic_review_attempts += 1
                        bazi_semantic_review_completed = (
                            review.passed and not review_violations
                        )
                        if not bazi_semantic_review_completed:
                            logger.warning(
                                "bazi semantic output repair required run_id=%s violations=%s",
                                run.run_id,
                                "；".join(review_violations),
                            )
                            pruned_draft = (
                                prune_semantically_rejected_verification_events(
                                    bazi_analysis_draft,
                                    rejected_event_labels,
                                )
                                if bazi_analysis_draft is not None
                                else None
                            )
                            if pruned_draft is not None:
                                pruned_text = render_bazi_analysis_draft(pruned_draft)
                                pruned_violations = bazi_timing_contract_violations(
                                    pruned_text,
                                    expected_shensha_years=_bazi_key_shensha_years(
                                        tool_history
                                    ),
                                )
                                if not pruned_violations:
                                    bazi_analysis_draft = pruned_draft
                                    final_text = pruned_text
                                    bazi_semantic_review_completed = True
                                    logger.info(
                                        "bazi semantic review pruned rejected events run_id=%s removed=%s retained=%s",
                                        run.run_id,
                                        len(rejected_event_labels),
                                        len(pruned_draft.verification_events),
                                    )
                            if (
                                not bazi_semantic_review_completed
                                and bazi_semantic_repair_attempts < 2
                                and bazi_analysis_draft is not None
                            ):
                                bazi_semantic_repair_attempts += 1
                                current_request = build_bazi_verification_event_repair_request(
                                    first_request,
                                    tool_history=tool_history,
                                    current_events_json=json.dumps(
                                        {
                                            "verification_candidates": [
                                                candidate.model_dump()
                                                for candidate in bazi_analysis_draft.verification_candidates
                                            ],
                                            "verification_events": [
                                                event.model_dump()
                                                for event in bazi_analysis_draft.verification_events
                                            ],
                                        },
                                        ensure_ascii=False,
                                    ),
                                    violations=list(review_violations),
                                )
                                current_request = current_request.model_copy(
                                    update={
                                        "timeout_seconds_override": timeout_seconds_override
                                        if timeout_seconds_override is not None
                                        else remaining_timeout_seconds(deadline_monotonic)
                                    }
                                )
                                continue
                            if (
                                not bazi_semantic_review_completed
                                and bazi_analysis_draft is None
                                and bazi_semantic_repair_attempts < 2
                            ):
                                bazi_semantic_repair_attempts += 1
                                bazi_analysis_repair_source_text = reviewed_text
                                bazi_analysis_repair_sections = ["过三关"]
                                current_request = build_bazi_output_repair_request(
                                    first_request,
                                    invalid_final_text=bazi_repair_source_text(
                                        reviewed_text,
                                        bazi_analysis_repair_sections,
                                    ),
                                    violations=[
                                        f"过三关语义审查未通过：{item}"
                                        for item in review_violations
                                    ],
                                ).model_copy(
                                    update={
                                        "timeout_seconds_override": timeout_seconds_override
                                        if timeout_seconds_override is not None
                                        else remaining_timeout_seconds(deadline_monotonic)
                                    }
                                )
                                continue
                            if not bazi_semantic_review_completed:
                                logger.warning(
                                    "bazi semantic output review exhausted run_id=%s attempts=%s",
                                    run.run_id,
                                    bazi_semantic_review_attempts,
                                )
                                self.history.set_finalization_state(
                                    run.run_id,
                                    assessment="rejected",
                                    request_kind=current_request.request_kind,
                                    required_evidence_count=0,
                                    missing_evidence_items=list(review_violations),
                                    retry_triggered=True,
                                )
                                finalize_error(error_code="BAZI_SEMANTIC_REVIEW_FAILED")
                                return finish_run_error(
                                    history=self.history,
                                    events=events,
                                    session_id=session_id,
                                    run_id=run.run_id,
                                    trace_id=trace_id,
                                    run_started_at=run_started_at,
                                    llm_request_count=llm_request_count,
                                    error_code="BAZI_SEMANTIC_REVIEW_FAILED",
                                    error_text="过三关未通过质量审查，请重试本次解盘。",
                                    agent_id=resolved_agent.agent_id,
                                    post_commit_callback=self.self_improve_post_commit_callback,
                                )
                        if review.passed:
                            final_text = reviewed_text
                    if (
                        current_request.request_kind == "bazi_output_repair"
                        and bazi_analysis_repair_source_text is not None
                    ):
                        repaired_final_text = merge_bazi_repaired_sections(
                            bazi_analysis_repair_source_text,
                            final_text,
                            bazi_analysis_repair_sections,
                        )
                        normalized_repaired_final_text = (
                            normalize_bazi_timing_contract_text(repaired_final_text)
                        )
                        if missing_bazi_sections(normalized_repaired_final_text):
                            logger.warning(
                                "bazi output repair discarded run_id=%s reason=missing_sections sections=%s",
                                run.run_id,
                                "、".join(
                                    missing_bazi_sections(normalized_repaired_final_text)
                                ),
                            )
                            final_text = normalize_bazi_timing_contract_text(
                                bazi_analysis_repair_source_text
                            )
                        else:
                            final_text = normalized_repaired_final_text
                        if bazi_semantic_repair_attempts:
                            bazi_semantic_review_completed = False
                    else:
                        final_text = normalize_bazi_timing_contract_text(final_text)
                if (
                    resolved_agent.agent_id == "bazi"
                    and not _bazi_has_chart_facts(tool_history)
                    and _bazi_has_actionable_birth_input(message)
                    and "bazi" in first_request.available_tools
                    and not bazi_chart_repair_used
                ):
                    bazi_chart_repair_used = True
                    current_request = first_request.model_copy(
                        update={
                            "tool_history": list(tool_history),
                            "tool_result": None,
                            "requested_tool_name": "bazi",
                            "requested_tool_payload": {},
                            "request_kind": "bazi_chart_repair",
                            "invalid_final_text": final_text,
                            "timeout_seconds_override": timeout_seconds_override
                            if timeout_seconds_override is not None
                            else remaining_timeout_seconds(deadline_monotonic),
                            "cooperative_stop_event": stop_event,
                            "cooperative_deadline_monotonic": deadline_monotonic,
                        }
                    )
                    continue
                if (
                    resolved_agent.agent_id == "bazi"
                    and _bazi_dayun_requested(message)
                    and _bazi_has_dayun_seed(tool_history, message)
                    and not _bazi_has_required_dayun(
                        tool_history,
                        require_annuals=bazi_requires_complete_dayun,
                    )
                    and "bazi" in first_request.available_tools
                    and not bazi_dayun_repair_used
                ):
                    dayun_payload = _bazi_dayun_payload(tool_history, message)
                    if dayun_payload is not None:
                        bazi_dayun_repair_used = True
                        current_request = first_request.model_copy(
                            update={
                                "tool_history": list(tool_history),
                                "tool_result": None,
                                "requested_tool_name": "bazi",
                                "requested_tool_payload": dayun_payload,
                                "request_kind": "bazi_dayun_repair",
                                "invalid_final_text": final_text,
                                "timeout_seconds_override": timeout_seconds_override
                                if timeout_seconds_override is not None
                                else remaining_timeout_seconds(deadline_monotonic),
                                "cooperative_stop_event": stop_event,
                                "cooperative_deadline_monotonic": deadline_monotonic,
                            }
                        )
                        continue
                if (
                    resolved_agent.agent_id == "bazi"
                    and _bazi_has_chart_facts(tool_history)
                    and _bazi_chart_dayun_fingerprints_match(tool_history)
                    and not _bazi_has_knowledge_search(tool_history)
                    and "knowledge" in first_request.available_tools
                    and not bazi_knowledge_repair_used
                ):
                    bazi_knowledge_repair_used = True
                    current_request = first_request.model_copy(
                        update={
                            "tool_history": list(tool_history),
                            "tool_result": None,
                            "requested_tool_name": "knowledge",
                            "requested_tool_payload": {
                                "action": "search",
                                "namespace": "bazi-theory",
                                "top_k": 8,
                            },
                            "request_kind": "bazi_knowledge_search",
                            "invalid_final_text": final_text,
                            "timeout_seconds_override": timeout_seconds_override
                            if timeout_seconds_override is not None
                            else remaining_timeout_seconds(deadline_monotonic),
                            "cooperative_stop_event": stop_event,
                            "cooperative_deadline_monotonic": deadline_monotonic,
                        }
                    )
                    continue
                if (
                    resolved_agent.agent_id == "bazi"
                    and _bazi_dayun_requested(message)
                    and _bazi_has_chart_facts(tool_history)
                    and _bazi_has_knowledge_search(tool_history)
                    and not _bazi_has_case_search(tool_history)
                    and "bazi_case" in first_request.available_tools
                    and not bazi_case_repair_used
                ):
                    bazi_case_repair_used = True
                    current_request = first_request.model_copy(
                        update={
                            "tool_history": list(tool_history),
                            "tool_result": None,
                            "requested_tool_name": "bazi_case",
                            "requested_tool_payload": {"action": "search", "top_k": 3},
                            "request_kind": "bazi_case_search",
                            "invalid_final_text": final_text,
                            "timeout_seconds_override": timeout_seconds_override
                            if timeout_seconds_override is not None
                            else remaining_timeout_seconds(deadline_monotonic),
                            "cooperative_stop_event": stop_event,
                            "cooperative_deadline_monotonic": deadline_monotonic,
                        }
                    )
                    continue
                bazi_timing_violations = (
                    bazi_timing_contract_violations(
                        final_text,
                        expected_shensha_years=_bazi_key_shensha_years(tool_history),
                    )
                    if resolved_agent.agent_id == "bazi"
                    and _bazi_has_dayun(tool_history)
                    and _bazi_has_knowledge_search(tool_history)
                    else []
                )
                if bazi_analysis_draft is not None:
                    bazi_timing_violations.extend(bazi_fact_reference_violations)
                    bazi_timing_violations.extend(
                        bazi_verification_group_violations(
                            bazi_analysis_draft.verification_candidates,
                            bazi_analysis_draft.verification_events
                        )
                    )
                    bazi_timing_violations.extend(
                        deterministic_verification_event_violations(
                            bazi_analysis_draft.verification_events
                        )
                    )
                    bazi_timing_violations = list(
                        dict.fromkeys(bazi_timing_violations)
                    )
                typed_bazi_violations = classify_bazi_contract_violations(
                    bazi_timing_violations
                )
                verification_only_violations = bool(typed_bazi_violations) and all(
                    violation.scope == "verification"
                    for violation in typed_bazi_violations
                )
                if (
                    verification_only_violations
                    and bazi_analysis_draft is not None
                    and bazi_semantic_repair_attempts < 2
                ):
                    logger.warning(
                        "bazi verification patch required run_id=%s violations=%s",
                        run.run_id,
                        "；".join(bazi_timing_violations),
                    )
                    bazi_semantic_repair_attempts += 1
                    current_request = build_bazi_verification_event_repair_request(
                        first_request,
                        tool_history=tool_history,
                        current_events_json=json.dumps(
                            {
                                "verification_candidates": [
                                    candidate.model_dump()
                                    for candidate in bazi_analysis_draft.verification_candidates
                                ],
                                "verification_events": [
                                    event.model_dump()
                                    for event in bazi_analysis_draft.verification_events
                                ],
                            },
                            ensure_ascii=False,
                        ),
                        violations=bazi_timing_violations,
                    ).model_copy(
                        update={
                            "timeout_seconds_override": timeout_seconds_override
                            if timeout_seconds_override is not None
                            else remaining_timeout_seconds(deadline_monotonic)
                        }
                    )
                    continue
                if (
                    bazi_timing_violations
                    and (
                        not verification_only_violations
                        or bazi_analysis_draft is None
                    )
                    and bazi_analysis_repair_attempts < 1
                ):
                    logger.warning(
                        "bazi output contract repair required run_id=%s violations=%s",
                        run.run_id,
                        "；".join(bazi_timing_violations),
                    )
                    bazi_analysis_repair_attempts += 1
                    if bazi_analysis_draft is not None:
                        current_request = build_bazi_analysis_draft_repair_request(
                            first_request,
                            tool_history=tool_history,
                            invalid_draft_text=bazi_analysis_draft.model_dump_json(),
                            violations=bazi_timing_violations,
                        )
                    else:
                        bazi_analysis_repair_sections = bazi_violation_sections(
                            bazi_timing_violations
                        )
                        bazi_analysis_repair_source_text = final_text
                        current_request = build_bazi_output_repair_request(
                            first_request,
                            invalid_final_text=bazi_repair_source_text(
                                final_text,
                                bazi_analysis_repair_sections,
                            ),
                            violations=bazi_timing_violations,
                        )
                    current_request = current_request.model_copy(
                        update={
                            "timeout_seconds_override": timeout_seconds_override
                            if timeout_seconds_override is not None
                            else remaining_timeout_seconds(deadline_monotonic)
                        }
                    )
                    continue
                if bazi_timing_violations:
                    logger.warning(
                        "bazi output contract repair exhausted run_id=%s attempts=%s violations=%s",
                        run.run_id,
                        bazi_analysis_repair_attempts,
                        "；".join(bazi_timing_violations),
                    )
                    self.history.set_finalization_state(
                        run.run_id,
                        assessment="rejected",
                        request_kind=current_request.request_kind,
                        required_evidence_count=0,
                        missing_evidence_items=bazi_timing_violations,
                        retry_triggered=True,
                    )
                    finalize_error(error_code="BAZI_OUTPUT_CONTRACT_FAILED")
                    return finish_run_error(
                        history=self.history,
                        events=events,
                        session_id=session_id,
                        run_id=run.run_id,
                        trace_id=trace_id,
                        run_started_at=run_started_at,
                        llm_request_count=llm_request_count,
                        error_code="BAZI_OUTPUT_CONTRACT_FAILED",
                        error_text="八字答案未通过结构与事实审查，请重试本次解盘。",
                        agent_id=resolved_agent.agent_id,
                        post_commit_callback=self.self_improve_post_commit_callback,
                    )
                if (
                    resolved_agent.agent_id == "bazi"
                    and current_request.request_kind
                    in {
                        "bazi_final_generation",
                        "bazi_analysis_draft_repair",
                        "bazi_output_repair",
                        "bazi_verification_event_repair",
                    }
                    and not missing_bazi_sections(final_text)
                    and not bazi_timing_violations
                    and not bazi_semantic_review_completed
                ):
                    bazi_semantic_review_source_text = final_text
                    current_request = build_bazi_output_semantic_review_request(
                        first_request,
                        tool_history=tool_history,
                        candidate_text=final_text,
                        verification_events_json=(
                            json.dumps(
                                {
                                    "verification_candidates": [
                                        candidate.model_dump()
                                        for candidate in bazi_analysis_draft.verification_candidates
                                    ],
                                    "verification_events": [
                                        event.model_dump()
                                        for event in bazi_analysis_draft.verification_events
                                    ],
                                },
                                ensure_ascii=False,
                            )
                            if bazi_analysis_draft is not None
                            else None
                        ),
                    ).model_copy(
                        update={
                            "timeout_seconds_override": timeout_seconds_override
                            if timeout_seconds_override is not None
                            else remaining_timeout_seconds(deadline_monotonic)
                        }
                    )
                    continue
                if (
                    resolved_agent.agent_id == "bazi"
                    and current_request.request_kind
                    in {
                        "bazi_final_generation",
                        "bazi_analysis_draft_repair",
                        "bazi_output_repair",
                        "bazi_output_semantic_review",
                        "bazi_verification_event_repair",
                    }
                    and not missing_bazi_sections(final_text)
                    and not bazi_timing_violations
                    and bazi_semantic_review_completed
                ):
                    self.history.set_finalization_state(
                        run.run_id,
                        assessment="accepted",
                        request_kind=current_request.request_kind,
                        required_evidence_count=0,
                        missing_evidence_items=[],
                        retry_triggered=False,
                    )
                    finalize_success(final_text=final_text)
                    return finish_run_success(
                        history=self.history,
                        self_improve_recorder=self.self_improve_recorder,
                        append_post_turn_summary_callback=self._append_post_turn_summary,
                        post_commit_callback=self.self_improve_post_commit_callback,
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
                        channel_id=channel_id,
                    )
                effective_finalization_contract_draft = (
                    _infer_required_first_turn_contract_from_text(
                        final_text,
                        user_message=message,
                        actual_draft=reply.finalization_contract_draft,
                    )
                )
                invalid_first_turn_finalization_contract = (
                    _first_violated_finalization_contract(
                        tool_history,
                        final_text,
                        user_message=message,
                        finalization_contract_draft=effective_finalization_contract_draft,
                        enforce_structured_contract=True,
                    )
                    is not None
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
                        current_request = build_contract_repair_request(
                            first_request,
                            invalid_final_text=final_text,
                        ).model_copy(
                            update={
                                "timeout_seconds_override": timeout_seconds_override
                                if timeout_seconds_override is not None
                                else remaining_timeout_seconds(deadline_monotonic),
                                "cooperative_stop_event": stop_event,
                                "cooperative_deadline_monotonic": deadline_monotonic,
                            }
                        )
                        continue
                    if (
                        final_text
                        and reply.finalization_contract_draft is None
                        and not _first_violated_finalization_contract(
                            tool_history,
                            final_text,
                            user_message=message,
                            finalization_contract_draft=FinalizationContractDraft(),
                            enforce_structured_contract=False,
                        )
                    ):
                        self.history.set_finalization_state(
                            run.run_id,
                            assessment="retryable_degraded",
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
                            outcome="final_text_missing_contract",
                            selected_tool=None,
                            provider_ref=getattr(resolved_llm, "provider_name", None),
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
                    finalization_evidence_ledger = build_current_turn_evidence_ledger(
                        user_message=message,
                        tool_history=tool_history,
                        model_request_count=llm_request_count,
                        base_ledger=current_request.finalization_evidence_ledger,
                    )
                    if (
                        finalization_retry_used
                        or current_request.request_kind == "finalization_retry"
                    ):
                        finalization_evidence_ledger = (
                            require_latest_failed_tool_evidence(
                                finalization_evidence_ledger,
                                tool_history,
                            )
                        )
                    finalization_evidence_ledger = _apply_finalization_draft_to_evidence_ledger(
                        finalization_evidence_ledger,
                        finalization_contract_draft=reply.finalization_contract_draft,
                    )
                    finalization_details = assess_finalization_text_with_details(
                        tool_history,
                        final_text,
                        user_message=message,
                        model_request_count=llm_request_count,
                        finalization_evidence_ledger=finalization_evidence_ledger,
                        finalization_contract_draft=reply.finalization_contract_draft,
                        enforce_structured_contract=True,
                    )
                    if (
                        finalization_details.assessment == "accepted"
                        and final_text_masks_failed_tool_result(
                            tool_history,
                            final_text,
                            finalization_evidence_ledger,
                        )
                    ):
                        finalization_details = failed_tool_details(tool_history)
                    if (
                        finalization_details.assessment == "retryable_degraded"
                        and not finalization_retry_used
                        and current_request.request_kind != "bazi_final_generation"
                    ):
                        record_finalization_diagnostics(
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
                            invalid_final_text=final_text,
                        ).model_copy(
                            update={
                                "timeout_seconds_override": timeout_seconds_override
                                if timeout_seconds_override is not None
                                else remaining_timeout_seconds(deadline_monotonic)
                            }
                        )
                        continue
                    if (
                        finalization_details.assessment == "retryable_degraded"
                        and current_request.request_kind != "bazi_final_generation"
                    ):
                        invalid_retry_text = _finalization_candidate_text(
                            request_kind=current_request.request_kind,
                            normalized_final_text=final_text,
                            raw_reply_text=reply.final_text,
                        )
                        final_text = recover_successful_tool_followup_text_with_meta(
                            tool_history,
                            model_request_count=llm_request_count,
                            finalization_evidence_ledger=finalization_evidence_ledger,
                        )
                        if (
                            final_text
                            and invalid_retry_text
                            and not is_generic_tool_failure_text(invalid_retry_text)
                        ):
                            repaired_details = assess_finalization_text_with_details(
                                tool_history,
                                invalid_retry_text,
                                user_message=message,
                                model_request_count=llm_request_count,
                                finalization_evidence_ledger=finalization_evidence_ledger,
                                finalization_contract_draft=reply.finalization_contract_draft,
                                enforce_structured_contract=True,
                            )
                            if repaired_details.assessment == "accepted":
                                final_text = invalid_retry_text
                                finalization_details = repaired_details
                            elif not repaired_details.missing_evidence_items:
                                final_text = invalid_retry_text
                                finalization_details = repaired_details
                        record_finalization_diagnostics(
                            self.history,
                            run_id=run.run_id,
                            request_kind=current_request.request_kind,
                            details=finalization_details,
                            retry_triggered=bool(
                                finalization_retry_used
                                or current_request.request_kind == "finalization_retry"
                            ),
                            recovered_from_fragments=bool(final_text and final_text != invalid_retry_text),
                            invalid_final_text=invalid_retry_text,
                        )
                    elif finalization_details.assessment == "unrecoverable":
                        record_finalization_diagnostics(
                            self.history,
                            run_id=run.run_id,
                            request_kind=current_request.request_kind,
                            details=finalization_details,
                            retry_triggered=finalization_retry_used,
                            invalid_final_text=final_text,
                        )
                        final_text = ""
                    else:
                        record_finalization_diagnostics(
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
                observation_policy=tool_observation_policy(reply.tool_name or ""),
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
                    finalization_evidence_ledger = build_current_turn_evidence_ledger(
                        user_message=message,
                        tool_history=tool_history,
                        model_request_count=llm_request_count,
                        base_ledger=current_request.finalization_evidence_ledger,
                    )
                    finalization_details = assess_finalization_text_with_details(
                        tool_history,
                        followup_render.terminal_text,
                        user_message=message,
                        model_request_count=llm_request_count,
                        finalization_evidence_ledger=finalization_evidence_ledger,
                    )
                    record_finalization_diagnostics(
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
                if (
                    len(tool_history) >= self.max_tool_rounds
                    and not finalization_retry_used
                    and str(first_request.compact_summary_text or "").strip()
                ):
                    compaction_retry_ledger = deprioritize_tool_evidence_requirements(
                        build_current_turn_evidence_ledger(
                            user_message=message,
                            tool_history=tool_history,
                            model_request_count=llm_request_count,
                            base_ledger=current_request.finalization_evidence_ledger,
                        )
                    )
                    finalization_retry_used = True
                    current_request = build_finalization_retry_request(
                        first_request,
                        tool_history=tool_history,
                        finalization_evidence_ledger=compaction_retry_ledger,
                    ).model_copy(
                        update={
                            "timeout_seconds_override": timeout_seconds_override
                            if timeout_seconds_override is not None
                            else remaining_timeout_seconds(deadline_monotonic),
                            "cooperative_stop_event": stop_event,
                            "cooperative_deadline_monotonic": deadline_monotonic,
                        }
                    )
                    continue
                if str(reply.tool_name or "").strip() == "session":
                    transition = tool_result.get("transition")
                    if isinstance(transition, dict) and transition.get("binding_changed") is True:
                        target_session_id = str(
                            transition.get("target_session_id") or ""
                        ).strip()
                        if target_session_id:
                            rebind_same_turn_session_context(target_session_id)
            if (
                resolved_agent.agent_id == "bazi"
                and _bazi_dayun_requested(message)
                and _bazi_has_dayun_seed(tool_history, message)
                and not _bazi_has_required_dayun(
                    tool_history,
                    require_annuals=bazi_requires_complete_dayun,
                )
                and "bazi" in first_request.available_tools
                and not bazi_dayun_repair_used
            ):
                dayun_payload = _bazi_dayun_payload(tool_history, message)
                if dayun_payload is not None:
                    bazi_dayun_repair_used = True
                    current_request = first_request.model_copy(
                        update={
                            "tool_history": list(tool_history),
                            "tool_result": None,
                            "requested_tool_name": "bazi",
                            "requested_tool_payload": dayun_payload,
                            "request_kind": "bazi_dayun_repair",
                            "invalid_final_text": None,
                            "timeout_seconds_override": timeout_seconds_override
                            if timeout_seconds_override is not None
                            else remaining_timeout_seconds(deadline_monotonic),
                            "cooperative_stop_event": stop_event,
                            "cooperative_deadline_monotonic": deadline_monotonic,
                        }
                    )
                    continue
            if (
                resolved_agent.agent_id == "bazi"
                and _bazi_has_chart_facts(tool_history)
                and _bazi_chart_dayun_fingerprints_match(tool_history)
                and not _bazi_has_knowledge_search(tool_history)
                and "knowledge" in first_request.available_tools
                and not bazi_knowledge_repair_used
            ):
                bazi_knowledge_repair_used = True
                current_request = first_request.model_copy(
                    update={
                        "tool_history": list(tool_history),
                        "tool_result": None,
                        "requested_tool_name": "knowledge",
                        "requested_tool_payload": {
                            "action": "search",
                            "namespace": "bazi-theory",
                            "top_k": 8,
                        },
                        "request_kind": "bazi_knowledge_search",
                        "invalid_final_text": None,
                        "timeout_seconds_override": timeout_seconds_override
                        if timeout_seconds_override is not None
                        else remaining_timeout_seconds(deadline_monotonic),
                        "cooperative_stop_event": stop_event,
                        "cooperative_deadline_monotonic": deadline_monotonic,
                    }
                )
                continue
            if (
                resolved_agent.agent_id == "bazi"
                and _bazi_dayun_requested(message)
                and _bazi_has_chart_facts(tool_history)
                and _bazi_has_knowledge_search(tool_history)
                and not _bazi_has_case_search(tool_history)
                and "bazi_case" in first_request.available_tools
                and not bazi_case_repair_used
            ):
                bazi_case_repair_used = True
                current_request = first_request.model_copy(
                    update={
                        "tool_history": list(tool_history),
                        "tool_result": None,
                        "requested_tool_name": "bazi_case",
                        "requested_tool_payload": {"action": "search", "top_k": 3},
                        "request_kind": "bazi_case_search",
                        "invalid_final_text": None,
                        "timeout_seconds_override": timeout_seconds_override
                        if timeout_seconds_override is not None
                        else remaining_timeout_seconds(deadline_monotonic),
                        "cooperative_stop_event": stop_event,
                        "cooperative_deadline_monotonic": deadline_monotonic,
                    }
                )
                continue
            if (
                resolved_agent.agent_id == "bazi"
                and _bazi_required_analysis_complete(
                    message,
                    tool_history,
                    require_case_search="bazi_case" in first_request.available_tools,
                )
                and not bazi_final_generation_used
            ):
                finalization_evidence_ledger = build_current_turn_evidence_ledger(
                    user_message=message,
                    tool_history=tool_history,
                    model_request_count=llm_request_count,
                    base_ledger=current_request.finalization_evidence_ledger,
                )
                bazi_final_generation_used = True
                current_request = build_bazi_final_generation_request(
                    first_request,
                    tool_history=tool_history,
                    finalization_evidence_ledger=finalization_evidence_ledger,
                ).model_copy(
                    update={
                        "timeout_seconds_override": timeout_seconds_override
                        if timeout_seconds_override is not None
                        else remaining_timeout_seconds(deadline_monotonic),
                        "cooperative_stop_event": stop_event,
                        "cooperative_deadline_monotonic": deadline_monotonic,
                    }
                )
                continue
            provisional_request = build_tool_followup_request(
                first_request,
                tool_history=tool_history,
                tool_result=tool_result,
                requested_tool_name=reply.tool_name,
                requested_tool_payload=reply.tool_payload,
                finalization_evidence_ledger=build_current_turn_evidence_ledger(
                    user_message=message,
                    tool_history=tool_history,
                    model_request_count=llm_request_count,
                    base_ledger=current_request.finalization_evidence_ledger,
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
                finalization_evidence_ledger=build_current_turn_evidence_ledger(
                    user_message=message,
                    tool_history=tool_history,
                    model_request_count=llm_request_count,
                    base_ledger=current_request.finalization_evidence_ledger,
                ),
            ).model_copy(
                update={
                    "timeout_seconds_override": timeout_seconds_override
                    if timeout_seconds_override is not None
                    else remaining_timeout_seconds(deadline_monotonic)
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
            message=observed_message,
            summary="tool loop limit exceeded",
            observation_policy=observation_policy,
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


def _is_repairable_memory_schema_failure(tool_name: str | None, exc: ToolExecutionFailed) -> bool:
    if str(tool_name or "").strip() != "memory":
        return False
    return str(getattr(exc, "cause_error_code", "") or "").strip() in {
        "MEMORY_DELETE_SCOPE_REQUIRED",
        "MEMORY_WRITE_SCOPE_REQUIRED",
        "MEMORY_WRITE_TYPE_REQUIRED",
    }


def _bazi_analysis_evidence_complete(tool_history: list[ToolExchange]) -> bool:
    has_chart_facts = _bazi_has_chart_facts(tool_history)
    has_theory = False
    for exchange in tool_history:
        result = exchange.tool_result
        if not isinstance(result, dict) or result.get("ok") is not True:
            continue
        action = str(exchange.tool_payload.get("action") or result.get("action") or "").strip()
        if exchange.tool_name == "knowledge" and action == "search":
            results = result.get("results")
            if isinstance(results, list) and any(
                isinstance(item, dict)
                and str(item.get("text") or "").strip()
                and str(item.get("source_id") or "").strip()
                and str(item.get("chunk_id") or "").strip()
                for item in results
            ):
                has_theory = True
    return has_chart_facts and has_theory


def _bazi_required_analysis_complete(
    user_message: str,
    tool_history: list[ToolExchange],
    *,
    require_case_search: bool = False,
) -> bool:
    if (
        _bazi_dayun_requested(user_message)
        and _bazi_has_dayun_seed(tool_history, user_message)
        and not _bazi_has_dayun(tool_history)
    ):
        return False
    if (
        require_case_search
        and _bazi_dayun_requested(user_message)
        and not _bazi_has_case_search(tool_history)
    ):
        return False
    return _bazi_analysis_evidence_complete(tool_history)


def _bazi_dayun_requested(user_message: str) -> bool:
    normalized = " ".join(str(user_message or "").lower().split())
    return _bazi_has_actionable_birth_input(user_message) or any(
        marker in normalized
        for marker in (
            "大运",
            "起运",
            "阶段趋势",
            "完整解盘",
            "过三关",
            "子平",
            "盲派",
            "分析",
            "解盘",
            "dayun",
            "fortune cycle",
        )
    )


def _bazi_has_actionable_birth_input(user_message: str) -> bool:
    text = str(user_message or "").strip()
    pillars = re.findall(r"[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]", text)
    if _explicit_bazi_gender(text) is not None and len(pillars) >= 4:
        return True
    has_birth_date = bool(
        re.search(r"(?:19|20)\d{2}\s*年", text)
        and re.search(r"(?:农历|公历|阳历)", text)
        and re.search(r"[一二三四五六七八九十冬腊\d]+\s*月", text)
        and re.search(r"[初一二三四五六七八九十廿卅\d]+\s*(?:日|号)", text)
    )
    has_birth_time = bool(re.search(r"\d{1,2}\s*(?::|点|时)", text))
    has_birth_place = bool(re.search(r"(?:省|自治区|市).*(?:市|县|区|旗)", text))
    return (
        _explicit_bazi_gender(text) is not None
        and has_birth_date
        and has_birth_time
        and has_birth_place
    )


def _bazi_dayun_payload(
    tool_history: list[ToolExchange],
    user_message: str = "",
) -> dict[str, object] | None:
    for exchange in tool_history:
        if exchange.tool_name != "bazi":
            continue
        action = str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        if exchange.tool_result.get("ok") is not True:
            continue
        if action == "chart":
            return {
                **exchange.tool_payload,
                "action": "dayun",
                "detailLevel": "full",
            }
        if action == "resolve_pillars":
            return _bazi_dayun_payload_from_resolve(
                exchange,
                fallback_gender=_explicit_bazi_gender(user_message),
            )
    return None


def _bazi_dayun_payload_from_resolve(
    exchange: ToolExchange,
    *,
    fallback_gender: str | None = None,
) -> dict[str, object] | None:
    gender = str(exchange.tool_payload.get("gender") or fallback_gender or "").strip()
    if gender not in {"male", "female"}:
        return None
    result = exchange.tool_result.get("result")
    candidates = result.get("候选列表") if isinstance(result, dict) else None
    if not isinstance(candidates, list):
        return None
    current_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    past_candidates: list[datetime] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        solar_text = str(candidate.get("公历") or "").strip()
        try:
            solar_time = datetime.strptime(solar_text, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if 1901 <= solar_time.year <= 2100 and solar_time.date() <= current_date:
            past_candidates.append(solar_time)
    if len(past_candidates) != 1:
        return None
    selected = past_candidates[0]
    return {
        "action": "dayun",
        "gender": gender,
        "birthYear": selected.year,
        "birthMonth": selected.month,
        "birthDay": selected.day,
        "birthHour": selected.hour,
        "birthMinute": selected.minute,
        "calendarType": "solar",
        "isLeapMonth": False,
        "timeBasis": "clock",
        "timezone": "Asia/Shanghai",
        "sourceTimeStandard": "beijing_standard",
        "detailLevel": "full",
    }


def _bazi_has_dayun(tool_history: list[ToolExchange]) -> bool:
    return _bazi_has_required_dayun(tool_history, require_annuals=False)


def _bazi_has_required_dayun(
    tool_history: list[ToolExchange], *, require_annuals: bool
) -> bool:
    for exchange in tool_history:
        if exchange.tool_name != "bazi" or not isinstance(exchange.tool_result, dict):
            continue
        action = str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        if action != "dayun" or exchange.tool_result.get("ok") is not True:
            continue
        if not require_annuals:
            return True
        result = exchange.tool_result.get("result")
        cycles = result.get("大运列表") if isinstance(result, dict) else None
        if isinstance(cycles, list) and any(
            isinstance(cycle, dict)
            and isinstance(cycle.get("流年列表"), list)
            and any(isinstance(annual, dict) for annual in cycle["流年列表"])
            for cycle in cycles
        ):
            return True
    return False


def _bazi_has_birth_chart(tool_history: list[ToolExchange]) -> bool:
    return any(
        exchange.tool_name == "bazi"
        and str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        == "chart"
        and isinstance(exchange.tool_result, dict)
        and exchange.tool_result.get("ok") is True
        for exchange in tool_history
    )


def _bazi_has_dayun_seed(
    tool_history: list[ToolExchange],
    user_message: str = "",
) -> bool:
    return (
        _bazi_has_birth_chart(tool_history)
        or _bazi_dayun_payload(tool_history, user_message) is not None
    )


def _explicit_bazi_gender(user_message: str) -> str | None:
    text = str(user_message or "").strip()
    male = re.search(r"(?:^|[\s,，;；:：])男(?:命)?(?=$|[\s,，。;；:：])", text)
    female = re.search(r"(?:^|[\s,，;；:：])女(?:命)?(?=$|[\s,，。;；:：])", text)
    if bool(male) == bool(female):
        return None
    return "male" if male else "female"


def _bazi_has_chart_facts(tool_history: list[ToolExchange]) -> bool:
    return any(
        exchange.tool_name == "bazi"
        and str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        in {"chart", "resolve_pillars"}
        and isinstance(exchange.tool_result, dict)
        and exchange.tool_result.get("ok") is True
        for exchange in tool_history
    )


def _bazi_has_knowledge_search(tool_history: list[ToolExchange]) -> bool:
    return any(
        exchange.tool_name == "knowledge"
        and str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        == "search"
        for exchange in tool_history
    )


def _bazi_has_case_search(tool_history: list[ToolExchange]) -> bool:
    return any(
        exchange.tool_name == "bazi_case"
        and str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        == "search"
        for exchange in tool_history
    )


def _bazi_key_shensha_years(
    tool_history: list[ToolExchange],
) -> tuple[tuple[int, str], ...]:
    key_names = {
        "羊刃", "飞刃", "血刃", "白虎", "流霞", "灾煞", "劫煞",
        "桃花", "红鸾", "天喜", "红艳煞", "孤辰", "寡宿", "驿马", "马星",
        "禄神", "金舆", "华盖", "空亡", "文昌", "文昌贵人", "天乙贵人",
        "天德贵人", "月德贵人", "太极贵人", "国印贵人", "福星贵人",
        "天医", "将星", "官符", "丧门", "吊客", "天罗", "地网",
    }
    found: list[tuple[int, str]] = []
    for exchange in tool_history:
        if exchange.tool_name != "bazi" or exchange.tool_result.get("ok") is not True:
            continue
        result = exchange.tool_result.get("result")
        cycles = result.get("大运列表") if isinstance(result, dict) else None
        if not isinstance(cycles, list):
            continue
        for cycle in cycles:
            annuals = cycle.get("流年列表") if isinstance(cycle, dict) else None
            if not isinstance(annuals, list):
                continue
            for annual in annuals:
                names = annual.get("神煞") if isinstance(annual, dict) else None
                year = annual.get("流年") if isinstance(annual, dict) else None
                if not isinstance(year, int) or isinstance(year, bool) or not isinstance(names, list):
                    continue
                for name in names:
                    normalized = str(name or "").strip()
                    item = (year, normalized)
                    if normalized in key_names and item not in found:
                        found.append(item)
    return tuple(found)


def _bazi_chart_dayun_fingerprints_match(
    tool_history: list[ToolExchange],
) -> bool:
    fingerprints: dict[str, str] = {}
    for exchange in tool_history:
        if exchange.tool_name != "bazi" or exchange.tool_result.get("ok") is not True:
            continue
        action = str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        if action not in {"chart", "dayun"}:
            continue
        fingerprint = str(exchange.tool_result.get("inputFingerprint") or "").strip()
        if fingerprint:
            fingerprints[action] = fingerprint
    if "chart" not in fingerprints or "dayun" not in fingerprints:
        return True
    return fingerprints["chart"] == fingerprints["dayun"]


def _enforce_bazi_repair_reply(request, reply):  # noqa: ANN001, ANN202
    if request.request_kind != "bazi_dayun_repair":
        return reply
    requested_name = str(request.requested_tool_name or "").strip()
    requested_payload = dict(request.requested_tool_payload or {})
    if requested_name != "bazi" or requested_payload.get("action") != "dayun":
        return reply
    return reply.model_copy(
        update={
            "final_text": None,
            "tool_name": "bazi",
            "tool_payload": requested_payload,
        }
    )
