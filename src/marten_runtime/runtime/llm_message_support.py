from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from marten_runtime.runtime.llm_provider_support import (
    collapse_system_messages as _collapse_system_messages,
    resolve_parameters_schema as _resolve_parameters_schema,
)
from marten_runtime.runtime.capabilities import (
    get_capability_declarations as _get_capability_declarations,
    render_capability_catalog_for_request as _render_capability_catalog_for_request,
    render_tool_description_for_provider as _render_tool_description_for_provider,
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
    is_session_summary = request.request_kind == "session_summary"
    include_capability_catalog = (
        bool(request.capability_catalog_text)
        and not is_tool_followup
        and request.request_kind != "contract_repair"
    )
    capability_catalog_text = request.capability_catalog_text
    if include_capability_catalog:
        capability_catalog_text = _compact_capability_catalog_for_request(request)
    _append_system_message(messages, request.system_prompt)
    if not is_tool_followup:
        _append_system_message(messages, request.skill_heads_text)
    if include_capability_catalog:
        _append_system_message(messages, capability_catalog_text)
    _append_system_message(messages, request.always_on_skill_text)
    _append_system_message(messages, request.repository_context_text)
    _append_system_message(messages, request.compact_summary_text)
    _append_system_message(messages, request.tool_outcome_summary_text)
    _append_system_message(messages, request.memory_text)
    _append_system_message(messages, request.working_context_text)
    if not is_session_summary:
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
                "description": _tool_description_for_provider(tool_name, request),
                "parameters": _tool_parameters_schema_for_provider(tool_name, request),
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
    if request.request_kind == "finalization_retry":
        ledger = request.finalization_evidence_ledger
        if (
            str(request.compact_summary_text or "").strip()
            and ledger is not None
            and not any(item.required_for_user_request for item in ledger.items)
        ):
            return []
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
        "content": json.dumps(
            _serialize_tool_result_for_provider(item.tool_result),
            ensure_ascii=True,
        ),
    }


def _serialize_tool_result_for_provider(
    tool_result: object,
    *,
    text_limit: int = 1600,
    content_item_limit: int = 2,
) -> object:
    if isinstance(tool_result, dict):
        if _is_successful_github_file_content_result(tool_result):
            text_limit = max(text_limit, 12000)
            content_item_limit = max(content_item_limit, 6)
        if _is_mcp_discovery_result(tool_result):
            content_item_limit = max(content_item_limit, 80)
        serialized: dict[str, object] = {}
        for key, value in tool_result.items():
            if key == "content" and isinstance(value, list):
                trimmed_items: list[object] = []
                for item in value[:content_item_limit]:
                    trimmed_items.append(
                        _serialize_tool_result_for_provider(
                            item,
                            text_limit=text_limit,
                            content_item_limit=content_item_limit,
                        )
                    )
                if len(value) > content_item_limit:
                    trimmed_items.append({"type": "truncated", "omitted_items": len(value) - content_item_limit})
                serialized[key] = trimmed_items
                continue
            if key in {"result_text", "text", "message"} and isinstance(value, str):
                serialized[key] = _truncate_ledger_text(value, limit=text_limit)
                continue
            if isinstance(value, str):
                serialized[key] = _truncate_ledger_text(value, limit=text_limit)
                continue
            if isinstance(value, dict):
                serialized[key] = _serialize_tool_result_for_provider(
                    value,
                    text_limit=text_limit,
                    content_item_limit=content_item_limit,
                )
                continue
            if isinstance(value, list):
                serialized[key] = [
                    _serialize_tool_result_for_provider(
                        item,
                        text_limit=text_limit,
                        content_item_limit=content_item_limit,
                    )
                    for item in value[:content_item_limit]
                ]
                if len(value) > content_item_limit:
                    serialized[f"{key}_truncated_count"] = len(value) - content_item_limit
                continue
            serialized[key] = value
        return serialized
    if isinstance(tool_result, list):
        trimmed = [
            _serialize_tool_result_for_provider(
                item,
                text_limit=text_limit,
                content_item_limit=content_item_limit,
            )
            for item in tool_result[:content_item_limit]
        ]
        if len(tool_result) > content_item_limit:
            trimmed.append({"omitted_items": len(tool_result) - content_item_limit})
        return trimmed
    if isinstance(tool_result, str):
        return _truncate_ledger_text(tool_result, limit=text_limit)
    return tool_result


def _is_successful_github_file_content_result(tool_result: dict[str, object]) -> bool:
    return (
        str(tool_result.get("action") or "").strip() == "call"
        and str(tool_result.get("server_id") or "").strip() == "github"
        and str(tool_result.get("tool_name") or "").strip() == "get_file_contents"
        and bool(tool_result.get("ok", True))
        and not bool(tool_result.get("is_error"))
    )


def _is_mcp_discovery_result(tool_result: dict[str, object]) -> bool:
    return str(tool_result.get("action") or "").strip() in {"list", "detail"}


def _tool_description(tool_name: str, request: "LLMRequest") -> str:
    metadata = request.tool_snapshot.tool_metadata.get(tool_name, {})
    if isinstance(metadata, Mapping):
        return str(metadata.get("description", ""))
    return ""


def _tool_description_for_provider(tool_name: str, request: "LLMRequest") -> str:
    declarations = _get_capability_declarations()
    declaration = declarations.get(tool_name)
    if declaration is not None:
        return _render_tool_description_for_provider(declaration)
    return _tool_description(tool_name, request)


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


def _tool_parameters_schema_for_provider(
    tool_name: str,
    request: "LLMRequest",
) -> dict[str, object]:
    schema = _tool_parameters_schema(tool_name, request)
    return _strip_schema_descriptions(schema)


def _strip_schema_descriptions(schema: object) -> object:
    if isinstance(schema, dict):
        cleaned: dict[str, object] = {}
        for key, value in schema.items():
            if key in {"description", "title", "examples", "default"}:
                continue
            cleaned[key] = _strip_schema_descriptions(value)
        return cleaned
    if isinstance(schema, list):
        return [_strip_schema_descriptions(item) for item in schema]
    return schema


def _compact_capability_catalog_for_request(request: "LLMRequest") -> str | None:
    declarations = _get_capability_declarations()
    source_text = str(request.capability_catalog_text or "")
    if "Global rule:" not in source_text:
        return source_text or None
    mcp_catalog_text = None
    marker = "MCP family contract:"
    if marker in source_text:
        mcp_catalog_text = source_text.split(marker, 1)[1]
        mcp_catalog_text = marker + mcp_catalog_text
    return _render_capability_catalog_for_request(
        declarations,
        available_tools=request.available_tools,
        mcp_catalog_text=mcp_catalog_text,
    )


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
