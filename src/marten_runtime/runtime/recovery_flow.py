from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal

from marten_runtime.memory.intent import (
    has_explicit_memory_delete_intent,
    has_explicit_memory_write_intent,
)
from marten_runtime.runtime.direct_rendering import (
    is_partial_fragment_aggregation,
    render_recovery_fragment,
    render_direct_tool_text,
    render_recovery_fragments_text,
)
from marten_runtime.runtime.finalization_contract_prompt import (
    CurrentSessionIdentityClaimDraft,
    FinalizationContractDraft,
    LiveRuntimeContextClaimDraft,
    LiveTimeClaimDraft,
    MemoryMutationClaimDraft,
    SessionSwitchClaimDraft,
    SpawnSubagentAcceptanceClaimDraft,
)
from marten_runtime.runtime.llm_client import (
    FinalizationEvidenceItem,
    FinalizationEvidenceLedger,
    ToolExchange,
    ToolFollowupFragment,
)
from marten_runtime.runtime.tool_followup_support import build_finalization_evidence_ledger
from marten_runtime.runtime.tool_followup_support import (
    is_intermediate_support_tool_result,
)
from marten_runtime.tools.builtins.runtime_tool import render_runtime_compaction_status_text

FinalizationAssessment = Literal["accepted", "retryable_degraded", "unrecoverable"]

@dataclass(frozen=True)
class FinalizationContractRule:
    contract_id: str
    violation_checker: Callable[..., bool]


@dataclass(frozen=True)
class FinalizationContractSpec:
    contract_id: str
    claim_getter: Callable[[FinalizationContractDraft | None], object | None]
    history_confirmer: Callable[[list[ToolExchange], object], bool]


_MISSING_STRUCTURED_CONTRACT_RULE = FinalizationContractRule(
    contract_id="structured_finalization_contract",
    violation_checker=lambda *_args, **_kwargs: True,
)


@dataclass(frozen=True)
class FinalizationAssessmentDetails:
    assessment: FinalizationAssessment
    required_evidence_items: tuple[str, ...] = ()
    missing_evidence_items: tuple[str, ...] = ()


def is_generic_tool_failure_text(text: str) -> bool:
    normalized = " ".join(str(text).split())
    return normalized in {
        "工具执行失败，请重试。",
        "工具执行失败，请稍后重试。",
        "tool execution failed, please retry.",
    }


def derive_finalization_contract_flags(
    *,
    tool_history: list[ToolExchange],
    model_request_count: int | None,
    user_message: str = "",
) -> tuple[bool, bool]:
    del model_request_count, user_message
    successful_tool_history = [
        exchange
        for exchange in tool_history
        if _is_successful_tool_result(exchange.tool_result)
    ]
    requires_result_coverage = bool(successful_tool_history)
    requires_round_trip_report = False
    return requires_result_coverage, requires_round_trip_report


def recover_successful_tool_followup_text(history: list[ToolExchange]) -> str:
    return recover_successful_tool_followup_text_with_meta(history)


def recover_successful_tool_followup_text_with_meta(
    history: list[ToolExchange],
    *,
    model_request_count: int | None = None,
    finalization_evidence_ledger: FinalizationEvidenceLedger | None = None,
) -> str:
    if not history:
        return ""
    if finalization_evidence_ledger is not None:
        ledger_text = _recover_text_from_ledger(history, finalization_evidence_ledger)
        if ledger_text:
            return ledger_text
    combined_text = render_recovery_fragments_text(
        _safe_recovery_fragments(
            history,
            model_request_count=model_request_count,
            requires_round_trip_report=(
                finalization_evidence_ledger.requires_round_trip_report
                if finalization_evidence_ledger is not None
                else None
            ),
        )
    )
    if combined_text:
        return combined_text
    latest = history[-1]
    if not isinstance(latest.tool_result, dict):
        return ""
    if latest.tool_result.get("ok") is False or latest.tool_result.get("is_error") is True:
        return ""
    return render_direct_tool_text(
        latest.tool_name,
        latest.tool_result,
        tool_payload=latest.tool_payload,
    )


