from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from marten_runtime.runtime.direct_rendering import (
    is_partial_fragment_aggregation,
    render_recovery_fragment,
    render_direct_tool_text,
    render_recovery_fragments_text,
)
from marten_runtime.runtime.llm_client import (
    FinalizationEvidenceLedger,
    ToolExchange,
    ToolFollowupFragment,
)
from marten_runtime.runtime.tool_followup_support import build_finalization_evidence_ledger

FinalizationAssessment = Literal["accepted", "retryable_degraded", "unrecoverable"]


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


def derive_finalization_contract_flags(user_message: str) -> tuple[bool, bool]:
    return (
        _explicitly_requires_current_turn_result_coverage(user_message),
        _explicitly_requires_round_trip_report(user_message),
    )


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
) -> FinalizationAssessment:
    return assess_finalization_text_with_details(
        history,
        final_text,
        user_message=user_message,
        model_request_count=model_request_count,
        finalization_evidence_ledger=finalization_evidence_ledger,
    ).assessment


def assess_finalization_text_with_details(
    history: list[ToolExchange],
    final_text: str,
    *,
    user_message: str = "",
    model_request_count: int | None = None,
    finalization_evidence_ledger: FinalizationEvidenceLedger | None = None,
) -> FinalizationAssessmentDetails:
    normalized_text = str(final_text or "").strip()
    resolved_ledger = _resolve_finalization_evidence_ledger(
        history,
        user_message=user_message,
        model_request_count=model_request_count,
        finalization_evidence_ledger=finalization_evidence_ledger,
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
    if violates_session_switch_contract(history, normalized_text):
        return FinalizationAssessmentDetails(
            assessment=(
                "retryable_degraded" if _safe_recovery_fragments(history) else "unrecoverable"
            ),
            required_evidence_items=diagnostic_required_evidence,
            missing_evidence_items=missing_diagnostic_evidence,
        )
    if violates_current_session_identity_contract(history, normalized_text):
        return FinalizationAssessmentDetails(
            assessment=(
                "retryable_degraded" if _safe_recovery_fragments(history) else "unrecoverable"
            ),
            required_evidence_items=diagnostic_required_evidence,
            missing_evidence_items=missing_diagnostic_evidence,
        )
    if violates_spawn_subagent_acceptance_contract(history, normalized_text):
        return FinalizationAssessmentDetails(
            assessment=(
                "retryable_degraded" if _safe_recovery_fragments(history) else "unrecoverable"
            ),
            required_evidence_items=diagnostic_required_evidence,
            missing_evidence_items=missing_diagnostic_evidence,
        )
    fragments = _safe_recovery_fragments(
        history,
        model_request_count=model_request_count,
        requires_round_trip_report=resolved_ledger.requires_round_trip_report,
    )
    required_evidence = _required_finalization_evidence(
        resolved_ledger,
    )
    missing_required_evidence = _missing_required_evidence(required_evidence, final_text)
    has_multi_step_diagnostic_gap = (
        len(diagnostic_required_evidence) >= 2
        and 0 < len(missing_diagnostic_evidence) < len(diagnostic_required_evidence)
    )
    is_retryable_degraded = (
        not normalized_text
        or is_generic_tool_failure_text(final_text)
        or is_partial_fragment_aggregation(fragments, final_text)
        or has_multi_step_diagnostic_gap
        or bool(missing_required_evidence)
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


def recover_tool_result_text(tool_history: list[ToolExchange]) -> str:
    if not tool_history:
        return ""
    latest = tool_history[-1]
    return render_direct_tool_text(
        latest.tool_name,
        latest.tool_result,
        tool_payload=latest.tool_payload,
    )


def violates_session_switch_contract(
    history: list[ToolExchange],
    final_text: str,
) -> bool:
    normalized_text = " ".join(str(final_text or "").split())
    if not normalized_text:
        return False
    if not _claims_session_switch_success(normalized_text):
        return False
    return not _history_confirms_session_switch(history, normalized_text)


def is_confirmed_session_switch_reply(
    history: list[ToolExchange],
    final_text: str,
) -> bool:
    normalized_text = " ".join(str(final_text or "").split())
    if not normalized_text:
        return False
    if not _claims_session_switch_success(normalized_text):
        return False
    return _history_confirms_session_switch(history, normalized_text)


def violates_spawn_subagent_acceptance_contract(
    history: list[ToolExchange],
    final_text: str,
) -> bool:
    normalized_text = " ".join(str(final_text or "").split())
    if not normalized_text:
        return False
    if not _claims_spawn_subagent_acceptance(normalized_text):
        return False
    return not _history_confirms_spawn_subagent_acceptance(history, normalized_text)


def violates_current_session_identity_contract(
    history: list[ToolExchange],
    final_text: str,
) -> bool:
    normalized_text = " ".join(str(final_text or "").split())
    if not normalized_text:
        return False
    if not _claims_current_session_identity(normalized_text):
        return False
    return not _history_confirms_current_session_identity(history, normalized_text)


def _safe_recovery_fragments(
    history: list[ToolExchange],
    *,
    model_request_count: int | None = None,
    requires_round_trip_report: bool | None = None,
) -> list[ToolFollowupFragment]:
    fragments: list[ToolFollowupFragment] = []
    for item in history:
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
) -> FinalizationEvidenceLedger:
    if finalization_evidence_ledger is not None:
        return finalization_evidence_ledger
    return build_finalization_evidence_ledger(
        user_message=user_message,
        tool_history=history,
        model_request_count=model_request_count,
        requires_result_coverage=_explicitly_requires_current_turn_result_coverage(
            user_message
        ),
        requires_round_trip_report=_explicitly_requires_round_trip_report(user_message),
    )


def _required_finalization_evidence(
    ledger: FinalizationEvidenceLedger,
) -> list[str]:
    return [
        str(item.result_summary or "").strip()
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


def _explicitly_requires_current_turn_result_coverage(user_message: str) -> bool:
    normalized = _normalize_requirement_text(user_message)
    if not normalized:
        return False
    summary_terms = ("总结", "汇总", "概括", "归纳")
    chain_terms = ("链路", "按顺序", "依次", "逐步", "每一步", "各步", "每个成功工具", "关键结果")
    return any(term in normalized for term in summary_terms) and any(
        term in normalized for term in chain_terms
    )


def _explicitly_requires_round_trip_report(user_message: str) -> bool:
    normalized = _normalize_requirement_text(user_message)
    if not normalized:
        return False
    return any(
        term in normalized
        for term in (
            "往返",
            "模型请求",
            "工具调用",
            "多次模型/工具",
            "多轮",
        )
    )


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
    if rendered in normalized_final_text:
        return True
    anchors = _coverage_anchors(rendered)
    if not anchors:
        return any(alias in normalized_final_text for alias in _coverage_aliases(rendered))
    if any(anchor in normalized_final_text for anchor in anchors):
        return True
    return any(alias in normalized_final_text for alias in _coverage_aliases(rendered))


_COVERAGE_TOKEN_RE = re.compile(
    r"sess_[a-z0-9_-]+"
    r"|[a-z][a-z0-9_./:-]{2,}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}:\d{2}(?::\d{2})?"
    r"|\d+/\d+"
    r"|\d+%"
    r"|[\u4e00-\u9fff]{2,}"
)
_COVERAGE_STOPWORDS = {
    "当前",
    "现在",
    "这轮",
    "这次请求",
    "已经",
    "已按顺序完成",
    "详情",
    "显示",
    "预计",
    "占用",
    "服务",
    "工具",
    "调用",
    "结果",
    "说明",
    "总结",
    "链路",
    "本次请求共发生",
    "次模型请求和",
    "次工具调用",
    "属于多次模型",
}


def _coverage_anchors(text: str) -> list[str]:
    anchors: list[str] = []
    for token in _COVERAGE_TOKEN_RE.findall(text):
        normalized = token.strip().lower()
        if len(normalized) < 2:
            continue
        if normalized in _COVERAGE_STOPWORDS:
            continue
        if normalized.isdigit() and len(normalized) < 2:
            continue
        anchors.append(normalized)
    deduped: list[str] = []
    for token in anchors:
        if token in deduped:
            continue
        deduped.append(token)
    return deduped


def _coverage_aliases(text: str) -> list[str]:
    aliases: list[str] = []
    if any(term in text for term in ("北京时间", "当前时间", "utc", "iso_time")):
        aliases.extend(["当前时间", "time"])
    if any(term in text for term in ("上下文", "tokens", "窗口", "context_status")):
        aliases.extend(["上下文状态", "当前上下文", "runtime", "context_status"])
    if "mcp" in text:
        aliases.extend(["mcp", "mcp 服务", "github mcp"])
    deduped: list[str] = []
    for token in aliases:
        normalized = token.strip().lower()
        if not normalized or normalized in deduped:
            continue
        deduped.append(normalized)
    return deduped


def _is_successful_tool_result(tool_result: object) -> bool:
    if not isinstance(tool_result, dict):
        return False
    return tool_result.get("ok") is not False and tool_result.get("is_error") is not True


def _claims_session_switch_success(text: str) -> bool:
    return _parse_session_switch_claim(text) is not None


def _claims_spawn_subagent_acceptance(text: str) -> bool:
    return _parse_spawn_subagent_acceptance_claim(text) is not None


def _claims_current_session_identity(text: str) -> bool:
    return _parse_current_session_identity_claim(text) is not None


def _history_confirms_session_switch(
    history: list[ToolExchange],
    final_text: str,
) -> bool:
    claim = _parse_session_switch_claim(final_text)
    if claim is None:
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
        claimed_session_id = str(claim.get("session_id") or "").strip()
        if claimed_session_id and target_session_id and claimed_session_id != target_session_id:
            continue
        claim_kind = str(claim.get("kind") or "").strip()
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
    final_text: str,
) -> bool:
    claim = _parse_spawn_subagent_acceptance_claim(final_text)
    if claim is None:
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
        claimed_queue_state = str(claim.get("queue_state") or "").strip()
        if claimed_queue_state and claimed_queue_state != actual_queue_state:
            continue
        notify_on_finish = bool(item.tool_payload.get("notify_on_finish", True))
        notify_phrase = str(claim.get("notify_phrase") or "").strip()
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
    final_text: str,
) -> bool:
    claim = _parse_current_session_identity_claim(final_text)
    if claim is None:
        return False
    claimed_session_id = str(claim.get("session_id") or "").strip()
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


