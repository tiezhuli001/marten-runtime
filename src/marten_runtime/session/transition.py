from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from typing import Literal
from uuid import uuid4

from marten_runtime.runtime.llm_client import LLMClient
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.compaction_runner import build_compactable_prefix
from marten_runtime.session.models import SessionMessage, SessionRecord
from marten_runtime.session.store import SessionStore


@dataclass(frozen=True)
class SessionTransitionResult:
    action: Literal["new", "resume"]
    source_session_id: str
    target_session_id: str
    session: SessionRecord
    compaction_attempted: bool
    compaction_succeeded: bool
    compaction_reason: str
    compaction_job: dict[str, Any] | None = None


def execute_session_transition(
    *,
    action: Literal["new", "resume"],
    session_store: SessionStore,
    source_session_id: str,
    channel_id: str,
    conversation_id: str,
    current_user_id: str,
    current_message: str,
    llm: LLMClient | None,
    replay_user_turns: int,
    target_session_id: str | None = None,
) -> SessionTransitionResult:
    source = session_store.get(source_session_id)
    if action == "resume":
        if not target_session_id:
            raise ValueError("target_session_id is required for session.resume")
        if target_session_id == source_session_id:
            return SessionTransitionResult(
                action=action,
                source_session_id=source_session_id,
                target_session_id=source_session_id,
                session=source,
                compaction_attempted=False,
                compaction_succeeded=False,
                compaction_reason="same_session",
            )

    (
        compaction_attempted,
        compaction_succeeded,
        compaction_reason,
        compaction_job,
    ) = _maybe_enqueue_source_session_compaction(
        session_store=session_store,
        source=source,
        current_message=current_message,
        llm=llm,
        replay_user_turns=replay_user_turns,
    )

    if action == "new":
        target = _create_new_session(
            session_store=session_store,
            source=source,
            channel_id=channel_id,
            conversation_id=conversation_id,
            current_user_id=current_user_id,
        )
        carried_context = _build_new_session_continuation_checkpoint(
            source=source,
            target_session_id=target.session_id,
            current_message=current_message,
        )
        if carried_context is not None:
            session_store.set_compacted_context(target.session_id, carried_context)
            target = session_store.get(target.session_id)
    else:
        assert target_session_id is not None
        session_store.bind_conversation(
            channel_id=channel_id,
            conversation_id=conversation_id,
            session_id=target_session_id,
            user_id=current_user_id,
        )
        target = session_store.get(target_session_id)

    return SessionTransitionResult(
        action=action,
        source_session_id=source_session_id,
        target_session_id=target.session_id,
        session=target,
        compaction_attempted=compaction_attempted,
        compaction_succeeded=compaction_succeeded,
        compaction_reason=compaction_reason,
        compaction_job=compaction_job,
    )


def _maybe_enqueue_source_session_compaction(
    *,
    session_store: SessionStore,
    source: SessionRecord,
    current_message: str,
    llm: LLMClient | None,
    replay_user_turns: int,
) -> tuple[bool, bool, str, dict[str, Any] | None]:
    prefix, _tail, prefix_end_index = build_compactable_prefix(
        source.history,
        current_message=current_message,
        preserved_tail_user_turns=replay_user_turns,
    )
    if not prefix:
        return False, False, "no_prefix", None

    latest_compacted = source.latest_compacted_context
    latest_prefix_end = (
        latest_compacted.source_message_range[1]
        if latest_compacted is not None and latest_compacted.source_message_range
        else 0
    )
    if latest_prefix_end >= prefix_end_index:
        return False, False, "up_to_date", None

    enqueue_job = getattr(session_store, "enqueue_compaction_job", None)
    payload = {
        "source_session_id": source.session_id,
        "current_message": current_message,
        "preserved_tail_user_turns": replay_user_turns,
        "source_message_range": [0, prefix_end_index],
        "snapshot_message_count": len(source.history),
        "compaction_profile_name": getattr(llm, "profile_name", None),
    }
    if callable(enqueue_job):
        try:
            job = enqueue_job(**payload)
        except Exception:
            failed_job = {
                "job_id": "",
                "enqueue_status": "failed",
                **payload,
            }
            return True, False, "enqueue_failed", failed_job
        if isinstance(job, dict):
            return True, False, "deferred", job
        return True, False, "deferred", {
            "job_id": "",
            "enqueue_status": "queued",
            **payload,
        }
    failed_job = {
        "job_id": "",
        "enqueue_status": "failed",
        **payload,
    }
    return True, False, "enqueue_failed", failed_job