def assess_finalization_text(
    history: list[ToolExchange],
    final_text: str,
    *,
    user_message: str = "",
    model_request_count: int | None = None,
    finalization_evidence_ledger: FinalizationEvidenceLedger | None = None,
    finalization_contract_draft: FinalizationContractDraft | None = None,
    enforce_structured_contract: bool = False,
) -> FinalizationAssessment:
    return assess_finalization_text_with_details(
        history,
        final_text,
        user_message=user_message,
        model_request_count=model_request_count,
        finalization_evidence_ledger=finalization_evidence_ledger,
        finalization_contract_draft=finalization_contract_draft,
        enforce_structured_contract=enforce_structured_contract,
    ).assessment


def assess_finalization_text_with_details(
    history: list[ToolExchange],
    final_text: str,
    *,
    user_message: str = "",
    model_request_count: int | None = None,
    finalization_evidence_ledger: FinalizationEvidenceLedger | None = None,
    finalization_contract_draft: FinalizationContractDraft | None = None,
    enforce_structured_contract: bool = False,
) -> FinalizationAssessmentDetails:
    normalized_text = str(final_text or "").strip()
    resolved_ledger = _resolve_finalization_evidence_ledger(
        history,
        user_message=user_message,
        model_request_count=model_request_count,
        finalization_evidence_ledger=finalization_evidence_ledger,
        finalization_contract_draft=finalization_contract_draft,
    )
    diagnostic_required_evidence = tuple(
        _diagnostic_required_evidence(
            history,
            resolved_ledger=resolved_ledger,
            model_request_count=model_request_count,
        )
    )
    missing_diagnostic_evidence = tuple(
        _missing_required_evidence(diagnostic_required_evidence, final_text)
    )
    if _first_violated_finalization_contract(
        history,
        normalized_text,
        user_message=user_message,
        finalization_contract_draft=finalization_contract_draft,
        enforce_structured_contract=enforce_structured_contract,
    ) is not None:
        return FinalizationAssessmentDetails(
            assessment=(
                "retryable_degraded"
                if history or _safe_recovery_fragments(history)
                else "unrecoverable"
            ),
            required_evidence_items=diagnostic_required_evidence,
            missing_evidence_items=missing_diagnostic_evidence,
        )
    fragments = _safe_recovery_fragments(
        history,
        model_request_count=model_request_count,
        requires_round_trip_report=resolved_ledger.requires_round_trip_report,
    )
    required_items = _required_finalization_items(
        resolved_ledger,
    )
    missing_required_items = _missing_required_evidence_items(
        required_items,
        final_text,
    )
    missing_required_evidence = tuple(
        str(item.result_summary or "").strip()
        for item in missing_required_items
        if str(item.result_summary or "").strip()
    )
    is_retryable_degraded = (
        not normalized_text
        or is_generic_tool_failure_text(final_text)
        or is_partial_fragment_aggregation(fragments, final_text)
        or bool(missing_required_items)
    )
    if normalized_text and not is_retryable_degraded:
        return FinalizationAssessmentDetails(
            assessment="accepted",
            required_evidence_items=diagnostic_required_evidence,
            missing_evidence_items=(),
        )
    has_recovery_evidence = bool(fragments) or bool(
        _recover_text_from_ledger(history, resolved_ledger)
    )
    if has_recovery_evidence and is_retryable_degraded:
        return FinalizationAssessmentDetails(
            assessment="retryable_degraded",
            required_evidence_items=diagnostic_required_evidence,
            missing_evidence_items=missing_diagnostic_evidence,
        )
    return FinalizationAssessmentDetails(
        assessment="unrecoverable",
        required_evidence_items=diagnostic_required_evidence,
        missing_evidence_items=missing_diagnostic_evidence,
    )


def _first_violated_finalization_contract(
    history: list[ToolExchange],
    final_text: str,
    *,
    user_message: str = "",
    finalization_contract_draft: FinalizationContractDraft | None = None,
    enforce_structured_contract: bool = False,
) -> FinalizationContractRule | None:
    normalized_text = " ".join(str(final_text or "").split())
    if (
        enforce_structured_contract
        and normalized_text
        and finalization_contract_draft is None
    ):
        return _MISSING_STRUCTURED_CONTRACT_RULE
    for rule in _FINALIZATION_CONTRACT_RULES:
        if rule.violation_checker(
            history,
            final_text,
            user_message=user_message,
            finalization_contract_draft=finalization_contract_draft,
        ):
            return rule
    return None


