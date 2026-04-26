from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from marten_runtime.runtime.llm_provider_support import (
    collapse_system_messages as _collapse_system_messages,
    resolve_parameters_schema as _resolve_parameters_schema,
)
from marten_runtime.runtime.llm_request_instructions import (
    request_specific_instruction as _request_specific_instruction,
    tool_followup_instruction as _tool_followup_instruction,
)

if TYPE_CHECKING:
    from marten_runtime.runtime.llm_client import (
        FinalizationEvidenceItem,
        FinalizationEvidenceLedger,
        LLMRequest,
        ToolExchange,
    )


def build_openai_messages(request: "LLMRequest") -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    is_tool_followup = bool(request.tool_history) or (
        request.tool_result is not None and bool(request.requested_tool_name)
    )
    include_capability_catalog = bool(request.capability_catalog_text) and not is_tool_followup
    _append_system_message(messages, request.system_prompt)
    if not is_tool_followup:
        _append_system_message(messages, request.skill_heads_text)
    if include_capability_catalog:
        _append_system_message(messages, request.capability_catalog_text)
    _append_system_message(messages, request.always_on_skill_text)
    _append_system_message(messages, request.compact_summary_text)
    _append_system_message(messages, request.tool_outcome_summary_text)
    _append_system_message(messages, request.memory_text)
    _append_system_message(messages, request.working_context_text)
    _append_system_message(messages, _request_specific_instruction(request))
    _append_system_message(
        messages,
        render_finalization_evidence_ledger_block(
            request.finalization_evidence_ledger
            if (is_tool_followup or request.request_kind == "finalization_retry")
            else None
        ),
    )
    _append_system_message(
        messages,
        _tool_followup_instruction(
            request.requested_tool_name,
            tool_history_count=len(request.tool_history),
            has_evidence_ledger=request.finalization_evidence_ledger is not None,
            required_evidence_count=sum(
                1
                for item in (request.finalization_evidence_ledger.items if request.finalization_evidence_ledger else [])
                if item.required_for_user_request
            ),
        ),
    )
    for body in request.activated_skill_bodies:
        _append_system_message(messages, body)
    for item in request.conversation_messages:
        messages.append({"role": item.role, "content": item.content})
    messages.append({"role": "user", "content": request.message})
    for index, item in enumerate(_tool_history_for_request(request), start=1):
        call_id = f"call_{index}"
        messages.append(_assistant_tool_call_message(item, call_id))
        messages.append(_tool_result_message(item, call_id))
    return _collapse_system_messages(messages)


def build_openai_chat_payload(
    model_name: str, request: "LLMRequest"
) -> dict[str, object]:
    body: dict[str, object] = {
        "model": model_name,
        "messages": build_openai_messages(request),
    }
    tool_definitions = build_tool_definitions(request)
    if tool_definitions:
        body["tools"] = tool_definitions
        body["tool_choice"] = build_openai_tool_choice(
            request,
            responses_api=False,
        ) or "auto"
    return body


def build_tool_definitions(request: "LLMRequest") -> list[dict[str, object]]:
    if request.request_kind == "finalization_retry":
        return []
    tool_names = list(request.available_tools)
    forced_tool_name = _forced_initial_tool_name(request)
    if forced_tool_name:
        tool_names = [tool_name for tool_name in tool_names if tool_name == forced_tool_name]
    return [
        {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": _tool_description(tool_name, request),
                "parameters": _tool_parameters_schema(tool_name, request),
            },
        }
        for tool_name in tool_names
    ]


def _append_system_message(
    messages: list[dict[str, object]], content: str | None
) -> None:
    if content:
        messages.append({"role": "system", "content": content})


def render_finalization_evidence_ledger_block(
    ledger: "FinalizationEvidenceLedger" | None,
) -> str | None:
    if ledger is None or not ledger.items:
        return None
    lines = [
        "Current-turn evidence ledger:",
        f"- tool_call_count={ledger.tool_call_count}",
    ]
    if ledger.model_request_count is not None:
        lines.append(f"- model_request_count={ledger.model_request_count}")
    lines.append(
        "- requires_result_coverage={value}".format(
            value="yes" if ledger.requires_result_coverage else "no"
        )
    )
    lines.append(
        "- requires_round_trip_report={value}".format(
            value="yes" if ledger.requires_round_trip_report else "no"
        )
    )
    lines.append("- evidence_items:")
    for item in ledger.items:
        lines.append(_render_finalization_evidence_item(item))
    return "\n".join(lines)


