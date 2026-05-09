from __future__ import annotations

from marten_runtime.memory.intent import (
    MEMORY_SOURCE_EXCERPT_FIELD,
    has_explicit_memory_delete_intent,
    has_explicit_memory_write_intent,
)
from marten_runtime.memory.service import ThinMemoryService


def run_memory_tool(
    payload: dict,
    *,
    memory_service: ThinMemoryService,
    tool_context: dict | None = None,
) -> dict:
    action = str(payload.get("action", "get")).strip().lower() or "get"
    user_id = str((tool_context or {}).get("user_id") or "").strip()
    if not memory_service.has_stable_user_id(user_id):
        return {
            "action": action,
            "ok": True,
            "available": False,
            "user_id": "",
            "memory_text": "",
            "rendered_memory": None,
        }
    if action == "get":
        document = memory_service.load(user_id)
    elif action == "append":
        _require_explicit_memory_intent(action, payload, tool_context=tool_context)
        document = memory_service.append(
            user_id,
            section=str(payload.get("section", "")).strip(),
            content=str(payload.get("content", "")).strip(),
        )
    elif action == "replace":
        _require_explicit_memory_intent(action, payload, tool_context=tool_context)
        document = memory_service.replace(
            user_id,
            section=str(payload.get("section", "")).strip(),
            content=str(payload.get("content", "")).strip(),
        )
    elif action == "delete":
        _require_explicit_memory_intent(action, payload, tool_context=tool_context)
        document = memory_service.delete(
            user_id,
            section=str(payload.get("section", "")).strip(),
            content=(
                str(payload.get("content", "")).strip()
                if str(payload.get("content", "")).strip()
                else None
            ),
        )
    else:
        raise ValueError("unsupported memory action")
    return {
        "action": action,
        "ok": True,
        "available": True,
        "user_id": user_id,
        "memory_text": document.text,
        "rendered_memory": memory_service.render_prompt_memory(user_id),
        "sections": document.sections,
    }


def _require_explicit_memory_intent(
    action: str,
    payload: dict,
    *,
    tool_context: dict | None = None,
) -> None:
    if _has_explicit_memory_intent(action, payload):
        _require_memory_source_excerpt(payload, tool_context=tool_context)
        return
    raise ValueError("explicit user memory intent is required for memory writes")


def _has_explicit_memory_intent(action: str, payload: dict) -> bool:
    if action == "delete":
        return has_explicit_memory_delete_intent(payload)
    return has_explicit_memory_write_intent(payload)


def _require_memory_source_excerpt(
    payload: dict,
    *,
    tool_context: dict | None,
) -> None:
    normalized_excerpt = _normalize_memory_source_text(
        payload.get(MEMORY_SOURCE_EXCERPT_FIELD)
    )
    normalized_message = _normalize_memory_source_text(
        (tool_context or {}).get("message")
    )
    if normalized_excerpt and normalized_message and normalized_excerpt in normalized_message:
        return
    raise ValueError("memory source_excerpt must quote the current user message")


def _normalize_memory_source_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip().casefold()