def _violates_finalization_contract_spec(
    spec: FinalizationContractSpec,
    history: list[ToolExchange],
    final_text: str,
    *,
    user_message: str = "",
    finalization_contract_draft: FinalizationContractDraft | None = None,
) -> bool:
    del final_text, user_message
    claim = spec.claim_getter(finalization_contract_draft)
    if claim is None:
        return False
    return not spec.history_confirmer(history, claim)


def _build_finalization_contract_rule(
    spec: FinalizationContractSpec,
) -> FinalizationContractRule:
    return FinalizationContractRule(
        contract_id=spec.contract_id,
        violation_checker=lambda history, final_text, *, user_message="", finalization_contract_draft=None: _violates_finalization_contract_spec(
            spec,
            history,
            final_text,
            user_message=user_message,
            finalization_contract_draft=finalization_contract_draft,
        ),
    )


def recover_tool_result_text(tool_history: list[ToolExchange]) -> str:
    if not tool_history:
        return ""
    latest = tool_history[-1]
    return render_direct_tool_text(
        latest.tool_name,
        latest.tool_result,
        tool_payload=latest.tool_payload,
    )


def is_confirmed_session_switch_reply(
    history: list[ToolExchange],
    final_text: str,
    *,
    finalization_contract_draft: FinalizationContractDraft | None = None,
) -> bool:
    claim = (
        finalization_contract_draft.session_switch
        if finalization_contract_draft is not None
        else None
    )
    if claim is None:
        return False
    return _history_confirms_session_switch(history, claim)


def _safe_recovery_fragments(
    history: list[ToolExchange],
    *,
    model_request_count: int | None = None,
    requires_round_trip_report: bool | None = None,
) -> list[ToolFollowupFragment]:
    fragments: list[ToolFollowupFragment] = []
    for index, item in enumerate(history):
        if is_intermediate_support_tool_result(history, index):
            continue
        fragment = item.recovery_fragment
        if fragment is None and _is_successful_tool_result(item.tool_result):
            text = render_direct_tool_text(
                item.tool_name,
                item.tool_result,
                tool_payload=item.tool_payload,
            )
            normalized = str(text or "").strip()
            if normalized:
                fragment = ToolFollowupFragment(
                    text=normalized,
                    source="tool_result",
                    tool_name=item.tool_name,
                )
        if fragment is None or fragment.safe_for_fallback is not True:
            continue
        fragments.append(fragment)
    loop_meta = _loop_meta_fragment(
        model_request_count=model_request_count,
        tool_call_count=len(history),
        requires_round_trip_report=requires_round_trip_report,
    )
    if loop_meta is not None:
        fragments.append(loop_meta)
    return fragments


def _resolve_finalization_evidence_ledger(
    history: list[ToolExchange],
    *,
    user_message: str,
    model_request_count: int | None,
    finalization_evidence_ledger: FinalizationEvidenceLedger | None,
    finalization_contract_draft: FinalizationContractDraft | None = None,
) -> FinalizationEvidenceLedger:
    if finalization_evidence_ledger is None:
        requires_result_coverage, requires_round_trip_report = (
            derive_finalization_contract_flags(
                tool_history=history,
                model_request_count=model_request_count,
                user_message=user_message,
            )
        )
    else:
        requires_result_coverage = bool(
            finalization_evidence_ledger.requires_result_coverage
        )
        requires_round_trip_report = bool(
            finalization_evidence_ledger.requires_round_trip_report
        )
    base_ledger = finalization_evidence_ledger or build_finalization_evidence_ledger(
        user_message=user_message,
        tool_history=history,
        model_request_count=model_request_count,
        requires_result_coverage=requires_result_coverage,
        requires_round_trip_report=requires_round_trip_report,
    )
    return _apply_finalization_draft_to_evidence_ledger(
        base_ledger,
        finalization_contract_draft=finalization_contract_draft,
    )


