from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import (
    FinalizationEvidenceLedger,
    LLMReply,
    LLMRequest,
    ToolExchange,
)
from marten_runtime.runtime.recovery_flow import (
    FinalizationAssessmentDetails,
    derive_finalization_contract_flags,
)
from marten_runtime.runtime.tool_followup_support import (
    build_finalization_evidence_ledger,
    is_intermediate_support_tool_result,
)


def build_contract_repair_request(
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


def is_duplicate_spawn_subagent_followup(
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
    if str(latest.tool_result.get("status") or "").strip() != "accepted":
        return False
    latest_key = spawn_subagent_duplicate_key(latest.tool_payload)
    reply_key = spawn_subagent_duplicate_key(reply.tool_payload)
    if latest_key and reply_key:
        return latest_key == reply_key
    return True


def spawn_subagent_duplicate_key(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()
    values: list[str] = []
    for key in ("task", "label", "tool_profile", "context_mode", "agent_id"):
        values.append(" ".join(str(payload.get(key) or "").split()).strip().lower())
    if not any(values):
        return ()
    return tuple(values)


def build_current_turn_evidence_ledger(
    *,
    user_message: str,
    tool_history: list[ToolExchange],
    model_request_count: int,
    base_ledger: FinalizationEvidenceLedger | None = None,
):
    if base_ledger is not None:
        requires_result_coverage = bool(base_ledger.requires_result_coverage)
        requires_round_trip_report = bool(base_ledger.requires_round_trip_report)
    else:
        requires_result_coverage, requires_round_trip_report = (
            derive_finalization_contract_flags(
                tool_history=tool_history,
                model_request_count=model_request_count,
                user_message=user_message,
            )
        )
    return build_finalization_evidence_ledger(
        user_message=user_message,
        tool_history=tool_history,
        model_request_count=model_request_count,
        requires_result_coverage=requires_result_coverage,
        requires_round_trip_report=requires_round_trip_report,
    )


def deprioritize_tool_evidence_requirements(
    ledger: FinalizationEvidenceLedger,
) -> FinalizationEvidenceLedger:
    return ledger.model_copy(
        update={
            "requires_result_coverage": False,
            "requires_round_trip_report": False,
            "items": [],
        }
    )


def tool_result_is_failure(tool_result: object) -> bool:
    return (
        isinstance(tool_result, dict)
        and (tool_result.get("ok") is False or tool_result.get("is_error") is True)
    )


def tool_history_has_failure(tool_history: list[ToolExchange]) -> bool:
    return any(tool_result_is_failure(item.tool_result) for item in tool_history)


def latest_tool_failure_text(tool_history: list[ToolExchange]) -> str:
    for item in reversed(tool_history):
        tool_result = item.tool_result
        if not tool_result_is_failure(tool_result):
            continue
        if not isinstance(tool_result, dict):
            continue
        return str(
            tool_result.get("error_text")
            or tool_result.get("error_code")
            or "工具执行失败，请重试。"
        ).strip()
    return ""


def require_latest_failed_tool_evidence(
    ledger: FinalizationEvidenceLedger,
    tool_history: list[ToolExchange],
) -> FinalizationEvidenceLedger:
    failed_ordinal = 0
    for index, item in enumerate(tool_history, start=1):
        if tool_result_is_failure(item.tool_result):
            failed_ordinal = index
    if failed_ordinal <= 0:
        return ledger
    return ledger.model_copy(
        update={
            "requires_result_coverage": True,
            "items": [
                item.model_copy(update={"required_for_user_request": True})
                if item.ordinal == failed_ordinal
                else item
                for item in ledger.items
            ],
        }
    )


def final_text_masks_failed_tool_result(
    tool_history: list[ToolExchange],
    final_text: str,
    finalization_evidence_ledger: FinalizationEvidenceLedger,
) -> bool:
    if not tool_history_has_failure(tool_history):
        return False
    normalized_final = " ".join(str(final_text or "").split()).strip()
    if not normalized_final:
        return False
    normalized_final = normalized_final.casefold()
    for item in finalization_evidence_ledger.items:
        if item.evidence_source != "tool_result":
            continue
        index = item.ordinal - 1
        if not is_intermediate_support_tool_result(tool_history, index):
            continue
        evidence = " ".join(str(item.result_summary or "").split()).strip().casefold()
        if evidence and (
            evidence in normalized_final or normalized_final in evidence
        ):
            return True
    return False


def failed_tool_details(
    tool_history: list[ToolExchange],
) -> FinalizationAssessmentDetails:
    latest_failure = latest_tool_failure_text(tool_history) or "工具执行失败，请重试。"
    return FinalizationAssessmentDetails(
        assessment="retryable_degraded",
        required_evidence_items=(latest_failure,),
        missing_evidence_items=(latest_failure,),
    )


def record_finalization_diagnostics(
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
