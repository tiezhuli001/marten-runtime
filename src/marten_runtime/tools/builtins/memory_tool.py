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
        normalized = _normalize_scope_payload(payload, tool_context=tool_context)
        document = memory_service.append(
            user_id,
            section=str(payload.get("section", "")).strip(),
            content=str(payload.get("content", "")).strip(),
            **normalized,
        )
    elif action == "replace":
        _require_explicit_memory_intent(action, payload, tool_context=tool_context)
        normalized = _normalize_scope_payload(payload, tool_context=tool_context)
        document = memory_service.replace(
            user_id,
            section=str(payload.get("section", "")).strip(),
            content=str(payload.get("content", "")).strip(),
            memory_id=str(payload.get("memory_id", "")).strip() or None,
            **normalized,
        )
    elif action == "delete":
        _require_explicit_memory_intent(action, payload, tool_context=tool_context)
        normalized = _normalize_delete_payload(payload, tool_context=tool_context)
        document = memory_service.delete(
            user_id,
            section=str(payload.get("section", "")).strip(),
            content=(
                str(payload.get("content", "")).strip()
                if str(payload.get("content", "")).strip()
                else None
            ),
            memory_id=str(payload.get("memory_id", "")).strip() or None,
            **normalized,
        )
    else:
        raise ValueError("unsupported memory action")
    return {
        "action": action,
        "ok": True,
        "available": True,
        "user_id": user_id,
        "memory_text": document.text,
        "rendered_memory": memory_service.render_prompt_memory(
            user_id,
            agent_id=str((tool_context or {}).get("agent_id") or "").strip() or None,
            workspace_id=str((tool_context or {}).get("workspace_id") or "").strip() or None,
            current_message=str((tool_context or {}).get("message") or ""),
        ),
        "sections": document.sections,
        "items": [item.model_dump() for item in document.items],
    }


def _normalize_scope_payload(
    payload: dict,
    *,
    tool_context: dict | None,
) -> dict:
    scope = str(payload.get("scope") or "global").strip().lower()
    memory_type = str(payload.get("type") or _type_from_section(str(payload.get("section") or ""))).strip().lower()
    agent_id = str(payload.get("agent_id") or "").strip()
    workspace_id = str(payload.get("workspace_id") or "").strip()
    if scope == "agent":
        agent_id = agent_id or str((tool_context or {}).get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required for agent memory")
    if scope == "workspace" and not workspace_id:
        raise ValueError("workspace_id is required for workspace memory")
    return {
        "scope": scope,
        "agent_id": agent_id or None,
        "workspace_id": workspace_id or None,
        "type": memory_type,
        "source_excerpt": str(payload.get(MEMORY_SOURCE_EXCERPT_FIELD) or "").strip(),
        "source_run_id": str(payload.get("source_run_id") or (tool_context or {}).get("run_id") or "").strip() or None,
        "priority": int(payload.get("priority", 50) or 50),
    }


def _normalize_delete_payload(
    payload: dict,
    *,
    tool_context: dict | None,
) -> dict:
    scope = str(payload.get("scope") or "").strip().lower() or None
    agent_id = str(payload.get("agent_id") or "").strip() or None
    workspace_id = str(payload.get("workspace_id") or "").strip() or None
    if scope == "agent":
        agent_id = agent_id or str((tool_context or {}).get("agent_id") or "").strip() or None
        if not agent_id:
            raise ValueError("agent_id is required for agent memory")
    if scope == "workspace" and not workspace_id:
        raise ValueError("workspace_id is required for workspace memory")
    return {"scope": scope, "agent_id": agent_id, "workspace_id": workspace_id}


def _type_from_section(section: str) -> str:
    value = " ".join(str(section or "").split()).strip().lower()
    if value in {"preferences", "preference"}:
        return "preference"
    if value in {"constraints", "constraint"}:
        return "constraint"
    if value in {"workflow_hints", "workflow hints", "workflow_hint"}:
        return "workflow_hint"
    return "fact"


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