def _apply_finalization_draft_to_evidence_ledger(
    ledger: FinalizationEvidenceLedger,
    *,
    finalization_contract_draft: FinalizationContractDraft | None,
) -> FinalizationEvidenceLedger:
    if finalization_contract_draft is None:
        return ledger
    if _is_empty_finalization_contract_draft(finalization_contract_draft) and (
        ledger.requires_result_coverage or ledger.requires_round_trip_report
    ):
        return ledger
    requires_result_coverage = bool(finalization_contract_draft.requires_result_coverage)
    requires_round_trip_report = bool(finalization_contract_draft.requires_round_trip_report)
    if (
        ledger.requires_result_coverage == requires_result_coverage
        and ledger.requires_round_trip_report == requires_round_trip_report
        and all(
            item.required_for_user_request
            == (
                requires_result_coverage
                if item.evidence_source == "tool_result"
                else requires_round_trip_report
            )
            for item in ledger.items
        )
    ):
        return ledger
    items = [
        item.model_copy(
            update={
                "required_for_user_request": (
                    requires_result_coverage
                    if item.evidence_source == "tool_result"
                    else requires_round_trip_report
                )
            }
        )
        for item in ledger.items
    ]
    return ledger.model_copy(
        update={
            "requires_result_coverage": requires_result_coverage,
            "requires_round_trip_report": requires_round_trip_report,
            "items": items,
        }
    )


def _is_empty_finalization_contract_draft(draft: FinalizationContractDraft) -> bool:
    return (
        not draft.requires_result_coverage
        and not draft.requires_round_trip_report
        and draft.live_time is None
        and draft.live_runtime_context is None
        and draft.session_switch is None
        and draft.current_session_identity is None
        and draft.spawn_subagent_acceptance is None
        and draft.memory_write is None
        and draft.memory_delete is None
    )


def _required_finalization_items(
    ledger: FinalizationEvidenceLedger,
) -> list[FinalizationEvidenceItem]:
    return [
        item
        for item in ledger.items
        if item.required_for_user_request and str(item.result_summary or "").strip()
    ]


def _diagnostic_required_evidence(
    history: list[ToolExchange],
    *,
    resolved_ledger: FinalizationEvidenceLedger,
    model_request_count: int | None,
) -> list[str]:
    required: list[str] = []
    for fragment in _safe_recovery_fragments(
        history,
        model_request_count=model_request_count,
        requires_round_trip_report=resolved_ledger.requires_round_trip_report,
    ):
        text = render_recovery_fragment(fragment)
        normalized = str(text or "").strip()
        if not normalized or normalized in required:
            continue
        required.append(normalized)
    return required

def _normalize_requirement_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def _missing_required_evidence(
    required_evidence: list[str] | tuple[str, ...],
    final_text: str,
) -> list[str]:
    if not required_evidence:
        return []
    normalized_final_text = _normalize_requirement_text(final_text)
    if not normalized_final_text:
        return [str(text).strip() for text in required_evidence if str(text).strip()]
    return [
        text
        for text in required_evidence
        if str(text).strip()
        and not _evidence_text_is_covered(str(text), normalized_final_text)
    ]


def _missing_required_evidence_items(
    required_items: list[FinalizationEvidenceItem] | tuple[FinalizationEvidenceItem, ...],
    final_text: str,
) -> list[FinalizationEvidenceItem]:
    if not required_items:
        return []
    normalized_final_text = _normalize_requirement_text(final_text)
    if not normalized_final_text:
        return list(required_items)
    return [
        item
        for item in required_items
        if not _evidence_item_is_covered(item, normalized_final_text)
    ]


def _misses_required_evidence_coverage(
    required_evidence: list[str],
    final_text: str,
) -> bool:
    return bool(_missing_required_evidence(required_evidence, final_text))


def _evidence_text_is_covered(
    evidence_text: str,
    normalized_final_text: str,
) -> bool:
    rendered = _normalize_requirement_text(evidence_text)
    if not rendered:
        return True
    return rendered in normalized_final_text


