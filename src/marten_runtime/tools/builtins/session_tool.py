from __future__ import annotations

from uuid import uuid4

from marten_runtime.session.models import SessionRecord
from marten_runtime.session.store import SessionStore


def run_session_tool(
    payload: dict,
    *,
    session_store: SessionStore,
    tool_context: dict | None = None,
) -> dict:
    action = str(payload.get("action", "list")).strip().lower() or "list"
    current_user_id = _stable_user_id(tool_context)
    if action == "list":
        items = [
            _present_session(item)
            for item in session_store.list_sessions()
            if _is_session_visible_to_user(item, current_user_id=current_user_id)
        ]
        return {"action": action, "count": len(items), "items": items}
    if action == "show":
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            raise ValueError("session_id is required")
        record = session_store.get(session_id)
        _require_session_visibility(record, current_user_id=current_user_id)
        return {
            "action": action,
            "session": _present_session(
                record,
                include_compact_summary=True,
            ),
        }
    if action == "new":
        context = _require_context(tool_context)
        current = session_store.get(context["session_id"])
        created = session_store.create(
            session_id=f"sess_{uuid4().hex[:8]}",
            conversation_id=context["conversation_id"],
            config_snapshot_id=current.config_snapshot_id,
            bootstrap_manifest_id=current.bootstrap_manifest_id,
            channel_id=context["channel_id"],
        )
        session_store.set_active_agent(
            created.session_id,
            current.active_agent_id or current.agent_id or "main",
        )
        _inherit_catalog_metadata_for_new_session(
            session_store=session_store,
            created_session_id=created.session_id,
            current=current,
            current_user_id=current_user_id,
        )
        created = session_store.get(created.session_id)
        return {"action": action, "session": _present_session(created)}
    if action == "resume":
        context = _require_context(tool_context)
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            raise ValueError("session_id is required")
        target = session_store.get(session_id)
        _require_session_visibility(target, current_user_id=current_user_id)
        session_store.bind_conversation(
            channel_id=context["channel_id"],
            conversation_id=context["conversation_id"],
            session_id=target.session_id,
        )
        target = session_store.get(target.session_id)
        return {"action": action, "session": _present_session(target)}
    raise ValueError("unsupported session action")


def _require_context(tool_context: dict | None) -> dict[str, str]:
    context = tool_context or {}
    channel_id = str(context.get("channel_id") or "").strip()
    conversation_id = str(context.get("conversation_id") or "").strip()
    session_id = str(context.get("session_id") or "").strip()
    if not channel_id or not conversation_id or not session_id:
        raise ValueError("tool_context channel_id, conversation_id, session_id are required")
    return {
        "channel_id": channel_id,
        "conversation_id": conversation_id,
        "session_id": session_id,
    }


def _stable_user_id(tool_context: dict | None) -> str:
    return str((tool_context or {}).get("user_id") or "").strip()


def _is_session_visible_to_user(
    record: SessionRecord,
    *,
    current_user_id: str,
) -> bool:
    if not current_user_id:
        return record.user_id == ""
    return record.user_id == current_user_id


def _require_session_visibility(
    record: SessionRecord,
    *,
    current_user_id: str,
) -> None:
    if _is_session_visible_to_user(record, current_user_id=current_user_id):
        return
    raise ValueError("session_id is not visible to current user")


def _present_session(
    record: SessionRecord,
    *,
    include_compact_summary: bool = False,
) -> dict[str, object]:
    item = {
        "session_id": record.session_id,
        "conversation_id": record.conversation_id,
        "channel_id": record.channel_id,
        "user_id": record.user_id,
        "agent_id": record.agent_id or record.active_agent_id,
        "session_title": record.session_title,
        "session_preview": record.session_preview,
        "message_count": record.message_count,
        "state": record.state,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "last_event_at": (
            record.last_event_at.isoformat() if record.last_event_at is not None else None
        ),
    }
    if include_compact_summary:
        item["compact_summary"] = (
            record.latest_compacted_context.summary_text
            if record.latest_compacted_context is not None
            else record.session_preview
        )
    return item


def _inherit_catalog_metadata_for_new_session(
    *,
    session_store: SessionStore,
    created_session_id: str,
    current: SessionRecord,
    current_user_id: str,
) -> None:
    session_store.set_catalog_metadata(
        created_session_id,
        user_id=current_user_id or current.user_id,
        agent_id=current.agent_id or current.active_agent_id,
        session_title="",
        session_preview="",
    )