def _tool_history_for_request(request: "LLMRequest") -> list["ToolExchange"]:
    tool_history = list(request.tool_history)
    if tool_history or request.tool_result is None or not request.requested_tool_name:
        return tool_history
    from marten_runtime.runtime.llm_client import ToolExchange

    tool_history.append(
        ToolExchange(
            tool_name=request.requested_tool_name,
            tool_payload=request.requested_tool_payload,
            tool_result=request.tool_result,
        )
    )
    return tool_history


def _render_finalization_evidence_item(item: "FinalizationEvidenceItem") -> str:
    parts = [
        f"{item.ordinal}. tool={item.tool_name}",
        f"required={'yes' if item.required_for_user_request else 'no'}",
        f"source={item.evidence_source}",
    ]
    if item.tool_action:
        parts.append(f"action={item.tool_action}")
    if item.payload_summary:
        parts.append(f"payload={_truncate_ledger_text(item.payload_summary, limit=80)}")
    parts.append(f"result={_truncate_ledger_text(item.result_summary, limit=180)}")
    return "- " + " | ".join(parts)


def _truncate_ledger_text(text: str | None, *, limit: int) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _assistant_tool_call_message(
    item: "ToolExchange", call_id: str
) -> dict[str, object]:
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": item.tool_name,
                    "arguments": json.dumps(item.tool_payload, ensure_ascii=True),
                },
            }
        ],
    }


def _tool_result_message(item: "ToolExchange", call_id: str) -> dict[str, object]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(item.tool_result, ensure_ascii=True),
    }


def _tool_description(tool_name: str, request: "LLMRequest") -> str:
    metadata = request.tool_snapshot.tool_metadata.get(tool_name, {})
    if isinstance(metadata, Mapping):
        return str(metadata.get("description", ""))
    return ""


def _forced_initial_tool_name(request: "LLMRequest") -> str | None:
    if request.tool_history or request.tool_result is not None:
        return None
    forced = str(request.requested_tool_name or "").strip()
    if not forced:
        return None
    return forced


def resolve_required_initial_tool_name(request: "LLMRequest") -> str | None:
    forced_tool_name = _forced_initial_tool_name(request)
    if forced_tool_name:
        return forced_tool_name
    return None


def build_openai_tool_choice(
    request: "LLMRequest",
    *,
    responses_api: bool,
) -> dict[str, object] | None:
    required_tool_name = resolve_required_initial_tool_name(request)
    if not required_tool_name:
        return None
    if responses_api:
        return {"type": "function", "name": required_tool_name}
    return {"type": "function", "function": {"name": required_tool_name}}


def _tool_parameters_schema(tool_name: str, request: "LLMRequest") -> dict[str, object]:
    schema = _resolve_parameters_schema(tool_name, request.tool_snapshot)
    if tool_name != "session":
        return schema
    if _forced_initial_tool_name(request) != "session":
        return schema
    return _forced_session_parameters_schema(schema, request.requested_tool_payload)


def _forced_session_parameters_schema(
    schema: dict[str, object],
    payload: Mapping[str, object],
) -> dict[str, object]:
    narrowed = copy.deepcopy(schema)
    properties = narrowed.setdefault("properties", {})
    if not isinstance(properties, dict):
        return narrowed
    required = list(narrowed.get("required", []))
    action = str(payload.get("action") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    if action:
        action_schema = dict(properties.get("action") or {})
        action_schema["type"] = "string"
        action_schema["enum"] = [action]
        properties["action"] = action_schema
        if "action" not in required:
            required.append("action")
    if session_id:
        session_schema = dict(properties.get("session_id") or {})
        session_schema["type"] = "string"
        session_schema["enum"] = [session_id]
        properties["session_id"] = session_schema
        if "session_id" not in required:
            required.append("session_id")
    narrowed["required"] = required
    return narrowed
