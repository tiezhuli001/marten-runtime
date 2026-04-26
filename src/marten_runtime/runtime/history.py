from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from marten_runtime.runtime.usage_models import NormalizedUsage, ProviderCallDiagnostics
from marten_runtime.session.tool_outcome_summary import ToolOutcomeSummary

FINALIZATION_DIAGNOSTIC_ITEM_LIMIT = 3
FINALIZATION_DIAGNOSTIC_TEXT_LIMIT = 280


class CompactionDiagnostics(BaseModel):
    decision: str = "none"
    effective_window_tokens: int = 0
    advisory_threshold_tokens: int = 0
    proactive_threshold_tokens: int = 0
    estimated_input_tokens_before: int = 0
    estimated_input_tokens_after: int = 0
    used_compacted_context: bool = False
    compacted_context_id: str | None = None


class RunTimings(BaseModel):
    llm_first_ms: int = 0
    tool_ms: int = 0
    llm_second_ms: int = 0
    outbound_ms: int = 0
    total_ms: int = 0


class RunQueueDiagnostics(BaseModel):
    queue_depth_at_enqueue: int = 1
    queue_wait_ms: int = 0
    waited_in_lane: bool = False


class ExternalObservabilityRefs(BaseModel):
    langfuse_trace_id: str | None = None
    langfuse_url: str | None = None


class FinalizationDiagnostics(BaseModel):
    assessment: str | None = None
    request_kind: str | None = None
    required_evidence_count: int = 0
    missing_evidence_items: list[str] = Field(default_factory=list)
    retry_triggered: bool = False
    recovered_from_fragments: bool = False
    invalid_final_text: str | None = None


class RunRecord(BaseModel):
    run_id: str
    trace_id: str
    session_id: str
    job_id: str | None = None
    config_snapshot_id: str = "cfg_bootstrap"
    bootstrap_manifest_id: str = "boot_default"
    trigger_kind: str = "interactive"
    status: str = "pending"
    parent_run_id: str | None = None
    context_snapshot_id: str | None = None
    skill_snapshot_id: str = "skill_default"
    tool_snapshot_id: str = "tool_default"
    started_at: datetime
    finished_at: datetime | None = None
    delivery_status: str = "none"
    error_code: str | None = None
    provider_ref: str | None = None
    attempted_profiles: list[str] = Field(default_factory=list)
    attempted_providers: list[str] = Field(default_factory=list)
    failover_skipped_profiles: list[dict[str, str]] = Field(default_factory=list)
    failover_trigger: str | None = None
    failover_stage: str | None = None
    final_provider_ref: str | None = None
    contract_repair_triggered: bool = False
    contract_repair_reason: str | None = None
    contract_repair_attempt_count: int = 0
    contract_repair_outcome: str | None = None
    contract_repair_selected_tool: str | None = None
    contract_repair_provider_ref: str | None = None
    llm_request_count: int = 0
    preflight_input_tokens_estimate: int = 0
    preflight_estimator_kind: str = "rough"
    initial_preflight_input_tokens_estimate: int = 0
    peak_preflight_input_tokens_estimate: int = 0
    peak_preflight_stage: str = "initial_request"
    actual_input_tokens: int | None = None
    actual_output_tokens: int | None = None
    actual_total_tokens: int | None = None
    actual_cumulative_input_tokens: int = 0
    actual_cumulative_output_tokens: int = 0
    actual_cumulative_total_tokens: int = 0
    actual_peak_input_tokens: int | None = None
    actual_peak_output_tokens: int | None = None
    actual_peak_total_tokens: int | None = None
    actual_peak_stage: str | None = None
    latest_actual_usage: NormalizedUsage | None = None
    provider_calls: list[dict[str, object]] = Field(default_factory=list)
    tool_calls: list[dict[str, object]] = Field(default_factory=list)
    tool_outcome_summaries: list[ToolOutcomeSummary] = Field(default_factory=list)
    timings: RunTimings = Field(default_factory=RunTimings)
    queue: RunQueueDiagnostics = Field(default_factory=RunQueueDiagnostics)
    compaction: CompactionDiagnostics = Field(default_factory=CompactionDiagnostics)
    external_observability: ExternalObservabilityRefs = Field(default_factory=ExternalObservabilityRefs)
    finalization: FinalizationDiagnostics = Field(default_factory=FinalizationDiagnostics)