def _evidence_item_is_covered(
    item: FinalizationEvidenceItem,
    normalized_final_text: str,
) -> bool:
    if _evidence_text_is_covered(item.result_summary, normalized_final_text):
        return True
    coverage_tokens = [
        _normalize_requirement_text(token)
        for token in item.coverage_tokens
        if _normalize_requirement_text(token)
    ]
    if coverage_tokens:
        return any(
            _coverage_token_is_present(token, normalized_final_text)
            for token in coverage_tokens
        )
    return False


def _coverage_token_is_present(token: str, normalized_final_text: str) -> bool:
    if not token:
        return False
    if re.search(r"[\u4e00-\u9fff]", token):
        return token in normalized_final_text
    pattern = re.compile(rf"(?<![a-z0-9_./:%-]){re.escape(token)}(?![a-z0-9_./:%-])")
    return bool(pattern.search(normalized_final_text))


def _is_successful_tool_result(tool_result: object) -> bool:
    if not isinstance(tool_result, dict):
        return False
    return tool_result.get("ok") is not False and tool_result.get("is_error") is not True


def _history_confirms_session_switch(
    history: list[ToolExchange],
    claim: object,
) -> bool:
    if not isinstance(claim, SessionSwitchClaimDraft):
        return False
    for item in history:
        if item.tool_name != "session":
            continue
        tool_result = item.tool_result
        if not _is_successful_tool_result(tool_result):
            continue
        if not isinstance(tool_result, dict):
            continue
        action = str(tool_result.get("action") or item.tool_payload.get("action") or "").strip()
        if action not in {"new", "resume"}:
            continue
        transition = tool_result.get("transition")
        if not isinstance(transition, dict):
            continue
        transition_mode = str(transition.get("mode") or "").strip()
        target_session_id = str(
            transition.get("target_session_id")
            or (tool_result.get("session") or {}).get("session_id")
            or item.tool_payload.get("session_id")
            or ""
        ).strip()
        claimed_session_id = str(claim.session_id or "").strip()
        if claimed_session_id and target_session_id and claimed_session_id != target_session_id:
            continue
        claim_kind = str(claim.kind or "").strip()
        if claim_kind == "new":
            if action == "new" and transition.get("binding_changed") is True:
                return True
            continue
        if claim_kind == "resume_noop":
            if action == "resume" and transition_mode == "noop_same_session":
                return True
            continue
        if claim_kind == "resume_switch":
            if (
                action == "resume"
                and transition.get("binding_changed") is True
                and transition_mode != "noop_same_session"
            ):
                return True
    return False


def _history_confirms_spawn_subagent_acceptance(
    history: list[ToolExchange],
    claim: object,
) -> bool:
    if not isinstance(claim, SpawnSubagentAcceptanceClaimDraft):
        return False
    for item in history:
        if item.tool_name != "spawn_subagent":
            continue
        tool_result = item.tool_result
        if not _is_successful_tool_result(tool_result):
            continue
        if not isinstance(tool_result, dict):
            continue
        if str(tool_result.get("status") or "").strip() != "accepted":
            continue
        actual_queue_state = str(tool_result.get("queue_state") or "").strip() or "running"
        claimed_queue_state = str(claim.queue_state or "").strip()
        if claimed_queue_state and claimed_queue_state != actual_queue_state:
            continue
        notify_on_finish = bool(item.tool_payload.get("notify_on_finish", True))
        notify_phrase = str(claim.notify_phrase or "").strip()
        if notify_phrase == "after_start":
            if not notify_on_finish or actual_queue_state != "queued":
                continue
        if notify_phrase == "after_finish":
            if not notify_on_finish or actual_queue_state != "running":
                continue
        return True
    return False


def _history_confirms_current_session_identity(
    history: list[ToolExchange],
    claim: object,
) -> bool:
    if not isinstance(claim, CurrentSessionIdentityClaimDraft):
        return False
    claimed_session_id = str(claim.session_id or "").strip()
    if not claimed_session_id:
        return False
    for item in history:
        if item.tool_name != "session":
            continue
        tool_result = item.tool_result
        if not _is_successful_tool_result(tool_result):
            continue
        if not isinstance(tool_result, dict):
            continue
        action = str(tool_result.get("action") or item.tool_payload.get("action") or "").strip()
        if action not in {"show", "new", "resume", "list"}:
            continue
        actual_session_id = _session_id_from_session_result(tool_result, item.tool_payload)
        if actual_session_id and actual_session_id == claimed_session_id:
            return True
        if action == "list":
            current_session = tool_result.get("current_session")
            if isinstance(current_session, dict):
                current_session_id = str(current_session.get("session_id") or "").strip()
                if current_session_id == claimed_session_id:
                    return True
    return False