_SESSION_ID_RE = re.compile(r"`?(sess_[A-Za-z0-9_-]+)`?")


def _extract_session_id(text: str) -> str | None:
    match = _SESSION_ID_RE.search(str(text or ""))
    if match is None:
        return None
    return str(match.group(1) or "").strip() or None


def _parse_session_switch_claim(text: str) -> dict[str, str | None] | None:
    normalized = " ".join(str(text or "").split())
    if "当前已在会话" in normalized:
        return {
            "kind": "resume_noop",
            "session_id": _extract_session_id(normalized),
        }
    if "已切换到新会话" in normalized:
        return {
            "kind": "new",
            "session_id": _extract_session_id(normalized),
        }
    if (
        "已恢复旧会话" in normalized
        or "已恢复会话" in normalized
        or "已恢复到会话" in normalized
    ):
        return {
            "kind": "resume_switch",
            "session_id": _extract_session_id(normalized),
        }
    if "已切换到已有会话" in normalized or "已切换到会话" in normalized:
        return {
            "kind": "resume_switch",
            "session_id": _extract_session_id(normalized),
        }
    return None


def _parse_spawn_subagent_acceptance_claim(text: str) -> dict[str, str | None] | None:
    normalized = " ".join(str(text or "").split())
    if "已受理" not in normalized:
        return None
    if "子 agent" not in normalized and "后台执行" not in normalized and "进入队列" not in normalized:
        return None
    queue_state: str | None = None
    if "进入队列" in normalized:
        queue_state = "queued"
    elif "后台执行" in normalized:
        queue_state = "running"
    notify_phrase: str | None = None
    if "开始后会通知你结果" in normalized:
        notify_phrase = "after_start"
    elif "完成后会通知你结果" in normalized:
        notify_phrase = "after_finish"
    return {
        "queue_state": queue_state,
        "notify_phrase": notify_phrase,
    }