class InMemoryRunHistory:
    def __init__(self) -> None:
        self._items: dict[str, RunRecord] = {}

    def start(
        self,
        session_id: str,
        trace_id: str,
        config_snapshot_id: str,
        bootstrap_manifest_id: str,
        *,
        context_snapshot_id: str | None = None,
        skill_snapshot_id: str = "skill_default",
        tool_snapshot_id: str = "tool_default",
        parent_run_id: str | None = None,
    ) -> RunRecord:
        record = RunRecord(
            run_id=f"run_{uuid4().hex[:8]}",
            trace_id=trace_id,
            session_id=session_id,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id=bootstrap_manifest_id,
            context_snapshot_id=context_snapshot_id,
            skill_snapshot_id=skill_snapshot_id,
            tool_snapshot_id=tool_snapshot_id,
            parent_run_id=parent_run_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        self._items[record.run_id] = record
        return record

    def finish(self, run_id: str, delivery_status: str) -> RunRecord:
        record = self._items[run_id]
        record.status = "succeeded"
        record.delivery_status = delivery_status
        record.finished_at = datetime.now(timezone.utc)
        return record

    def fail(self, run_id: str, error_code: str, delivery_status: str = "error") -> RunRecord:
        record = self._items[run_id]
        record.status = "failed"
        record.error_code = error_code
        record.delivery_status = delivery_status
        record.finished_at = datetime.now(timezone.utc)
        return record

    def set_failover_state(
        self,
        run_id: str,
        *,
        provider_ref: str | None,
        attempted_profiles: list[str],
        attempted_providers: list[str],
        failover_trigger: str | None,
        failover_stage: str | None,
        final_provider_ref: str | None,
    ) -> None:
        record = self._items[run_id]
        record.provider_ref = provider_ref
        record.attempted_profiles = list(attempted_profiles)
        record.attempted_providers = list(attempted_providers)
        record.failover_trigger = failover_trigger
        record.failover_stage = failover_stage
        record.final_provider_ref = final_provider_ref

    def record_failover_skipped_profile(
        self,
        run_id: str,
        *,
        profile_name: str,
        reason: str,
    ) -> None:
        record = self._items[run_id]
        record.failover_skipped_profiles.append(
            {
                "profile_name": profile_name,
                "reason": reason,
            }
        )

    def set_contract_repair_state(
        self,
        run_id: str,
        *,
        triggered: bool | None = None,
        reason: str | None = None,
        attempt_count: int | None = None,
        outcome: str | None = None,
        selected_tool: str | None = None,
        provider_ref: str | None = None,
    ) -> None:
        record = self._items[run_id]
        if triggered is not None:
            record.contract_repair_triggered = triggered
        if reason is not None:
            record.contract_repair_reason = reason
        if attempt_count is not None:
            record.contract_repair_attempt_count = attempt_count
        if outcome is not None:
            record.contract_repair_outcome = outcome
        if selected_tool is not None or record.contract_repair_selected_tool is not None:
            record.contract_repair_selected_tool = selected_tool
        if provider_ref is not None:
            record.contract_repair_provider_ref = provider_ref

    def get(self, run_id: str) -> RunRecord:
        return self._items[run_id]

    def list_runs(self) -> list[RunRecord]:
        return list(self._items.values())

    def record_tool_call(
        self,
        run_id: str,
        *,
        tool_name: str,
        tool_payload: dict,
        tool_result: dict,
    ) -> None:
        record = self._items[run_id]
        record.tool_calls.append(
            {
                "tool_name": tool_name,
                "tool_payload": tool_payload,
                "tool_result": tool_result,
            }
        )

    def record_provider_call(
        self,
        run_id: str,
        *,
        stage: str,
        diagnostics: ProviderCallDiagnostics,
    ) -> None:
        record = self._items[run_id]
        record.provider_calls.append(
            {
                "stage": stage,
                **diagnostics.model_dump(mode="json"),
            }
        )

    def append_tool_outcome_summary(self, run_id: str, summary: ToolOutcomeSummary) -> None:
        self._items[run_id].tool_outcome_summaries.append(summary)

    def set_llm_request_count(self, run_id: str, count: int) -> None:
        self._items[run_id].llm_request_count = count

    def set_preflight_usage(
        self,
        run_id: str,
        *,
        input_tokens_estimate: int,
        estimator_kind: str,
        peak_input_tokens_estimate: int | None = None,
        peak_stage: str | None = None,
    ) -> None:
        record = self._items[run_id]
        record.preflight_input_tokens_estimate = input_tokens_estimate
        record.preflight_estimator_kind = estimator_kind
        record.initial_preflight_input_tokens_estimate = input_tokens_estimate
        record.peak_preflight_input_tokens_estimate = (
            peak_input_tokens_estimate
            if peak_input_tokens_estimate is not None
            else max(record.peak_preflight_input_tokens_estimate, input_tokens_estimate)
        )
        record.peak_preflight_stage = peak_stage or "initial_request"

    def update_peak_preflight_usage(
        self,
        run_id: str,
        *,
        input_tokens_estimate: int,
        stage: str,
    ) -> None:
        record = self._items[run_id]
        if input_tokens_estimate >= record.peak_preflight_input_tokens_estimate:
            record.peak_preflight_input_tokens_estimate = input_tokens_estimate
            record.peak_preflight_stage = stage

    def set_actual_usage(self, run_id: str, usage: NormalizedUsage, *, stage: str | None = None) -> None:
        record = self._items[run_id]
        record.latest_actual_usage = usage
        record.actual_input_tokens = usage.input_tokens
        record.actual_output_tokens = usage.output_tokens
        record.actual_total_tokens = usage.total_tokens
        record.actual_cumulative_input_tokens += usage.input_tokens
        record.actual_cumulative_output_tokens += usage.output_tokens
        record.actual_cumulative_total_tokens += usage.total_tokens
        if record.actual_peak_total_tokens is None or usage.total_tokens >= record.actual_peak_total_tokens:
            record.actual_peak_input_tokens = usage.input_tokens
            record.actual_peak_output_tokens = usage.output_tokens
            record.actual_peak_total_tokens = usage.total_tokens
            record.actual_peak_stage = stage or ("llm_second" if record.llm_request_count > 1 else "llm_first")

    def set_stage_timing(self, run_id: str, *, stage: str, elapsed_ms: int) -> None:
        record = self._items[run_id]
        if stage == "llm_first":
            record.timings.llm_first_ms = elapsed_ms
            return
        if stage == "tool":
            record.timings.tool_ms = elapsed_ms
            return
        if stage == "llm_second":
            record.timings.llm_second_ms = elapsed_ms
            return
        raise KeyError(stage)

    def add_outbound_timing(self, run_id: str, *, elapsed_ms: int) -> None:
        record = self._items[run_id]
        record.timings.outbound_ms += elapsed_ms
        record.timings.total_ms += elapsed_ms

    def finalize_total_timing(self, run_id: str, *, elapsed_ms: int) -> None:
        self._items[run_id].timings.total_ms = elapsed_ms

    def set_queue_diagnostics(
        self,
        run_id: str,
        *,
        queue_depth_at_enqueue: int,
        queue_wait_ms: int,
    ) -> None:
        record = self._items.get(run_id)
        if record is None:
            return
        record.queue = RunQueueDiagnostics(
            queue_depth_at_enqueue=max(1, int(queue_depth_at_enqueue)),
            queue_wait_ms=max(0, int(queue_wait_ms)),
            waited_in_lane=bool(queue_depth_at_enqueue > 1 or queue_wait_ms > 0),
        )

    def set_compaction(self, run_id: str, diagnostics: CompactionDiagnostics) -> None:
        self._items[run_id].compaction = diagnostics

    def set_external_observability_refs(
        self,
        run_id: str,
        *,
        langfuse_trace_id: str | None = None,
        langfuse_url: str | None = None,
    ) -> None:
        record = self._items[run_id]
        record.external_observability = ExternalObservabilityRefs(
            langfuse_trace_id=langfuse_trace_id,
            langfuse_url=langfuse_url,
        )

    def set_finalization_state(
        self,
        run_id: str,
        *,
        assessment: str | None = None,
        request_kind: str | None = None,
        required_evidence_count: int | None = None,
        missing_evidence_items: list[str] | None = None,
        retry_triggered: bool | None = None,
        recovered_from_fragments: bool | None = None,
        invalid_final_text: str | None = None,
    ) -> None:
        record = self._items[run_id]
        if assessment is not None:
            record.finalization.assessment = _normalize_diagnostic_text(assessment)
        if request_kind is not None:
            record.finalization.request_kind = _normalize_diagnostic_text(request_kind)
        if required_evidence_count is not None:
            record.finalization.required_evidence_count = max(0, int(required_evidence_count))
        if missing_evidence_items is not None:
            record.finalization.missing_evidence_items = _normalize_diagnostic_items(
                missing_evidence_items
            )
        if retry_triggered is not None:
            record.finalization.retry_triggered = bool(retry_triggered)
        if recovered_from_fragments is not None:
            record.finalization.recovered_from_fragments = bool(recovered_from_fragments)
        if invalid_final_text is not None:
            record.finalization.invalid_final_text = _normalize_diagnostic_text(
                invalid_final_text
            )


def _normalize_diagnostic_items(items: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in items[:FINALIZATION_DIAGNOSTIC_ITEM_LIMIT]:
        text = _normalize_diagnostic_text(item)
        if not text:
            continue
        normalized.append(text)
    return normalized


def _normalize_diagnostic_text(text: str | None) -> str | None:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return None
    if len(normalized) <= FINALIZATION_DIAGNOSTIC_TEXT_LIMIT:
        return normalized
    return f"{normalized[: FINALIZATION_DIAGNOSTIC_TEXT_LIMIT - 1].rstrip()}…"