def _history_confirms_memory_write(
    history: list[ToolExchange],
    claim: object,
) -> bool:
    if not isinstance(claim, MemoryMutationClaimDraft):
        return False
    for item in history:
        if item.tool_name != "memory":
            continue
        if not _is_successful_tool_result(item.tool_result):
            continue
        action = str(item.tool_payload.get("action") or "").strip().lower()
        if action not in {"append", "replace"}:
            continue
        if not _memory_tool_call_matches_request(item.tool_payload):
            continue
        if not _memory_claim_content_matches_tool(
            claim,
            confirmed_content=_confirmed_memory_content(item.tool_payload),
        ):
            continue
        return True
    return False


def _history_confirms_memory_delete(
    history: list[ToolExchange],
    claim: object,
) -> bool:
    if not isinstance(claim, MemoryMutationClaimDraft):
        return False
    for item in history:
        if item.tool_name != "memory":
            continue
        if not _is_successful_tool_result(item.tool_result):
            continue
        action = str(item.tool_payload.get("action") or "").strip().lower()
        if action != "delete":
            continue
        if not _memory_tool_call_matches_request(item.tool_payload):
            continue
        if not _memory_claim_content_matches_tool(
            claim,
            confirmed_content=_confirmed_memory_content(item.tool_payload),
        ):
            continue
        return True
    return False


def _history_confirms_current_time(
    history: list[ToolExchange],
    claim: object,
) -> bool:
    if not isinstance(claim, LiveTimeClaimDraft):
        return False
    observed = _latest_time_observation(history)
    if observed is None:
        return False
    facets = set(claim.facets or [])
    if not facets:
        return False
    if "time" in facets:
        if claim.hour is None or claim.minute is None:
            return False
        if (claim.hour, claim.minute) != (observed.hour, observed.minute):
            return False
        if claim.second is not None and claim.second != observed.second:
            return False
        if claim.requires_second_precision and claim.second is None:
            return False
    if "date" in facets:
        if claim.month is None or claim.day is None:
            return False
        if claim.year is not None and claim.year != observed.year:
            return False
        if (claim.month, claim.day) != (observed.month, observed.day):
            return False
    if "weekday" in facets:
        if claim.weekday is None or claim.weekday != observed.weekday:
            return False
    return True


def _history_confirms_runtime_context(
    history: list[ToolExchange],
    claim: object,
) -> bool:
    if not isinstance(claim, LiveRuntimeContextClaimDraft):
        return False
    observed = _latest_runtime_context_observation(history)
    if observed is None:
        return False
    observed_values = {
        "estimated_usage": observed.estimated_usage,
        "effective_window": observed.effective_window,
        "context_window": observed.context_window,
        "usage_percent": observed.usage_percent,
        "replay_budget": observed.replay_user_turns,
        "remaining_context": max(observed.context_window - observed.estimated_usage, 0),
        "remaining_effective": max(observed.effective_window - observed.estimated_usage, 0),
    }
    if claim.numeric_claims:
        for numeric_claim in claim.numeric_claims:
            if observed_values.get(numeric_claim.kind) != numeric_claim.value:
                return False
    if claim.status is not None and claim.status != observed.compaction_status:
        return False
    return bool(claim.numeric_claims or claim.status)


def _memory_claim_content_matches_tool(
    claim: MemoryMutationClaimDraft,
    *,
    confirmed_content: str | None,
) -> bool:
    claimed_content = str(claim.content or "").strip()
    if not claimed_content or not confirmed_content:
        return True
    normalized_claimed = _normalize_memory_compare_text(claimed_content)
    normalized_confirmed = _normalize_memory_compare_text(confirmed_content)
    if not normalized_claimed or not normalized_confirmed:
        return True
    return normalized_claimed == normalized_confirmed


