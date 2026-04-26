from __future__ import annotations

import json

from marten_runtime.runtime.direct_rendering import (
    maybe_render_tool_followup_text,
    render_direct_tool_text,
    render_recovery_fragment,
)
from marten_runtime.runtime.llm_client import (
    FinalizationEvidenceItem,
    FinalizationEvidenceLedger,
    LLMRequest,
    ToolExchange,
    ToolFollowupFragment,
    ToolFollowupRender,
)
from marten_runtime.tools.builtins.runtime_tool import annotate_runtime_context_status_peak


def append_tool_exchange(
    tool_history: list[ToolExchange],
    *,
    tool_name: str,
    tool_payload: dict,
    tool_result: object,
) -> None:
    tool_history.append(
        ToolExchange(
            tool_name=tool_name,
            tool_payload=tool_payload,
            tool_result=tool_result if isinstance(tool_result, dict) else {},
        )
    )


def normalize_tool_result_for_followup(
    *,
    tool_name: str,
    tool_payload: dict,
    tool_result: object,
    peak_input_tokens_estimate: int,
    peak_stage: str,
    actual_peak_input_tokens: int | None,
    actual_peak_output_tokens: int | None,
    actual_peak_total_tokens: int | None,
    actual_peak_stage: str | None,
    message: str = "",
    tool_history_count: int = 1,
    tool_history: list[ToolExchange] | None = None,
) -> tuple[object, ToolFollowupRender]:
    if isinstance(tool_result, dict) and tool_name == "runtime":
        annotated = annotate_runtime_context_status_peak(
            tool_result,
            peak_input_tokens_estimate=peak_input_tokens_estimate,
            peak_stage=peak_stage,
            actual_peak_input_tokens=actual_peak_input_tokens,
            actual_peak_output_tokens=actual_peak_output_tokens,
            actual_peak_total_tokens=actual_peak_total_tokens,
            actual_peak_stage=actual_peak_stage,
        )
        terminal_text = maybe_render_tool_followup_text(
            tool_name,
            annotated,
            tool_payload=tool_payload,
            tool_history=tool_history,
            message=message,
        ) or None
        recovery_text = render_direct_tool_text(
            tool_name,
            annotated,
            tool_payload=tool_payload,
        )
        return annotated, ToolFollowupRender(
            terminal_text=terminal_text,
            recovery_fragment=_tool_result_fragment(
                tool_name=tool_name,
                text=recovery_text,
            ),
        )
    if isinstance(tool_result, dict):
        terminal_text = maybe_render_tool_followup_text(
            tool_name,
            tool_result,
            tool_payload=tool_payload,
            tool_history=tool_history,
            message=message,
        ) or None
        recovery_text = render_direct_tool_text(
            tool_name,
            tool_result,
            tool_payload=tool_payload,
        )
        return tool_result, ToolFollowupRender(
            terminal_text=terminal_text,
            recovery_fragment=_tool_result_fragment(
                tool_name=tool_name,
                text=recovery_text,
            ),
        )
    del tool_payload, message, tool_history_count, tool_history
    return tool_result, ToolFollowupRender()


def build_tool_followup_request(
    base_request: LLMRequest,
    *,
    tool_history: list[ToolExchange],
    tool_result: object,
    requested_tool_name: str | None,
    requested_tool_payload: dict,
    finalization_evidence_ledger: FinalizationEvidenceLedger | None = None,
) -> LLMRequest:
    return base_request.model_copy(
        update={
            "tool_history": list(tool_history),
            "tool_result": tool_result,
            "requested_tool_name": requested_tool_name,
            "requested_tool_payload": requested_tool_payload,
            "finalization_evidence_ledger": finalization_evidence_ledger,
        }
    )


def build_finalization_retry_request(
    base_request: LLMRequest,
    *,
    tool_history: list[ToolExchange],
    finalization_evidence_ledger: FinalizationEvidenceLedger | None = None,
) -> LLMRequest:
    return base_request.model_copy(
        update={
            "conversation_messages": [],
            "compact_summary_text": None,
            "tool_outcome_summary_text": None,
            "memory_text": None,
            "tool_history": list(tool_history),
            "tool_result": None,
            "requested_tool_name": None,
            "requested_tool_payload": {},
            "available_tools": [],
            "request_kind": "finalization_retry",
            "finalization_evidence_ledger": finalization_evidence_ledger,
        }
    )


