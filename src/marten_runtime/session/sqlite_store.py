from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage, SessionRecord
from marten_runtime.session.store import SessionStore
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
    ) -> SessionRecord:
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            session_id=session_id,
            conversation_id=conversation_id,
            channel_id=channel_id,
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
        )
        return self.get(session_id)

    def create_child_session(
        self,
        *,
        parent_session_id: str,
        conversation_id: str,
        session_id: str | None = None,
    ) -> SessionRecord:
        parent = self.get(parent_session_id)
        now = datetime.now(timezone.utc)
        child = SessionRecord(
            session_id=session_id or f"sess_{uuid4().hex[:8]}",
            conversation_id=conversation_id,
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
            channel_id="",
            conversation_id=conversation_id,
            session_id=child.session_id,
        )
        return self.get(child.session_id)

    def get_or_create_for_conversation(
        self,
        conversation_id: str,
        config_snapshot_id: str = "cfg_bootstrap",
        bootstrap_manifest_id: str = "boot_default",
        *,
        channel_id: str = "",
    ) -> SessionRecord:
        session_id = self.resolve_session_for_conversation(
            channel_id=channel_id,
            conversation_id=conversation_id,
        )
        if session_id is not None:
            return self.get(session_id)
        return self.create(
            session_id=f"sess_{uuid4().hex[:8]}",
            conversation_id=conversation_id,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id=bootstrap_manifest_id,
            channel_id=channel_id,
        )

    def append_message(self, session_id: str, message: SessionMessage) -> SessionRecord:
        record = self.get(session_id)
        record.history.append(message)
        self._refresh_message_count(record)
        record.updated_at = message.created_at
        record.last_event_at = message.created_at
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
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM session_bindings
                WHERE session_id = ?
                  AND NOT (channel_id = ? AND conversation_id = ?)
                """,
                (session_id, channel_id, conversation_id),
            )
            conn.execute(
                """
                INSERT INTO session_bindings (channel_id, conversation_id, session_id, bound_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_id, conversation_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    bound_at=excluded.bound_at
                """,
                (
                    channel_id,
                    conversation_id,
                    session_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.execute(
                """
                UPDATE sessions
                SET conversation_id = ?, channel_id = ?
                WHERE session_id = ?
                """,
                (conversation_id, channel_id, session_id),
            )

    def resolve_session_for_conversation(
        self,
        *,
        channel_id: str,
        conversation_id: str,
    ) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id
                FROM session_bindings
                WHERE channel_id = ? AND conversation_id = ?
                LIMIT 1
                """,
                (channel_id, conversation_id),
            ).fetchone()
            if row is not None:
                return str(row[0])
            if channel_id:
                return None
            row = conn.execute(
                """
                SELECT session_id
                FROM sessions
                WHERE conversation_id = ?
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
                    record.latest_compacted_context.model_dump_json()
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
        }
        for name, ddl in required.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {ddl}")
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
                session_id TEXT NOT NULL,
                bound_at TEXT NOT NULL,
                PRIMARY KEY (channel_id, conversation_id)
            )
            """
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
