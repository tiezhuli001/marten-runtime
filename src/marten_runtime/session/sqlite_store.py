from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from marten_runtime.apps.runtime_defaults import DEFAULT_AGENT_ID
from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compaction_job import SessionCompactionJob
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage, SessionRecord
from marten_runtime.session.store import SessionStore, _should_apply_compacted_context
from marten_runtime.session.tool_outcome_summary import (
    ToolOutcomeSummary,
    coerce_tool_outcome_summary,
)
from marten_runtime.sqlite_support import connect_sqlite, prepare_sqlite_path


class SQLiteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None:
        self.path = prepare_sqlite_path(path)
        self._init_schema()

    def create(
        self,
        session_id: str,
        conversation_id: str,
        config_snapshot_id: str = "cfg_bootstrap",
        bootstrap_manifest_id: str = "boot_default",
        *,
        channel_id: str = "",
        user_id: str = "",
    ) -> SessionRecord:
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            session_id=session_id,
            conversation_id=conversation_id,
            channel_id=channel_id,
            user_id=user_id,
            created_at=now,
            updated_at=now,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id=bootstrap_manifest_id,
        )
        record.history.append(SessionMessage.system("created"))
        self._refresh_message_count(record)
        self._write_record(record)
        self.bind_conversation(
            channel_id=channel_id,
            conversation_id=conversation_id,
            session_id=session_id,
            user_id=user_id,
        )
        return self.get(session_id)

    def create_child_session(
        self,
        *,
        parent_session_id: str,
        conversation_id: str,
        session_id: str | None = None,
        agent_id: str | None = None,
        active_agent_id: str | None = None,
    ) -> SessionRecord:
        parent = self.get(parent_session_id)
        now = datetime.now(timezone.utc)
        child = SessionRecord(
            session_id=session_id or f"sess_{uuid4().hex[:8]}",
            conversation_id=conversation_id,
            channel_id=parent.channel_id,
            user_id=parent.user_id,
            agent_id=parent.agent_id if agent_id is None else agent_id,
            active_agent_id=(
                parent.active_agent_id if active_agent_id is None else active_agent_id
            ),
            created_at=now,
            updated_at=now,
            config_snapshot_id=parent.config_snapshot_id,
            bootstrap_manifest_id=parent.bootstrap_manifest_id,
            parent_session_id=parent.session_id,
            session_kind="subagent",
            lineage_depth=parent.lineage_depth + 1,
        )
        child.history.append(SessionMessage.system("created"))
        self._refresh_message_count(child)
        self._write_record(child)
        self.bind_conversation(
            channel_id=parent.channel_id,
            conversation_id=conversation_id,
            session_id=child.session_id,
            user_id=parent.user_id,
        )
        return self.get(child.session_id)

    def get_or_create_for_conversation(
        self,
        conversation_id: str,
        config_snapshot_id: str = "cfg_bootstrap",
        bootstrap_manifest_id: str = "boot_default",
        *,
        channel_id: str = "",
        user_id: str = "",
    ) -> SessionRecord:
        session_id = self.resolve_session_for_conversation(
            channel_id=channel_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        if session_id is not None:
            return self.get(session_id)
        return self.create(
            session_id=f"sess_{uuid4().hex[:8]}",
            conversation_id=conversation_id,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id=bootstrap_manifest_id,
            channel_id=channel_id,
            user_id=user_id,
        )

    def append_message(self, session_id: str, message: SessionMessage) -> SessionRecord:
        record = self.get(session_id)
        record.history.append(message)
        self._refresh_message_count(record)
        record.updated_at = message.created_at
        record.last_event_at = message.created_at
        self._write_record(record)
        return self.get(session_id)

    def remove_last_message_if_match(
        self,
        session_id: str,
        message: SessionMessage,
        *,
        restore_updated_at: datetime,
        restore_last_event_at: datetime | None,
    ) -> SessionRecord:
        record = self.get(session_id)
        if not record.history:
            return record
        last = record.history[-1]
        if (
            last.role != message.role
            or last.content != message.content
            or last.created_at != message.created_at
        ):
            return record
        record.history.pop()
        self._refresh_message_count(record)
        record.updated_at = restore_updated_at
        record.last_event_at = restore_last_event_at
        self._write_record(record)
        return self.get(session_id)

    def mark_run(self, session_id: str, run_id: str, event_at: datetime) -> SessionRecord:
        record = self.get(session_id)
        record.state = "running"
        record.last_run_id = run_id
        record.last_event_at = event_at
        record.updated_at = event_at
        self._write_record(record)
        return self.get(session_id)

    def set_active_agent(self, session_id: str, agent_id: str) -> SessionRecord:
        record = self.get(session_id)
        record.active_agent_id = agent_id
        record.agent_id = agent_id
        self._write_record(record)
        return self.get(session_id)

    def set_catalog_metadata(
        self,
        session_id: str,
        *,
        user_id: str,
        agent_id: str,
        session_title: str,
        session_preview: str,
    ) -> SessionRecord:
        record = self.get(session_id)
        record.user_id = user_id
        record.agent_id = agent_id
        record.session_title = session_title
        record.session_preview = session_preview
        self._write_record(record)
        self.bind_conversation(
            channel_id=record.channel_id,
            conversation_id=record.conversation_id,
            session_id=session_id,
            user_id=user_id,
        )
        return self.get(session_id)

    def set_bootstrap_manifest(self, session_id: str, bootstrap_manifest_id: str) -> SessionRecord:
        record = self.get(session_id)
        record.bootstrap_manifest_id = bootstrap_manifest_id
        self._write_record(record)
        return self.get(session_id)

    def set_compacted_context(self, session_id: str, compacted_context: CompactedContext) -> SessionRecord:
        record = self.get(session_id)
        record.latest_compacted_context = compacted_context
        record.last_compacted_at = compacted_context.created_at
        record.updated_at = compacted_context.created_at
        self._write_record(record)
        return self.get(session_id)

    def set_compacted_context_if_newer(
        self,
        session_id: str,
        compacted_context: CompactedContext,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT latest_compacted_context_json
                FROM sessions
                WHERE session_id = ?
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(session_id)
            current = (
                CompactedContext.model_validate_json(str(row[0]))
                if row[0] is not None
                else None
            )
            if not _should_apply_compacted_context(current, compacted_context):
                return False
            conn.execute(
                """
                UPDATE sessions
                SET latest_compacted_context_json = ?,
                    last_compacted_at = ?,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (
                    compacted_context.model_dump_json(exclude_none=True),
                    compacted_context.created_at.isoformat(),
                    compacted_context.created_at.isoformat(),
                    session_id,
                ),
            )
        return True

    def set_latest_actual_usage(self, session_id: str, usage: NormalizedUsage) -> SessionRecord:
        record = self.get(session_id)
        record.latest_actual_usage = usage
        if usage.captured_at is not None:
            record.updated_at = usage.captured_at
        self._write_record(record)
        return self.get(session_id)

    def append_tool_outcome_summary(
        self,
        session_id: str,
        summary: ToolOutcomeSummary | dict[str, object],
        *,
        max_items: int = 5,
    ) -> SessionRecord:
        record = self.get(session_id)
        item = coerce_tool_outcome_summary(summary)
        dedupe_key = item.dedupe_key()
        existing = [
            current
            for current in record.recent_tool_outcome_summaries
            if current.dedupe_key() != dedupe_key
        ]
        record.recent_tool_outcome_summaries = [*existing, item][-max_items:]
        record.updated_at = item.created_at
        self._write_record(record)
        return self.get(session_id)

    def list_recent_tool_outcome_summaries(
        self,
        session_id: str,
        *,
        limit: int = 3,
    ) -> list[ToolOutcomeSummary]:
        if limit <= 0:
            return []
        record = self.get(session_id)
        return list(record.recent_tool_outcome_summaries[-limit:])

    def bind_conversation(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        session_id: str,
        user_id: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM session_bindings
                WHERE session_id = ?
                  AND NOT (channel_id = ? AND conversation_id = ? AND user_id = ?)
                """,
                (session_id, channel_id, conversation_id, user_id),
            )
            if user_id:
                conn.execute(
                    """
                    DELETE FROM session_bindings
                    WHERE channel_id = ?
                      AND conversation_id = ?
                      AND user_id IN ('', ?)
                      AND NOT (session_id = ? AND user_id = ?)
                    """,
                    (channel_id, conversation_id, user_id, session_id, user_id),
                )
            conn.execute(
                """
                INSERT INTO session_bindings (channel_id, conversation_id, user_id, session_id, bound_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(channel_id, conversation_id, user_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    bound_at=excluded.bound_at
                """,
                (
                    channel_id,
                    conversation_id,
                    user_id,
                    session_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.execute(
                """
                UPDATE sessions
                SET conversation_id = ?, channel_id = ?,
                    user_id = CASE WHEN ? <> '' THEN ? ELSE user_id END
                WHERE session_id = ?
                """,
                (conversation_id, channel_id, user_id, user_id, session_id),
            )

    def resolve_session_for_conversation(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        user_id: str = "",
    ) -> str | None:
        with self._connect() as conn:
            if user_id:
                row = conn.execute(
                    """
                    SELECT session_id
                    FROM session_bindings
                    WHERE channel_id = ? AND conversation_id = ? AND user_id = ?
                    LIMIT 1
                    """,
                    (channel_id, conversation_id, user_id),
                ).fetchone()
                if row is not None:
                    return str(row[0])
                row = conn.execute(
                    """
                    SELECT b.session_id
                    FROM session_bindings b
                    LEFT JOIN sessions s ON s.session_id = b.session_id
                    WHERE b.channel_id = ?
                      AND b.conversation_id = ?
                      AND b.user_id = ''
                      AND TRIM(COALESCE(s.user_id, '')) = ''
                    LIMIT 1
                    """,
                    (channel_id, conversation_id),
                ).fetchone()
                if row is not None:
                    return str(row[0])
                return None
            rows = conn.execute(
                """
                SELECT DISTINCT b.session_id
                FROM session_bindings b
                LEFT JOIN sessions s ON s.session_id = b.session_id
                WHERE b.channel_id = ?
                  AND b.conversation_id = ?
                  AND b.user_id = ''
                  AND TRIM(COALESCE(s.user_id, '')) = ''
                """,
                (channel_id, conversation_id),
            ).fetchall()
            if len(rows) == 1:
                return str(rows[0][0])
            if channel_id:
                return None
            row = conn.execute(
                """
                SELECT session_id
                FROM sessions
                WHERE conversation_id = ?
                  AND TRIM(COALESCE(user_id, '')) = ''
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row[0])

    def get(self, session_id: str) -> SessionRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, conversation_id, state, created_at, updated_at,
                       channel_id, user_id, agent_id, session_title, session_preview, message_count,
                       active_agent_id, parent_session_id, session_kind, lineage_depth,
                       config_snapshot_id, bootstrap_manifest_id, context_snapshot_id,
                       last_run_id, last_event_at, last_compacted_at,
                       latest_compacted_context_json, latest_actual_usage_json,
                       tool_call_count
                FROM sessions
                WHERE session_id = ?
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(session_id)
            record = self._record_from_session_row(row)
            message_rows = conn.execute(
                """
                SELECT role, content, created_at, received_at, enqueued_at, started_at
                FROM session_messages
                WHERE session_id = ?
                ORDER BY message_index
                """,
                (session_id,),
            ).fetchall()
            summary_rows = conn.execute(
                """
                SELECT summary_json
                FROM session_tool_outcome_summaries
                WHERE session_id = ?
                ORDER BY summary_index
                """,
                (session_id,),
            ).fetchall()
        record.history = [
            SessionMessage(
                role=str(item[0]),
                content=str(item[1]),
                created_at=datetime.fromisoformat(str(item[2])),
                received_at=datetime.fromisoformat(str(item[3])) if item[3] is not None else None,
                enqueued_at=datetime.fromisoformat(str(item[4])) if item[4] is not None else None,
                started_at=datetime.fromisoformat(str(item[5])) if item[5] is not None else None,
            )
            for item in message_rows
        ]
        record.recent_tool_outcome_summaries = [
            ToolOutcomeSummary.model_validate_json(str(item[0])) for item in summary_rows
        ]
        return record

    def list_sessions(self) -> list[SessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, conversation_id, state, created_at, updated_at,
                       channel_id, user_id, agent_id, session_title, session_preview, message_count,
                       active_agent_id, parent_session_id, session_kind, lineage_depth,
                       config_snapshot_id, bootstrap_manifest_id, context_snapshot_id,
                       last_run_id, last_event_at, last_compacted_at,
                       latest_compacted_context_json, latest_actual_usage_json,
                       tool_call_count
                FROM sessions
                ORDER BY COALESCE(last_event_at, updated_at) DESC, updated_at DESC
                """
            ).fetchall()
        return [self._record_from_session_row(row, include_payloads=False) for row in rows]

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        return int(row[0] if row is not None else 0)

    def binding_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM session_bindings").fetchone()
        return int(row[0] if row is not None else 0)

    def enqueue_compaction_job(self, **payload) -> dict[str, object]:  # noqa: ANN003
        job = SessionCompactionJob(**payload)
        with self._connect() as conn:
            self._ensure_compaction_job_table(conn)
            conn.execute(
                """
                INSERT INTO session_compaction_jobs (
                    job_id, source_session_id, current_message, preserved_tail_user_turns,
                    source_message_range_json, snapshot_message_count, compaction_profile_name,
                    enqueue_status,
                    status, enqueued_at, started_at, finished_at, queue_wait_ms,
                    compaction_llm_ms, persist_ms, source_range_end, write_applied,
                    result_reason, error_code, error_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._compaction_job_row(job),
            )
        return job.model_dump(mode="json")

    def claim_next_compaction_job(self) -> dict[str, object] | None:
        with self._connect() as conn:
            self._ensure_compaction_job_table(conn)
            row = conn.execute(
                """
                SELECT job_id, source_session_id, current_message, preserved_tail_user_turns,
                       source_message_range_json, snapshot_message_count, compaction_profile_name,
                       enqueue_status,
                       status, enqueued_at, started_at, finished_at, queue_wait_ms,
                       compaction_llm_ms, persist_ms, source_range_end, write_applied,
                       result_reason, error_code, error_text
                FROM session_compaction_jobs
                WHERE status = 'queued'
                ORDER BY enqueued_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            started_at = datetime.now(timezone.utc)
            conn.execute(
                """
                UPDATE session_compaction_jobs
                SET status = 'running', started_at = ?
                WHERE job_id = ?
                """,
                (started_at.isoformat(), str(row[0])),
            )
            job_id = str(row[0])
        return self.get_compaction_job(job_id)

    def get_compaction_job(self, job_id: str) -> dict[str, object]:
        with self._connect() as conn:
            self._ensure_compaction_job_table(conn)
            row = conn.execute(
                """
                SELECT job_id, source_session_id, current_message, preserved_tail_user_turns,
                       source_message_range_json, snapshot_message_count, compaction_profile_name,
                       enqueue_status,
                       status, enqueued_at, started_at, finished_at, queue_wait_ms,
                       compaction_llm_ms, persist_ms, source_range_end, write_applied,
                       result_reason, error_code, error_text
                FROM session_compaction_jobs
                WHERE job_id = ?
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._job_from_row(row).model_dump(mode="json")

    def list_compaction_jobs(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            self._ensure_compaction_job_table(conn)
            rows = conn.execute(
                """
                SELECT job_id, source_session_id, current_message, preserved_tail_user_turns,
                       source_message_range_json, snapshot_message_count, compaction_profile_name,
                       enqueue_status,
                       status, enqueued_at, started_at, finished_at, queue_wait_ms,
                       compaction_llm_ms, persist_ms, source_range_end, write_applied,
                       result_reason, error_code, error_text
                FROM session_compaction_jobs
                ORDER BY enqueued_at ASC
                """
            ).fetchall()
        return [self._job_from_row(row).model_dump(mode="json") for row in rows]

    def reset_running_compaction_jobs(self) -> None:
        with self._connect() as conn:
            self._ensure_compaction_job_table(conn)
            conn.execute(
                """
                UPDATE session_compaction_jobs
                SET status = 'queued',
                    started_at = NULL,
                    finished_at = NULL,
                    result_reason = 'requeued_startup',
                    error_code = NULL,
                    error_text = NULL
                WHERE status = 'running'
                """
            )

    def mark_compaction_job_succeeded(
        self,
        job_id: str,
        *,
        queue_wait_ms: int,
        compaction_llm_ms: int,
        persist_ms: int,
        result_reason: str,
        source_range_end: int | None,
        write_applied: bool,
    ) -> dict[str, object]:
        finished_at = datetime.now(timezone.utc)
        with self._connect() as conn:
            self._ensure_compaction_job_table(conn)
            conn.execute(
                """
                UPDATE session_compaction_jobs
                SET status = 'succeeded',
                    finished_at = ?,
                    queue_wait_ms = ?,
                    compaction_llm_ms = ?,
                    persist_ms = ?,
                    source_range_end = ?,
                    write_applied = ?,
                    result_reason = ?,
                    error_code = NULL,
                    error_text = NULL
                WHERE job_id = ?
                """,
                (
                    finished_at.isoformat(),
                    max(0, int(queue_wait_ms)),
                    max(0, int(compaction_llm_ms)),
                    max(0, int(persist_ms)),
                    source_range_end,
                    1 if write_applied else 0,
                    result_reason,
                    job_id,
                ),
            )
        return self.get_compaction_job(job_id)

    def mark_compaction_job_failed(
        self,
        job_id: str,
        *,
        queue_wait_ms: int,
        compaction_llm_ms: int,
        persist_ms: int,
        result_reason: str,
        error_code: str | None = None,
        error_text: str | None = None,
    ) -> dict[str, object]:
        finished_at = datetime.now(timezone.utc)
        with self._connect() as conn:
            self._ensure_compaction_job_table(conn)
            conn.execute(
                """
                UPDATE session_compaction_jobs
                SET status = 'failed',
                    finished_at = ?,
                    queue_wait_ms = ?,
                    compaction_llm_ms = ?,
                    persist_ms = ?,
                    result_reason = ?,
                    error_code = ?,
                    error_text = ?,
                    write_applied = 0
                WHERE job_id = ?
                """,
                (
                    finished_at.isoformat(),
                    max(0, int(queue_wait_ms)),
                    max(0, int(compaction_llm_ms)),
                    max(0, int(persist_ms)),
                    result_reason,
                    error_code,
                    error_text,
                    job_id,
                ),
            )
        return self.get_compaction_job(job_id)

    def storage_kind(self) -> str:
        return "sqlite"

    def storage_path(self) -> str | None:
        return str(self.path)

    def _write_record(self, record: SessionRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, conversation_id, state, created_at, updated_at,
                    channel_id, user_id, agent_id, session_title, session_preview, message_count,
                    active_agent_id, parent_session_id, session_kind, lineage_depth,
                    config_snapshot_id, bootstrap_manifest_id, context_snapshot_id,
                    last_run_id, last_event_at, last_compacted_at,
                    latest_compacted_context_json, latest_actual_usage_json,
                    tool_call_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    conversation_id=excluded.conversation_id,
                    state=excluded.state,
                    updated_at=excluded.updated_at,
                    channel_id=excluded.channel_id,
                    user_id=excluded.user_id,
                    agent_id=excluded.agent_id,
                    session_title=excluded.session_title,
                    session_preview=excluded.session_preview,
                    message_count=excluded.message_count,
                    active_agent_id=excluded.active_agent_id,
                    parent_session_id=excluded.parent_session_id,
                    session_kind=excluded.session_kind,
                    lineage_depth=excluded.lineage_depth,
                    config_snapshot_id=excluded.config_snapshot_id,
                    bootstrap_manifest_id=excluded.bootstrap_manifest_id,
                    context_snapshot_id=excluded.context_snapshot_id,
                    last_run_id=excluded.last_run_id,
                    last_event_at=excluded.last_event_at,
                    last_compacted_at=excluded.last_compacted_at,
                    latest_compacted_context_json=excluded.latest_compacted_context_json,
                    latest_actual_usage_json=excluded.latest_actual_usage_json,
                    tool_call_count=excluded.tool_call_count
                """,
                (
                    record.session_id,
                    record.conversation_id,
                    record.state,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    record.channel_id,
                    record.user_id,
                    record.agent_id,
                    record.session_title,
                    record.session_preview,
                    record.message_count,
                    record.active_agent_id,
                    record.parent_session_id,
                    record.session_kind,
                    record.lineage_depth,
                    record.config_snapshot_id,
                    record.bootstrap_manifest_id,
                    record.context_snapshot_id,
                    record.last_run_id,
                    record.last_event_at.isoformat() if record.last_event_at is not None else None,
                    record.last_compacted_at.isoformat() if record.last_compacted_at is not None else None,
                    record.latest_compacted_context.model_dump_json(exclude_none=True)
                    if record.latest_compacted_context is not None
                    else None,
                    record.latest_actual_usage.model_dump_json()
                    if record.latest_actual_usage is not None
                    else None,
                    record.tool_call_count,
                ),
            )
            conn.execute(
                "DELETE FROM session_messages WHERE session_id = ?",
                (record.session_id,),
            )
            for index, message in enumerate(record.history):
                conn.execute(
                    """
                    INSERT INTO session_messages (
                        session_id, message_index, role, content,
                        created_at, received_at, enqueued_at, started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.session_id,
                        index,
                        message.role,
                        message.content,
                        message.created_at.isoformat(),
                        message.received_at.isoformat() if message.received_at is not None else None,
                        message.enqueued_at.isoformat() if message.enqueued_at is not None else None,
                        message.started_at.isoformat() if message.started_at is not None else None,
                    ),
                )
            conn.execute(
                "DELETE FROM session_tool_outcome_summaries WHERE session_id = ?",
                (record.session_id,),
            )
            for index, summary in enumerate(record.recent_tool_outcome_summaries):
                conn.execute(
                    """
                    INSERT INTO session_tool_outcome_summaries (
                        session_id, summary_index, created_at, tool_name, status, summary_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.session_id,
                        index,
                        summary.created_at.isoformat(),
                        summary.tool_name,
                        summary.source_kind,
                        summary.model_dump_json(),
                    ),
                )

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    channel_id TEXT NOT NULL DEFAULT '',
                    user_id TEXT NOT NULL DEFAULT '',
                    agent_id TEXT NOT NULL DEFAULT '',
                    session_title TEXT NOT NULL DEFAULT '',
                    session_preview TEXT NOT NULL DEFAULT '',
                    message_count INTEGER NOT NULL DEFAULT 0,
                    active_agent_id TEXT NOT NULL,
                    parent_session_id TEXT,
                    session_kind TEXT NOT NULL,
                    lineage_depth INTEGER NOT NULL,
                    config_snapshot_id TEXT NOT NULL,
                    bootstrap_manifest_id TEXT NOT NULL,
                    context_snapshot_id TEXT,
                    last_run_id TEXT,
                    last_event_at TEXT,
                    last_compacted_at TEXT,
                    latest_compacted_context_json TEXT,
                    latest_actual_usage_json TEXT,
                    tool_call_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._ensure_session_columns(conn)

    @staticmethod
    def _ensure_session_columns(conn: sqlite3.Connection) -> None:
        existing = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        required = {
            "channel_id": "TEXT NOT NULL DEFAULT ''",
            "user_id": "TEXT NOT NULL DEFAULT ''",
            "agent_id": "TEXT NOT NULL DEFAULT ''",
            "session_title": "TEXT NOT NULL DEFAULT ''",
            "session_preview": "TEXT NOT NULL DEFAULT ''",
            "message_count": "INTEGER NOT NULL DEFAULT 0",
            "active_agent_id": "TEXT NOT NULL DEFAULT 'main'",
            "parent_session_id": "TEXT",
            "session_kind": "TEXT NOT NULL DEFAULT 'main'",
            "lineage_depth": "INTEGER NOT NULL DEFAULT 0",
            "config_snapshot_id": "TEXT NOT NULL DEFAULT 'cfg_bootstrap'",
            "bootstrap_manifest_id": "TEXT NOT NULL DEFAULT 'boot_default'",
            "context_snapshot_id": "TEXT",
            "last_run_id": "TEXT",
            "last_event_at": "TEXT",
            "last_compacted_at": "TEXT",
            "latest_compacted_context_json": "TEXT",
            "latest_actual_usage_json": "TEXT",
            "tool_call_count": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, ddl in required.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {ddl}")
        conn.execute(
            """
            UPDATE sessions
            SET active_agent_id = agent_id
            WHERE TRIM(COALESCE(agent_id, '')) <> ''
              AND TRIM(COALESCE(agent_id, '')) <> 'main'
              AND TRIM(COALESCE(active_agent_id, '')) IN ('', 'main')
            """
        )
        conn.execute(
            """
            UPDATE sessions
            SET agent_id = ?, active_agent_id = ?
            WHERE LOWER(TRIM(COALESCE(agent_id, ''))) = 'assistant'
               OR LOWER(TRIM(COALESCE(active_agent_id, ''))) = 'assistant'
            """,
            (DEFAULT_AGENT_ID, DEFAULT_AGENT_ID),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_messages (
                session_id TEXT NOT NULL,
                message_index INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                received_at TEXT,
                enqueued_at TEXT,
                started_at TEXT,
                PRIMARY KEY (session_id, message_index)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_tool_outcome_summaries (
                session_id TEXT NOT NULL,
                summary_index INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                tool_name TEXT,
                status TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                PRIMARY KEY (session_id, summary_index)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_bindings (
                channel_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL,
                bound_at TEXT NOT NULL,
                PRIMARY KEY (channel_id, conversation_id, user_id)
            )
            """
        )
        SQLiteSessionStore._ensure_session_binding_columns(conn)
        SQLiteSessionStore._ensure_compaction_job_table(conn)

    @staticmethod
    def _ensure_session_binding_columns(conn: sqlite3.Connection) -> None:
        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(session_bindings)").fetchall()
        }
        primary_key_columns = [
            str(row[1])
            for row in sorted(
                conn.execute("PRAGMA table_info(session_bindings)").fetchall(),
                key=lambda item: int(item[5] or 0),
            )
            if int(row[5] or 0) > 0
        ]
        if columns == {"channel_id", "conversation_id", "user_id", "session_id", "bound_at"} and primary_key_columns == [
            "channel_id",
            "conversation_id",
            "user_id",
        ]:
            return
        conn.execute("ALTER TABLE session_bindings RENAME TO session_bindings_legacy")
        conn.execute(
            """
            CREATE TABLE session_bindings (
                channel_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL,
                bound_at TEXT NOT NULL,
                PRIMARY KEY (channel_id, conversation_id, user_id)
            )
            """
        )
        legacy_has_user_id = "user_id" in columns
        user_expr = (
            "COALESCE(NULLIF(b.user_id, ''), s.user_id, '')"
            if legacy_has_user_id
            else "COALESCE(s.user_id, '')"
        )
        conn.execute(
            f"""
            INSERT OR REPLACE INTO session_bindings (
                channel_id, conversation_id, user_id, session_id, bound_at
            )
            SELECT b.channel_id,
                   b.conversation_id,
                   {user_expr},
                   b.session_id,
                   b.bound_at
            FROM session_bindings_legacy b
            LEFT JOIN sessions s ON s.session_id = b.session_id
            """
        )
        conn.execute("DROP TABLE session_bindings_legacy")

    @staticmethod
    def _ensure_compaction_job_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_compaction_jobs (
                job_id TEXT PRIMARY KEY,
                source_session_id TEXT NOT NULL,
                current_message TEXT NOT NULL,
                preserved_tail_user_turns INTEGER NOT NULL,
                source_message_range_json TEXT NOT NULL,
                snapshot_message_count INTEGER NOT NULL DEFAULT 0,
                compaction_profile_name TEXT,
                enqueue_status TEXT NOT NULL DEFAULT 'queued',
                status TEXT NOT NULL DEFAULT 'queued',
                enqueued_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                queue_wait_ms INTEGER NOT NULL DEFAULT 0,
                compaction_llm_ms INTEGER NOT NULL DEFAULT 0,
                persist_ms INTEGER NOT NULL DEFAULT 0,
                source_range_end INTEGER,
                write_applied INTEGER NOT NULL DEFAULT 0,
                result_reason TEXT,
                error_code TEXT,
                error_text TEXT
            )
            """
        )
        existing = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(session_compaction_jobs)").fetchall()
        }
        if "compaction_profile_name" not in existing:
            conn.execute(
                "ALTER TABLE session_compaction_jobs ADD COLUMN compaction_profile_name TEXT"
            )

    @staticmethod
    def _record_from_session_row(
        row: sqlite3.Row | tuple,
        *,
        include_payloads: bool = True,
    ) -> SessionRecord:
        return SessionRecord(
            session_id=str(row[0]),
            conversation_id=str(row[1]),
            state=str(row[2]),
            created_at=datetime.fromisoformat(str(row[3])),
            updated_at=datetime.fromisoformat(str(row[4])),
            channel_id=str(row[5] or ""),
            user_id=str(row[6] or ""),
            agent_id=str(row[7] or ""),
            session_title=str(row[8] or ""),
            session_preview=str(row[9] or ""),
            message_count=int(row[10]),
            active_agent_id=str(row[11]),
            parent_session_id=str(row[12]) if row[12] is not None else None,
            session_kind=str(row[13]),
            lineage_depth=int(row[14]),
            config_snapshot_id=str(row[15]),
            bootstrap_manifest_id=str(row[16]),
            context_snapshot_id=str(row[17]) if row[17] is not None else None,
            last_run_id=str(row[18]) if row[18] is not None else None,
            last_event_at=datetime.fromisoformat(str(row[19])) if row[19] is not None else None,
            last_compacted_at=datetime.fromisoformat(str(row[20])) if row[20] is not None else None,
            latest_compacted_context=(
                CompactedContext.model_validate_json(str(row[21]))
                if include_payloads and row[21] is not None
                else None
            ),
            latest_actual_usage=(
                NormalizedUsage.model_validate_json(str(row[22]))
                if include_payloads and row[22] is not None
                else None
            ),
            tool_call_count=int(row[23]),
        )

    @staticmethod
    def _compaction_job_row(job: SessionCompactionJob) -> tuple[object, ...]:
        return (
            job.job_id,
            job.source_session_id,
            job.current_message,
            job.preserved_tail_user_turns,
            str(job.source_message_range),
            job.snapshot_message_count,
            job.compaction_profile_name,
            job.enqueue_status,
            job.status,
            job.enqueued_at.isoformat(),
            job.started_at.isoformat() if job.started_at is not None else None,
            job.finished_at.isoformat() if job.finished_at is not None else None,
            job.queue_wait_ms,
            job.compaction_llm_ms,
            job.persist_ms,
            job.source_range_end,
            1 if job.write_applied else 0,
            job.result_reason,
            job.error_code,
            job.error_text,
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row | tuple) -> SessionCompactionJob:
        import ast

        return SessionCompactionJob(
            job_id=str(row[0]),
            source_session_id=str(row[1]),
            current_message=str(row[2]),
            preserved_tail_user_turns=int(row[3]),
            source_message_range=list(ast.literal_eval(str(row[4]))),
            snapshot_message_count=int(row[5]),
            compaction_profile_name=str(row[6]) if row[6] is not None else None,
            enqueue_status=str(row[7]),
            status=str(row[8]),
            enqueued_at=datetime.fromisoformat(str(row[9])),
            started_at=datetime.fromisoformat(str(row[10])) if row[10] is not None else None,
            finished_at=datetime.fromisoformat(str(row[11])) if row[11] is not None else None,
            queue_wait_ms=int(row[12]),
            compaction_llm_ms=int(row[13]),
            persist_ms=int(row[14]),
            source_range_end=int(row[15]) if row[15] is not None else None,
            write_applied=bool(int(row[16])),
            result_reason=str(row[17]) if row[17] is not None else None,
            error_code=str(row[18]) if row[18] is not None else None,
            error_text=str(row[19]) if row[19] is not None else None,
        )