def build_finalization_evidence_ledger(
    *,
    user_message: str,
    tool_history: list[ToolExchange],
    model_request_count: int | None,
    requires_result_coverage: bool,
    requires_round_trip_report: bool,
) -> FinalizationEvidenceLedger:
    items: list[FinalizationEvidenceItem] = []
    for index, exchange in enumerate(tool_history, start=1):
        items.append(
            FinalizationEvidenceItem(
                ordinal=index,
                tool_name=exchange.tool_name,
                tool_action=_tool_action(exchange),
                payload_summary=_payload_summary(exchange.tool_payload),
                result_summary=_result_summary(exchange),
                required_for_user_request=(
                    requires_result_coverage and _is_successful_tool_result(exchange.tool_result)
                ),
                evidence_source="tool_result",
            )
        )
    if requires_round_trip_report:
        loop_meta_summary = _loop_meta_summary(
            model_request_count=model_request_count,
            tool_call_count=len(tool_history),
        )
        if loop_meta_summary:
            items.append(
                FinalizationEvidenceItem(
                    ordinal=len(items) + 1,
                    tool_name="runtime_loop",
                    result_summary=loop_meta_summary,
                    required_for_user_request=True,
                    evidence_source="loop_meta",
                )
            )
    return FinalizationEvidenceLedger(
        user_message=user_message,
        tool_call_count=len(tool_history),
        model_request_count=model_request_count,
        requires_result_coverage=requires_result_coverage,
        requires_round_trip_report=requires_round_trip_report,
        items=items,
    )


def _tool_result_fragment(
    *,
    tool_name: str,
    text: str,
) -> ToolFollowupFragment | None:
    normalized = str(text or "").strip()
    if not normalized:
        return None
    return ToolFollowupFragment(
        text=normalized,
        source="tool_result",
        tool_name=tool_name,
    )


def _tool_action(exchange: ToolExchange) -> str | None:
    action = str(exchange.tool_payload.get("action") or exchange.tool_result.get("action") or "").strip()
    return action or None


def _payload_summary(tool_payload: dict) -> str | None:
    if not isinstance(tool_payload, dict):
        return None
    important_keys = (
        "action",
        "timezone",
        "server_id",
        "tool_name",
        "session_id",
    )
    parts: list[str] = []
    for key in important_keys:
        if key == "action":
            continue
        value = tool_payload.get(key)
        if value in (None, "", [], {}):
            continue
        parts.append(f"{key}={value}")
    if parts:
        return ", ".join(parts)
    arguments = tool_payload.get("arguments")
    if isinstance(arguments, dict) and arguments:
        serialized = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        return _trim_summary(serialized, limit=80)
    return None


def _result_summary(exchange: ToolExchange) -> str:
    fragment_text = render_recovery_fragment(exchange.recovery_fragment)
    if fragment_text:
        return fragment_text
    direct_text = str(
        render_direct_tool_text(
            exchange.tool_name,
            exchange.tool_result,
            tool_payload=exchange.tool_payload,
        )
        or ""
    ).strip()
    if direct_text:
        return direct_text
    return _synthetic_result_summary(exchange)


def _synthetic_result_summary(exchange: ToolExchange) -> str:
    tool_result = exchange.tool_result if isinstance(exchange.tool_result, dict) else {}
    if tool_result.get("ok") is False or tool_result.get("is_error") is True:
        error_text = str(tool_result.get("error_text") or tool_result.get("error_code") or "").strip()
        if error_text:
            return error_text
        return f"{exchange.tool_name} 执行失败"
    for key in ("summary", "result_text", "text", "message", "status"):
        value = str(tool_result.get(key) or "").strip()
        if value:
            return value
    scalar_parts: list[str] = []
    for key in sorted(tool_result):
        value = tool_result.get(key)
        if key in {"ok", "is_error"} or value in (None, "", [], {}):
            continue
        if isinstance(value, (str, int, float, bool)):
            scalar_parts.append(f"{key}={value}")
        if len(scalar_parts) >= 3:
            break
    if scalar_parts:
        return _trim_summary(", ".join(scalar_parts), limit=120)
    action = _tool_action(exchange)
    if action:
        return f"{exchange.tool_name}.{action} 已执行"
    return f"{exchange.tool_name} 已执行"


def _loop_meta_summary(
    *,
    model_request_count: int | None,
    tool_call_count: int,
) -> str:
    if model_request_count is not None:
        return (
            f"本次请求共发生 {model_request_count} 次模型请求和 {tool_call_count} 次工具调用，"
            "属于多次模型/工具往返。"
        )
    return f"本轮共执行了 {tool_call_count} 次工具调用。"


def _is_successful_tool_result(tool_result: object) -> bool:
    if not isinstance(tool_result, dict):
        return False
    return tool_result.get("ok") is not False and tool_result.get("is_error") is not True


def _trim_summary(text: str, *, limit: int) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"
