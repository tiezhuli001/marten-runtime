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
from marten_runtime.runtime.context import assemble_runtime_context
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.finalization_contract_prompt import (
    FinalizationContractDraft,
    SessionSwitchClaimDraft,
)
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
                message=message,
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

        for _ in range(self.max_tool_rounds + 2):
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
                        else remaining_timeout_seconds(deadline_monotonic),
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
                    if finalization_details.assessment == "retryable_degraded":
                        invalid_retry_text = (reply.final_text or "").strip()
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
                            retry_triggered=True,
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


def _is_repairable_memory_schema_failure(tool_name: str | None, exc: ToolExecutionFailed) -> bool:
    if str(tool_name or "").strip() != "memory":
        return False
    return str(getattr(exc, "cause_error_code", "") or "").strip() in {
        "MEMORY_DELETE_SCOPE_REQUIRED",
        "MEMORY_WRITE_SCOPE_REQUIRED",
        "MEMORY_WRITE_TYPE_REQUIRED",
    }
