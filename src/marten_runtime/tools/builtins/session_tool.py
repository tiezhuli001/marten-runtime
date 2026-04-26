from __future__ import annotations

from collections.abc import Callable

from marten_runtime.runtime.llm_client import LLMClient
from marten_runtime.session.models import SessionRecord
from marten_runtime.session.store import SessionStore
from marten_runtime.session.transition import SessionTransitionResult, execute_session_transition


def run_session_tool(
    payload: dict,
    *,
    session_store: SessionStore,
    tool_context: dict | None = None,
    record_transition: Callable[[SessionTransitionResult], None] | None = None,
) -> dict:
    action = str(payload.get("action") or "").strip().lower()
    if not action:
        raise ValueError("action is required")
    current_user_id = _stable_user_id(tool_context)
    current_session_id = str((tool_context or {}).get("session_id") or "").strip()
    if action == "list":
        items = [
            _present_session(item, current_session_id=current_session_id)
            for item in session_store.list_sessions()
            if _is_session_visible_to_user(item, current_user_id=current_user_id)
        ]
        items.sort(key=lambda item: 0 if item.get("is_current") else 1)
        current_session = next(
            (
                item
                for item in items
                if str(item.get("session_id") or "").strip() == current_session_id
            ),
            None,
        )
        return {
            "action": action,
            "count": len(items),
            "items": items,
            "current_session": current_session,
        }
    if action == "show":
        session_id = str(payload.get("session_id") or current_session_id or "").strip()
        if not session_id:
            raise ValueError("session_id is required")
        record = session_store.get(session_id)
        _require_session_visibility(record, current_user_id=current_user_id)
        return {
            "action": action,
            "session": _present_session(
                record,
                include_compact_summary=True,
                current_session_id=current_session_id,
            ),
        }
    if action == "new":
        context = _require_context(tool_context)
        current = session_store.get(context["session_id"])
        _require_session_visibility(current, current_user_id=current_user_id)
        transition = execute_session_transition(
            action="new",
            session_store=session_store,
            source_session_id=current.session_id,
            channel_id=context["channel_id"],
            conversation_id=context["conversation_id"],
            current_user_id=current_user_id,
            current_message=context["message"],
            llm=context["llm_client"],
            replay_user_turns=context["session_replay_user_turns"],
        )
        if record_transition is not None:
            record_transition(transition)
        return {
            "action": action,
            "session": _present_session(transition.session),
            "transition": _present_transition(transition),
        }
    if action == "resume":
        context = _require_context(tool_context)
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            raise ValueError("session_id is required")
        target = session_store.get(session_id)
        _require_session_visibility(target, current_user_id=current_user_id)
        transition = execute_session_transition(
            action="resume",
            session_store=session_store,
            source_session_id=context["session_id"],
            target_session_id=target.session_id,
            channel_id=context["channel_id"],
            conversation_id=context["conversation_id"],
            current_user_id=current_user_id,
            current_message=context["message"],
            llm=context["llm_client"],
            replay_user_turns=context["session_replay_user_turns"],
        )
        if record_transition is not None:
            record_transition(transition)
        return {
            "action": action,
            "session": _present_session(transition.session),
            "transition": _present_transition(transition),
        }
    raise ValueError("unsupported session action")


def _require_context(tool_context: dict | None) -> dict[str, str | int | LLMClient | None]:
    context = tool_context or {}
    channel_id = str(context.get("channel_id") or "").strip()
    conversation_id = str(context.get("conversation_id") or "").strip()
    session_id = str(context.get("session_id") or "").strip()
    if not channel_id or not conversation_id or not session_id:
        raise ValueError("tool_context channel_id, conversation_id, session_id are required")
    replay_user_turns = context.get("session_replay_user_turns")
    if isinstance(replay_user_turns, int):
        resolved_replay_user_turns = replay_user_turns
    else:
        try:
            resolved_replay_user_turns = int(replay_user_turns)
        except (TypeError, ValueError):
            resolved_replay_user_turns = 8
    return {
        "channel_id": channel_id,
        "conversation_id": conversation_id,
        "session_id": session_id,
        "message": str(context.get("message") or "").strip(),
        "llm_client": context.get("llm_client"),
        "session_replay_user_turns": max(1, resolved_replay_user_turns),
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
    current_session_id: str = "",
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
        "is_current": bool(current_session_id and record.session_id == current_session_id),
    }
    if include_compact_summary:
        has_compacted_context = record.latest_compacted_context is not None
        item["compact_summary"] = (
            record.latest_compacted_context.summary_text
            if has_compacted_context
            else record.session_preview
        )
        item["has_compacted_context"] = has_compacted_context
        item["compacted_at"] = (
            record.last_compacted_at.isoformat()
            if record.last_compacted_at is not None
            else None
        )
        item["compacted_prefix_end"] = (
            record.latest_compacted_context.source_message_range[1]
            if has_compacted_context and record.latest_compacted_context.source_message_range
            else None
        )
        item["preserved_tail_user_turns"] = (
            record.latest_compacted_context.preserved_tail_user_turns
            if has_compacted_context
            else None
        )
    return item


def _present_transition(transition: SessionTransitionResult) -> dict[str, object]:
    same_session_noop = (
        transition.action == "resume"
        and transition.source_session_id == transition.target_session_id
        and transition.compaction_reason == "same_session"
    )
    return {
        "mode": "noop_same_session" if same_session_noop else "switched",
        "binding_changed": not same_session_noop,
        "source_session_id": transition.source_session_id,
        "target_session_id": transition.target_session_id,
        "compaction_attempted": transition.compaction_attempted,
        "compaction_succeeded": transition.compaction_succeeded,
        "compaction_reason": transition.compaction_reason,
        "compaction_job": dict(transition.compaction_job) if transition.compaction_job else None,
    }
