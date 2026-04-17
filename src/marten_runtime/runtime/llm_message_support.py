from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from marten_runtime.runtime.llm_provider_support import (
    collapse_system_messages as _collapse_system_messages,
    resolve_parameters_schema as _resolve_parameters_schema,
)
from marten_runtime.runtime.llm_request_instructions import (
    request_specific_instruction as _request_specific_instruction,
    should_lock_runtime_context_followup as _should_lock_runtime_context_followup,
    tool_followup_instruction as _tool_followup_instruction,
)

if TYPE_CHECKING:
    from marten_runtime.runtime.llm_client import LLMRequest, ToolExchange


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
    _append_system_message(messages, request.working_context_text)
    _append_system_message(messages, _request_specific_instruction(request))
    lock_runtime_context_followup = _should_lock_runtime_context_followup(
        message=request.message,
        tool_history_count=len(request.tool_history),
    )
    _append_system_message(
        messages,
        _tool_followup_instruction(
            request.requested_tool_name,
            lock_runtime_context_followup=lock_runtime_context_followup,
            tool_history_count=len(request.tool_history),
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
        body["tool_choice"] = "auto"
    return body


def build_tool_definitions(request: "LLMRequest") -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": _tool_description(tool_name, request),
                "parameters": _resolve_parameters_schema(tool_name, request.tool_snapshot),
            },
        }
        for tool_name in request.available_tools
    ]


def _append_system_message(
    messages: list[dict[str, object]], content: str | None
) -> None:
    if content:
        messages.append({"role": "system", "content": content})


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