@dataclass(frozen=True)
class _ObservedCurrentTime:
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    weekday: int


@dataclass(frozen=True)
class _ObservedRuntimeContext:
    estimated_usage: int
    effective_window: int
    context_window: int
    usage_percent: int
    replay_user_turns: int
    recent_tool_outcome_summary_limit: int
    compaction_status: str


def _latest_time_observation(history: list[ToolExchange]) -> _ObservedCurrentTime | None:
    for item in reversed(history):
        if item.tool_name != "time" or not _is_successful_tool_result(item.tool_result):
            continue
        if not isinstance(item.tool_result, dict):
            continue
        iso_time = str(item.tool_result.get("iso_time") or "").strip()
        if not iso_time:
            continue
        try:
            current_time = datetime.fromisoformat(iso_time)
        except ValueError:
            continue
        return _ObservedCurrentTime(
            year=current_time.year,
            month=current_time.month,
            day=current_time.day,
            hour=current_time.hour,
            minute=current_time.minute,
            second=current_time.second,
            weekday=current_time.weekday(),
        )
    return None


def _latest_runtime_context_observation(
    history: list[ToolExchange],
) -> _ObservedRuntimeContext | None:
    for item in reversed(history):
        if item.tool_name != "runtime" or not _is_successful_tool_result(item.tool_result):
            continue
        if not isinstance(item.tool_result, dict):
            tool_result = {}
        else:
            tool_result = item.tool_result
        action = str(item.tool_payload.get("action") or tool_result.get("action") or "").strip().lower()
        if action != "context_status":
            continue
        next_request = dict(tool_result.get("next_request_estimate") or {})
        effective_window = int(
            next_request.get("effective_window_tokens") or tool_result.get("effective_window") or 0
        )
        context_window = int(
            next_request.get("context_window_tokens") or tool_result.get("context_window") or 0
        )
        estimated_usage = int(
            next_request.get("input_tokens_estimate") or tool_result.get("estimated_usage") or 0
        )
        usage_percent = int(tool_result.get("usage_percent") or 0)
        replay_user_turns = int(tool_result.get("replay_user_turns") or 0)
        recent_tool_outcome_summary_limit = int(
            tool_result.get("recent_tool_outcome_summary_limit") or 0
        )
        compaction_status = _extract_runtime_status_from_result(tool_result)
        return _ObservedRuntimeContext(
            estimated_usage=estimated_usage,
            effective_window=effective_window,
            context_window=context_window,
            usage_percent=usage_percent,
            replay_user_turns=replay_user_turns,
            recent_tool_outcome_summary_limit=recent_tool_outcome_summary_limit,
            compaction_status=compaction_status,
        )
    return None


def _extract_runtime_status_from_result(tool_result: dict[str, object]) -> str:
    if str(tool_result.get("action") or "").strip() != "context_status":
        return ""
    return render_runtime_compaction_status_text(tool_result)


def _memory_tool_call_matches_request(
    tool_payload: dict[str, object],
) -> bool:
    actual_section = str(tool_payload.get("section") or "").strip().lower()
    action = str(tool_payload.get("action") or "").strip().lower()
    if action == "delete":
        return bool(actual_section) and has_explicit_memory_delete_intent(tool_payload)
    if action not in {"append", "replace"}:
        return False
    actual_content = str(tool_payload.get("content") or "").strip()
    return bool(actual_section) and bool(actual_content) and has_explicit_memory_write_intent(tool_payload)


def _confirmed_memory_content(
    tool_payload: dict[str, object],
) -> str | None:
    actual_content = str(tool_payload.get("content") or "").strip()
    return actual_content or None