def _create_new_session(
    *,
    session_store: SessionStore,
    source: SessionRecord,
    channel_id: str,
    conversation_id: str,
    current_user_id: str,
) -> SessionRecord:
    created = session_store.create(
        session_id=f"sess_{uuid4().hex[:8]}",
        conversation_id=conversation_id,
        config_snapshot_id=source.config_snapshot_id,
        bootstrap_manifest_id=source.bootstrap_manifest_id,
        channel_id=channel_id,
        user_id=current_user_id or source.user_id,
    )
    session_store.set_active_agent(
        created.session_id,
        source.active_agent_id or source.agent_id or "main",
    )
    session_store.set_catalog_metadata(
        created.session_id,
        user_id=current_user_id or source.user_id,
        agent_id=source.agent_id or source.active_agent_id,
        session_title="",
        session_preview="",
    )
    return session_store.get(created.session_id)


def _build_new_session_continuation_checkpoint(
    *,
    source: SessionRecord,
    target_session_id: str,
    current_message: str,
) -> CompactedContext | None:
    source_compacted = source.latest_compacted_context
    carried_summary = _normalize_summary_text(
        source_compacted.summary_text if source_compacted is not None else ""
    )
    session_title = _normalize_summary_text(source.session_title)
    session_preview = _normalize_summary_text(source.session_preview)
    last_user_anchor = _latest_non_control_message(
        source.history,
        role="user",
        exclude_text=current_message,
    )
    last_assistant_anchor = _latest_non_control_message(
        source.history,
        role="assistant",
        exclude_text="",
    )

    summary_parts: list[str] = []
    if carried_summary:
        summary_parts.append(carried_summary)
    else:
        if session_title:
            summary_parts.append(f"当前主任务：{session_title}")
        if session_preview and session_preview not in "\n".join(summary_parts):
            summary_parts.append(session_preview)
        if last_user_anchor and last_user_anchor not in "\n".join(summary_parts):
            summary_parts.append(f"最近用户任务锚点：{last_user_anchor}")
        if last_assistant_anchor and last_assistant_anchor not in "\n".join(summary_parts):
            summary_parts.append(f"最近已知进展：{last_assistant_anchor}")
    if not summary_parts:
        return None

    summary_text = "\n".join(
        [
            "以下任务锚点来自切换前会话，用于在新会话里继续同一任务：",
            *summary_parts,
        ]
    )
    open_todos = [
        item
        for item in (
            [session_title] if session_title else []
        )
        if item
    ]
    if source_compacted is not None:
        for item in source_compacted.open_todos:
            normalized = _normalize_summary_text(item)
            if normalized and normalized not in open_todos:
                open_todos.append(normalized)
    next_step = _normalize_summary_text(
        source_compacted.next_step if source_compacted is not None else ""
    )
    if not next_step:
        subject = session_title or session_preview or last_user_anchor or last_assistant_anchor
        if subject:
            next_step = f"在新会话里继续{subject}"
    pending_risks: list[str] = []
    if source_compacted is not None:
        for item in source_compacted.pending_risks:
            normalized = _normalize_summary_text(item)
            if normalized and normalized not in pending_risks:
                pending_risks.append(normalized)
    return CompactedContext(
        compact_id=f"cmp_carry_{uuid4().hex[:8]}",
        session_id=target_session_id,
        summary_text=summary_text,
        source_message_range=[0, 1],
        preserved_tail_user_turns=(
            source_compacted.preserved_tail_user_turns if source_compacted is not None else 1
        ),
        trigger_kind="session_transition_carryover",
        next_step=next_step or None,
        open_todos=open_todos[:3],
        pending_risks=pending_risks[:3],
        created_at=datetime.now(timezone.utc),
    )


def _latest_non_control_message(
    history: list[SessionMessage],
    *,
    role: str,
    exclude_text: str,
) -> str:
    normalized_exclude = _normalize_summary_text(exclude_text)
    for item in reversed(history):
        if item.role != role:
            continue
        content = _normalize_summary_text(item.content)
        if not content or content == normalized_exclude:
            continue
        return content
    return ""


def _normalize_summary_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()
