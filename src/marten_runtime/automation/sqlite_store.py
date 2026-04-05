from __future__ import annotations

import sqlite3
from pathlib import Path

from marten_runtime.automation.models import AutomationJob, build_automation_semantic_fingerprint
from marten_runtime.automation.skill_ids import GITHUB_TRENDING_DIGEST_SKILL_ID
from marten_runtime.automation.store import AutomationStore, _is_equivalent_registration, _normalize_automation_values

GITHUB_TRENDING_DIGEST_DISPLAY_NAME = "GitHub热榜推荐"


class SQLiteAutomationStore(AutomationStore):
    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def list_enabled(self) -> list[AutomationJob]:
        return [item for item in self.list_all() if item.enabled]

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

    def find_equivalent_registration(self, payload: dict[str, str]) -> AutomationJob | None:
        for item in self.list_enabled():
            if _is_equivalent_registration(item, payload):
                return item
        return None

    def update(self, automation_id: str, updates: dict[str, object]) -> AutomationJob:
        current = self.get(automation_id)
        merged = current.model_copy(update=_normalize_automation_values(updates))
        merged.semantic_fingerprint = build_automation_semantic_fingerprint(merged)
        self.save(merged)
        return merged

    def set_enabled(self, automation_id: str, enabled: bool) -> AutomationJob:
        return self.update(automation_id, {"enabled": enabled})

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

    def record_dispatched_window(
        self,
        *,
        automation_id: str,
        scheduled_for: str,
        delivery_target: str,
        dedupe_key: str,
    ) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO automation_dispatch_windows (
                        automation_id, scheduled_for, delivery_target, dedupe_key
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (automation_id, scheduled_for, delivery_target, dedupe_key),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def has_dispatched_window(self, automation_id: str, scheduled_for: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM automation_dispatch_windows
                WHERE automation_id = ? AND scheduled_for = ?
                LIMIT 1
                """,
                (automation_id, scheduled_for),
            ).fetchone()
        return row is not None

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS automation_dispatch_windows (
                    automation_id TEXT NOT NULL,
                    scheduled_for TEXT NOT NULL,
                    delivery_target TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    PRIMARY KEY (automation_id, scheduled_for)
                )
                """
            )
            self._migrate_legacy_github_digest_rows(conn)

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

    def _migrate_legacy_github_digest_rows(self, conn: sqlite3.Connection) -> None:
        legacy_skill_id = _legacy_github_digest_skill_id()
        rows = conn.execute(
            """
            SELECT automation_id, name, app_id, agent_id, prompt_template,
                   schedule_kind, schedule_expr, timezone, session_target,
                   delivery_channel, delivery_target, skill_id, enabled, internal, semantic_fingerprint
            FROM automations
            WHERE skill_id = ? OR automation_id = ? OR automation_id LIKE ?
            ORDER BY automation_id
            """,
            (
                legacy_skill_id,
                legacy_skill_id,
                f"{legacy_skill_id}_%",
            ),
        ).fetchall()
        for row in rows:
            current = self._row_to_job(row)
            target_id = _migrated_github_trending_automation_id(current.automation_id)
            migrated = current.model_copy(
                update={
                    "automation_id": target_id,
                    "name": _migrated_github_trending_name(current.name, current.automation_id),
                    "skill_id": GITHUB_TRENDING_DIGEST_SKILL_ID,
                }
            )
            migrated.semantic_fingerprint = build_automation_semantic_fingerprint(migrated)
            if target_id != current.automation_id:
                self._migrate_dispatch_windows(conn, source_id=current.automation_id, target_id=target_id)
            self._upsert_migrated_automation(conn, source_id=current.automation_id, job=migrated)

    def _upsert_migrated_automation(
        self,
        conn: sqlite3.Connection,
        *,
        source_id: str,
        job: AutomationJob,
    ) -> None:
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
        if source_id != job.automation_id:
            conn.execute("DELETE FROM automations WHERE automation_id = ?", (source_id,))

    def _migrate_dispatch_windows(self, conn: sqlite3.Connection, *, source_id: str, target_id: str) -> None:
        rows = conn.execute(
            """
            SELECT scheduled_for, delivery_target, dedupe_key
            FROM automation_dispatch_windows
            WHERE automation_id = ?
            ORDER BY scheduled_for
            """,
            (source_id,),
        ).fetchall()
        for scheduled_for, delivery_target, dedupe_key in rows:
            conn.execute(
                """
                INSERT OR IGNORE INTO automation_dispatch_windows (
                    automation_id, scheduled_for, delivery_target, dedupe_key
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    target_id,
                    str(scheduled_for),
                    str(delivery_target),
                    str(dedupe_key).replace(source_id, target_id),
                ),
            )
        conn.execute("DELETE FROM automation_dispatch_windows WHERE automation_id = ?", (source_id,))


def _legacy_github_digest_skill_id() -> str:
    return GITHUB_TRENDING_DIGEST_SKILL_ID.replace("trending", "hot_repos")


def _migrated_github_trending_automation_id(automation_id: str) -> str:
    legacy_skill_id = _legacy_github_digest_skill_id()
    if automation_id == legacy_skill_id:
        return GITHUB_TRENDING_DIGEST_SKILL_ID
    if automation_id.startswith(f"{legacy_skill_id}_"):
        return automation_id.replace(legacy_skill_id, GITHUB_TRENDING_DIGEST_SKILL_ID, 1)
    return automation_id


def _migrated_github_trending_name(name: str, automation_id: str) -> str:
    normalized = str(name).strip()
    default_names = {
        "",
        automation_id,
        _legacy_github_digest_skill_id(),
        _migrated_github_trending_automation_id(automation_id),
        GITHUB_TRENDING_DIGEST_SKILL_ID,
    }
    if normalized in default_names or _looks_like_legacy_github_top_name(normalized):
        return GITHUB_TRENDING_DIGEST_DISPLAY_NAME
    return normalized


def _looks_like_legacy_github_top_name(name: str) -> bool:
    normalized = " ".join(str(name).strip().casefold().split())
    return normalized.startswith("github") and normalized.endswith("top10")