def _normalize_memory_compare_text(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text or "").lower())
_FINALIZATION_CONTRACT_SPECS = (
    FinalizationContractSpec(
        "session_switch",
        lambda draft: draft.session_switch if draft is not None else None,
        _history_confirms_session_switch,
    ),
    FinalizationContractSpec(
        "current_session_identity",
        lambda draft: draft.current_session_identity if draft is not None else None,
        _history_confirms_current_session_identity,
    ),
    FinalizationContractSpec(
        "memory_write",
        lambda draft: draft.memory_write if draft is not None else None,
        _history_confirms_memory_write,
    ),
    FinalizationContractSpec(
        "memory_delete",
        lambda draft: draft.memory_delete if draft is not None else None,
        _history_confirms_memory_delete,
    ),
    FinalizationContractSpec(
        "live_time",
        lambda draft: draft.live_time if draft is not None else None,
        _history_confirms_current_time,
    ),
    FinalizationContractSpec(
        "live_runtime_context",
        lambda draft: draft.live_runtime_context if draft is not None else None,
        _history_confirms_runtime_context,
    ),
    FinalizationContractSpec(
        "spawn_subagent_acceptance",
        lambda draft: draft.spawn_subagent_acceptance if draft is not None else None,
        _history_confirms_spawn_subagent_acceptance,
    ),
)


_FINALIZATION_CONTRACT_RULES = tuple(
    _build_finalization_contract_rule(spec) for spec in _FINALIZATION_CONTRACT_SPECS
)


def _session_id_from_session_result(
    tool_result: dict[str, object],
    tool_payload: dict[str, object],
) -> str:
    session = tool_result.get("session")
    if isinstance(session, dict):
        session_id = str(session.get("session_id") or "").strip()
        if session_id:
            return session_id
    transition = tool_result.get("transition")
    if isinstance(transition, dict):
        target_session_id = str(transition.get("target_session_id") or "").strip()
        if target_session_id:
            return target_session_id
    return str(tool_payload.get("session_id") or "").strip()


def _loop_meta_fragment(
    *,
    model_request_count: int | None,
    tool_call_count: int,
    requires_round_trip_report: bool | None = None,
) -> ToolFollowupFragment | None:
    if model_request_count is None:
        return None
    if requires_round_trip_report is False:
        return None
    if model_request_count < 3 or tool_call_count < 2:
        return None
    return ToolFollowupFragment(
        text=(
            f"本次请求共发生 {model_request_count} 次模型请求和 {tool_call_count} 次工具调用，"
            "属于多次模型/工具往返。"
        ),
        source="loop_meta",
        safe_for_fallback=True,
    )


def _recover_text_from_ledger(
    history: list[ToolExchange],
    ledger: FinalizationEvidenceLedger,
) -> str:
    round_trip_summary = _round_trip_summary_from_ledger(ledger)
    required_items = [
        item for item in ledger.items if item.required_for_user_request and str(item.result_summary or "").strip()
    ]
    if required_items:
        recovered = [str(item.result_summary).strip() for item in required_items]
        if round_trip_summary and round_trip_summary not in recovered:
            recovered.append(round_trip_summary)
        return "\n\n".join(recovered)
    successful_items: list[str] = []
    for item in ledger.items:
        if item.evidence_source == "loop_meta":
            continue
        if is_intermediate_support_tool_result(history, item.ordinal - 1):
            continue
        if not _ledger_item_maps_to_successful_tool(item.ordinal, history):
            continue
        summary = str(item.result_summary or "").strip()
        if summary:
            successful_items.append(summary)
    if round_trip_summary and round_trip_summary not in successful_items:
        successful_items.append(round_trip_summary)
    return "\n\n".join(successful_items)


def _round_trip_summary_from_ledger(ledger: FinalizationEvidenceLedger) -> str | None:
    if not ledger.requires_round_trip_report:
        return None
    for item in ledger.items:
        if item.evidence_source != "loop_meta":
            continue
        summary = str(item.result_summary or "").strip()
        if summary:
            return summary
    fragment = _loop_meta_fragment(
        model_request_count=ledger.model_request_count,
        tool_call_count=ledger.tool_call_count,
        requires_round_trip_report=True,
    )
    if fragment is None:
        return None
    return str(fragment.text or "").strip() or None


def _ledger_item_maps_to_successful_tool(
    ordinal: int,
    history: list[ToolExchange],
) -> bool:
    if ordinal < 1 or ordinal > len(history):
        return False
    return _is_successful_tool_result(history[ordinal - 1].tool_result)
