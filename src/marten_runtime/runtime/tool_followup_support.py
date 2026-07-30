from __future__ import annotations

import json
from datetime import datetime

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
from marten_runtime.runtime.llm_message_support import (
    compact_bazi_verification_repair_evidence,
)
from marten_runtime.runtime.bazi_output_contract import (
    bazi_analysis_response_schema,
    bazi_semantic_review_response_schema,
    bazi_verification_events_response_schema,
    section_text,
)
from marten_runtime.runtime.tool_outcome_flow import collect_structured_hint_facts
from marten_runtime.tools.builtins.runtime_tool import annotate_runtime_context_status_peak
from marten_runtime.tools.builtins.runtime_tool import render_runtime_compaction_status_text


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
    invalid_final_text: str | None = None,
) -> LLMRequest:
    updates: dict[str, object] = {
        "conversation_messages": [],
        "tool_outcome_summary_text": None,
        "memory_text": None,
        "tool_history": list(tool_history),
        "tool_result": None,
        "requested_tool_name": None,
        "requested_tool_payload": {},
        "available_tools": [],
        "request_kind": "finalization_retry",
        "finalization_evidence_ledger": finalization_evidence_ledger,
        "invalid_final_text": " ".join(str(invalid_final_text or "").split()).strip()
        or None,
    }
    if base_request.agent_id == "bazi":
        updates.update(
            {
                "compact_summary_text": None,
                "working_context": {},
                "working_context_text": None,
                "skill_heads_text": None,
                "capability_catalog_text": None,
                "always_on_skill_text": None,
                "channel_protocol_instruction_text": None,
                "repository_context_text": None,
                "activated_skill_ids": [],
                "activated_skill_bodies": [],
            }
        )
    return base_request.model_copy(update=updates)


def build_bazi_final_generation_request(
    base_request: LLMRequest,
    *,
    tool_history: list[ToolExchange],
    finalization_evidence_ledger: FinalizationEvidenceLedger | None = None,
) -> LLMRequest:
    request = build_finalization_retry_request(
        base_request,
        tool_history=tool_history,
        finalization_evidence_ledger=finalization_evidence_ledger,
    )
    return request.model_copy(
        update={
            "request_kind": "bazi_final_generation",
            "max_completion_tokens": 3400,
            "response_schema_name": "bazi_analysis_draft",
            "response_schema": bazi_analysis_response_schema(),
        }
    )


def build_bazi_output_repair_request(
    base_request: LLMRequest,
    *,
    invalid_final_text: str,
    violations: list[str],
) -> LLMRequest:
    violation_text = "；".join(str(item or "").strip() for item in violations if str(item or "").strip())
    repair_text = (
        f"违规项：{violation_text}。\n原回复：{str(invalid_final_text or '').strip()}"
    ).strip()
    return base_request.model_copy(
        update={
            "conversation_messages": [],
            "compact_summary_text": None,
            "tool_outcome_summary_text": None,
            "memory_text": None,
            "working_context": {},
            "working_context_text": None,
            "skill_heads_text": None,
            "capability_catalog_text": None,
            "always_on_skill_text": None,
            "repository_context_text": None,
            "activated_skill_ids": [],
            "activated_skill_bodies": [],
            "tool_history": [],
            "tool_result": None,
            "requested_tool_name": None,
            "requested_tool_payload": {},
            "available_tools": [],
            "request_kind": "bazi_output_repair",
            "finalization_evidence_ledger": None,
            "invalid_final_text": repair_text or None,
        }
    )


def build_bazi_analysis_draft_repair_request(
    base_request: LLMRequest,
    *,
    tool_history: list[ToolExchange],
    invalid_draft_text: str,
    violations: list[str],
) -> LLMRequest:
    request = build_bazi_final_generation_request(
        base_request,
        tool_history=tool_history,
    )
    violation_text = "；".join(
        str(item or "").strip() for item in violations if str(item or "").strip()
    )
    return request.model_copy(
        update={
            "request_kind": "bazi_analysis_draft_repair",
            "invalid_final_text": (
                f"违规项：{violation_text}。\n上一版结构化草稿：{invalid_draft_text}"
            ),
        }
    )