def _parse_current_session_identity_claim(text: str) -> dict[str, str | None] | None:
    normalized = " ".join(str(text or "").split())
    if "当前会话" not in normalized:
        return None
    if "session_id" not in normalized and "会话 id" not in normalized and "会话id" not in normalized:
        return None
    session_id = _extract_session_id(normalized)
    if not session_id:
        return None
    return {"session_id": session_id}


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
    required_items = [
        item for item in ledger.items if item.required_for_user_request and str(item.result_summary or "").strip()
    ]
    if required_items:
        return "\n\n".join(str(item.result_summary).strip() for item in required_items)
    successful_items: list[str] = []
    for item in ledger.items:
        if item.evidence_source == "loop_meta":
            if ledger.requires_round_trip_report and str(item.result_summary or "").strip():
                successful_items.append(str(item.result_summary).strip())
            continue
        if not _ledger_item_maps_to_successful_tool(item.ordinal, history):
            continue
        summary = str(item.result_summary or "").strip()
        if summary:
            successful_items.append(summary)
    return "\n\n".join(successful_items)


def _ledger_item_maps_to_successful_tool(
    ordinal: int,
    history: list[ToolExchange],
) -> bool:
    if ordinal < 1 or ordinal > len(history):
        return False
    return _is_successful_tool_result(history[ordinal - 1].tool_result)
