from __future__ import annotations

import sqlite3
from pathlib import Path

from marten_runtime.automation.models import (
    AutomationJob,
    build_automation_semantic_fingerprint,
)
from marten_runtime.automation.store import AutomationStore
from marten_runtime.sqlite_support import connect_sqlite, prepare_sqlite_path

class SQLiteAutomationStore(AutomationStore):
    def __init__(self, path: str | Path) -> None:
        self.path = prepare_sqlite_path(path)
        self._init_schema()

    def save(self, job: AutomationJob) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO automations (
                    automation_id, name, app_id, agent_id, prompt_template,
                    schedule_kind, schedule_expr, timezone, session_target,
                    delivery_channel, delivery_target, skill_id, enabled, internal, semantic_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(automation_id) DO UPDATE SET
                    name=excluded.name,
                    app_id=excluded.app_id,
                    agent_id=excluded.agent_id,
                    prompt_template=excluded.prompt_template,
                    schedule_kind=excluded.schedule_kind,
                    schedule_expr=excluded.schedule_expr,
                    timezone=excluded.timezone,
                    session_target=excluded.session_target,
                    delivery_channel=excluded.delivery_channel,
                    delivery_target=excluded.delivery_target,
                    skill_id=excluded.skill_id,
                    enabled=excluded.enabled,
                    internal=excluded.internal,
                    semantic_fingerprint=excluded.semantic_fingerprint
                """,
                (
                    job.automation_id,
                    job.name,
                    job.app_id,
                    job.agent_id,
                    job.prompt_template,
                    job.schedule_kind,
                    job.schedule_expr,
                    job.timezone,
                    job.session_target,
                    job.delivery_channel,
                    job.delivery_target,
                    job.skill_id,
                    int(job.enabled),
                    int(job.internal),
                    job.semantic_fingerprint,
                ),
            )

    def list_all(self) -> list[AutomationJob]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT automation_id, name, app_id, agent_id, prompt_template,
                       schedule_kind, schedule_expr, timezone, session_target,
                       delivery_channel, delivery_target, skill_id, enabled, internal, semantic_fingerprint
                FROM automations
                ORDER BY automation_id
                """
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def get(self, automation_id: str) -> AutomationJob:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT automation_id, name, app_id, agent_id, prompt_template,
                       schedule_kind, schedule_expr, timezone, session_target,
                       delivery_channel, delivery_target, skill_id, enabled, internal, semantic_fingerprint
                FROM automations
                WHERE automation_id = ?
                LIMIT 1
                """,
                (automation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(automation_id)
        return self._row_to_job(row)

    def delete(self, automation_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM automations
                WHERE automation_id = ?
                """,
                (automation_id,),
            )
        return cursor.rowcount > 0

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS automations (
                    automation_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    app_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    prompt_template TEXT NOT NULL,
                    schedule_kind TEXT NOT NULL,
                    schedule_expr TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    session_target TEXT NOT NULL,
                    delivery_channel TEXT NOT NULL,
                    delivery_target TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    internal INTEGER NOT NULL DEFAULT 0,
                    semantic_fingerprint TEXT NOT NULL DEFAULT ''
                )
                """
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(automations)").fetchall()
            }
            if "semantic_fingerprint" not in columns:
                conn.execute(
                    """
                    ALTER TABLE automations
                    ADD COLUMN semantic_fingerprint TEXT NOT NULL DEFAULT ''
                    """
                )
            if "internal" not in columns:
                conn.execute(
                    """
                    ALTER TABLE automations
                    ADD COLUMN internal INTEGER NOT NULL DEFAULT 0
                    """
                )
            legacy_rows = conn.execute(
                """
                SELECT automation_id, name, app_id, agent_id, prompt_template,
                       schedule_kind, schedule_expr, timezone, session_target,
                       delivery_channel, delivery_target, skill_id, enabled, internal, semantic_fingerprint
                FROM automations
                WHERE LOWER(TRIM(COALESCE(agent_id, ''))) = 'assistant'
                """
            ).fetchall()
            for row in legacy_rows:
                job = self._row_to_job(row)
                job.semantic_fingerprint = build_automation_semantic_fingerprint(job)
                conn.execute(
                    """
                    UPDATE automations
                    SET agent_id = ?, semantic_fingerprint = ?
                    WHERE automation_id = ?
                    """,
                    (job.agent_id, job.semantic_fingerprint, job.automation_id),
                )
    def _row_to_job(self, row: tuple[object, ...]) -> AutomationJob:
        return AutomationJob(
            automation_id=str(row[0]),
            name=str(row[1]),
            app_id=str(row[2]),
            agent_id=str(row[3]),
            prompt_template=str(row[4]),
            schedule_kind=str(row[5]),
            schedule_expr=str(row[6]),
            timezone=str(row[7]),
            session_target=str(row[8]),
            delivery_channel=str(row[9]),
            delivery_target=str(row[10]),
            skill_id=str(row[11]),
            enabled=bool(row[12]),
            internal=bool(row[13]),
            semantic_fingerprint=str(row[14] or ""),
        )