def build_bazi_verification_event_repair_request(
    base_request: LLMRequest,
    *,
    tool_history: list[ToolExchange],
    current_events_json: str,
    violations: list[str],
) -> LLMRequest:
    request = build_bazi_final_generation_request(
        base_request,
        tool_history=tool_history,
    )
    try:
        current_payload = json.loads(current_events_json)
    except (TypeError, ValueError):
        current_payload = {}
    candidate_years = {
        int(candidate["year"])
        for candidate in current_payload.get("verification_candidates", [])
        if isinstance(candidate, dict)
        and isinstance(candidate.get("year"), int)
        and not isinstance(candidate.get("year"), bool)
    }
    compact_evidence = compact_bazi_verification_repair_evidence(
        tool_history,
        candidate_years,
    )
    violation_text = "；".join(
        str(item or "").strip() for item in violations if str(item or "").strip()
    )
    return request.model_copy(
        update={
            "request_kind": "bazi_verification_event_repair",
            "invalid_final_text": (
                f"语义审查违规项：{violation_text}。\n"
                f"上一版 verification_candidates 与 verification_events：{current_events_json}\n"
                "候选年份对应的确定性事实："
                f"{json.dumps(compact_evidence, ensure_ascii=False, separators=(',', ':'))}"
            ),
            "tool_history": [],
            "max_completion_tokens": 1600,
            "response_schema_name": "bazi_verification_events_patch",
            "response_schema": bazi_verification_events_response_schema(),
        }
    )


def build_bazi_output_semantic_review_request(
    base_request: LLMRequest,
    *,
    tool_history: list[ToolExchange],
    candidate_text: str,
    verification_events_json: str | None = None,
) -> LLMRequest:
    verification = section_text(candidate_text, "过三关").strip()
    review_material = verification or "过三关栏目为空"
    if verification_events_json:
        review_material = (
            f"{review_material}\n\n结构化候选与最终事件（仅供审查，不对用户展示）："
            f"{verification_events_json}"
        )
        try:
            verification_payload = json.loads(verification_events_json)
        except (TypeError, ValueError):
            verification_payload = {}
        candidate_years = {
            int(candidate["year"])
            for candidate in (
                verification_payload.get("verification_candidates", [])
                if isinstance(verification_payload, dict)
                else []
            )
            if isinstance(candidate, dict)
            and isinstance(candidate.get("year"), int)
            and not isinstance(candidate.get("year"), bool)
        }
        if candidate_years:
            deterministic_evidence = compact_bazi_verification_repair_evidence(
                tool_history,
                candidate_years,
            )
            review_material = (
                f"{review_material}\n\n候选年份确定性事实（审查合化、刑冲合害时以此为准）："
                f"{json.dumps(deterministic_evidence, ensure_ascii=False, separators=(',', ':'))}"
            )
    return base_request.model_copy(
        update={
            "conversation_messages": [],
            "compact_summary_text": None,
            "tool_outcome_summary_text": None,
            "memory_text": None,
            "working_context": {},
            "working_context_text": None,
            "skill_heads_text": None,
            "capability_catalog_text": None,
            "always_on_skill_text": None,
            "repository_context_text": None,
            "activated_skill_ids": [],
            "activated_skill_bodies": [],
            "tool_history": [],
            "tool_result": None,
            "requested_tool_name": None,
            "requested_tool_payload": {},
            "available_tools": [],
            "request_kind": "bazi_output_semantic_review",
            "finalization_evidence_ledger": None,
            "invalid_final_text": review_material,
            "max_completion_tokens": 500,
            "response_schema_name": "bazi_semantic_review",
            "response_schema": bazi_semantic_review_response_schema(),
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
                coverage_tokens=_coverage_tokens(exchange),
                required_for_user_request=(
                    requires_result_coverage and _is_successful_tool_result(exchange.tool_result)
                    and not is_intermediate_support_tool_result(tool_history, index - 1)
                ),
                evidence_source="tool_result",
            )
        )
    if model_request_count is not None:
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
                    required_for_user_request=requires_round_trip_report,
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


def is_intermediate_support_tool_result(
    tool_history: list[ToolExchange],
    index: int,
) -> bool:
    if index < 0 or index >= len(tool_history):
        return False
    exchange = tool_history[index]
    if not _is_successful_tool_result(exchange.tool_result):
        return False
    if exchange.tool_name == "mcp" and _tool_action(exchange) in {"list", "detail"}:
        return any(
            later.tool_name == "mcp"
            and _tool_action(later) == "call"
            for later in tool_history[index + 1 :]
        )
    return False


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


def _coverage_tokens(exchange: ToolExchange) -> list[str]:
    tool_result = exchange.tool_result if isinstance(exchange.tool_result, dict) else {}
    tool_payload = exchange.tool_payload if isinstance(exchange.tool_payload, dict) else {}
    tokens: list[str] = []
    if exchange.tool_name == "time":
        iso_time = str(tool_result.get("iso_time") or "").strip()
        if iso_time:
            try:
                observed = datetime.fromisoformat(iso_time)
            except ValueError:
                observed = None
            if observed is not None:
                tokens.extend(
                    [
                        observed.strftime("%Y-%m-%d"),
                        f"{observed.year}年{observed.month}月{observed.day}日",
                        observed.strftime("%H:%M"),
                        observed.strftime("%H:%M:%S"),
                    ]
                )
                weekday_tokens = (
                    "星期一",
                    "星期二",
                    "星期三",
                    "星期四",
                    "星期五",
                    "星期六",
                    "星期日",
                )
                english_weekdays = (
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                )
                weekday_index = observed.weekday()
                if 0 <= weekday_index < len(weekday_tokens):
                    tokens.extend(
                        [
                            weekday_tokens[weekday_index],
                            english_weekdays[weekday_index],
                        ]
                    )
    elif exchange.tool_name == "runtime":
        next_request = dict(tool_result.get("next_request_estimate") or {})
        for value in (
            next_request.get("input_tokens_estimate"),
            next_request.get("effective_window_tokens"),
            next_request.get("context_window_tokens"),
            tool_result.get("replay_user_turns"),
        ):
            if isinstance(value, (int, float)) and int(value) > 0:
                tokens.append(str(int(value)))
        usage_percent = tool_result.get("usage_percent")
        if isinstance(usage_percent, (int, float)) and int(usage_percent) >= 0:
            tokens.append(f"{int(usage_percent)}%")
        compaction_status = render_runtime_compaction_status_text(tool_result)
        if compaction_status:
            tokens.append(compaction_status)
    elif exchange.tool_name == "session":
        for value in (
            tool_payload.get("session_id"),
            ((tool_result.get("session") or {}).get("session_id") if isinstance(tool_result.get("session"), dict) else None),
            ((tool_result.get("transition") or {}).get("target_session_id") if isinstance(tool_result.get("transition"), dict) else None),
        ):
            normalized = str(value or "").strip()
            if normalized:
                tokens.append(normalized)
        count = tool_result.get("count")
        if isinstance(count, int) and count >= 0:
            tokens.append(str(count))
    elif exchange.tool_name == "memory":
        for key in ("section", "content"):
            normalized = str(tool_payload.get(key) or "").strip()
            if normalized:
                tokens.append(normalized)
        sections = tool_result.get("sections")
        if isinstance(sections, dict):
            for section_name, raw_items in sections.items():
                normalized_section = str(section_name or "").strip()
                if normalized_section:
                    tokens.append(normalized_section)
                if not isinstance(raw_items, list):
                    continue
                for item in raw_items[:3]:
                    normalized_item = str(item or "").strip()
                    if normalized_item:
                        tokens.append(normalized_item)
    elif exchange.tool_name == "spawn_subagent":
        queue_state = str(tool_result.get("queue_state") or "").strip()
        if queue_state:
            tokens.append(queue_state)
    for fact in collect_structured_hint_facts([exchange]):
        normalized = str(fact.value or "").strip()
        if normalized:
            tokens.append(normalized)
    deduped: list[str] = []
    for token in tokens:
        normalized = str(token).strip()
        if not normalized or normalized in deduped:
            continue
        deduped.append(normalized)
    return deduped


def _is_successful_tool_result(tool_result: object) -> bool:
    if not isinstance(tool_result, dict):
        return False
    return tool_result.get("ok") is not False and tool_result.get("is_error") is not True


def _trim_summary(text: str, *, limit: int) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"
