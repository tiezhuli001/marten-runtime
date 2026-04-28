from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from marten_runtime.apps.runtime_defaults import DEFAULT_AGENT_ID
from marten_runtime.self_improve.models import (
    FailureEvent,
    LessonCandidate,
    RecoveryEvent,
    ReviewTrigger,
    SkillCandidate,
    SystemLesson,
)
from marten_runtime.sqlite_support import connect_sqlite, prepare_sqlite_path


class SQLiteSelfImproveStore:
    def __init__(self, path: str | Path) -> None:
        self.path = prepare_sqlite_path(path)
        self._lock = threading.RLock()
        self._init_schema()

    def record_failure(self, event: FailureEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runtime_failure_events (
                    failure_id, agent_id, run_id, trace_id, session_id, error_code,
                    error_stage, tool_name, provider_name, summary, fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.failure_id,
                    event.agent_id,
                    event.run_id,
                    event.trace_id,
                    event.session_id,
                    event.error_code,
                    event.error_stage,
                    event.tool_name,
                    event.provider_name,
                    event.summary,
                    event.fingerprint,
                    event.created_at.isoformat(),
                ),
            )

    def list_recent_failures(self, *, agent_id: str, limit: int) -> list[FailureEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT failure_id, agent_id, run_id, trace_id, session_id, error_code,
                       error_stage, tool_name, provider_name, summary, fingerprint, created_at
                FROM runtime_failure_events
                WHERE agent_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_id, limit),
            ).fetchall()
        return [self._row_to_failure(row) for row in rows]

    def record_recovery(self, event: RecoveryEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runtime_recovery_events (
                    recovery_id, agent_id, run_id, trace_id, related_failure_fingerprint,
                    recovery_kind, fix_summary, success_evidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.recovery_id,
                    event.agent_id,
                    event.run_id,
                    event.trace_id,
                    event.related_failure_fingerprint,
                    event.recovery_kind,
                    event.fix_summary,
                    event.success_evidence,
                    event.created_at.isoformat(),
                ),
            )

    def list_recent_recoveries(self, *, agent_id: str, limit: int) -> list[RecoveryEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT recovery_id, agent_id, run_id, trace_id, related_failure_fingerprint,
                       recovery_kind, fix_summary, success_evidence, created_at
                FROM runtime_recovery_events
                WHERE agent_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_id, limit),
            ).fetchall()
        return [self._row_to_recovery(row) for row in rows]

    def save_candidate(self, candidate: LessonCandidate) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO lesson_candidates (
                    candidate_id, agent_id, source_fingerprints, candidate_text,
                    rationale, status, score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    candidate.agent_id,
                    json.dumps(candidate.source_fingerprints),
                    candidate.candidate_text,
                    candidate.rationale,
                    candidate.status,
                    candidate.score,
                    candidate.created_at.isoformat(),
                ),
            )

    def update_candidate_status(self, candidate_id: str, *, status: str) -> LessonCandidate:
        candidate = self.get_candidate(candidate_id)
        updated = candidate.model_copy(update={"status": status})
        self.save_candidate(updated)
        return updated

    def list_candidates(
        self,
        *,
        agent_id: str,
        limit: int,
        status: str | None = None,
    ) -> list[LessonCandidate]:
        query = """
            SELECT candidate_id, agent_id, source_fingerprints, candidate_text,
                   rationale, status, score, created_at
            FROM lesson_candidates
            WHERE agent_id = ?
        """
        params: list[object] = [agent_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_candidate(row) for row in rows]

    def latest_candidate(self, *, agent_id: str, status: str | None = None) -> LessonCandidate | None:
        query = """
            SELECT candidate_id, agent_id, source_fingerprints, candidate_text,
                   rationale, status, score, created_at
            FROM lesson_candidates
            WHERE agent_id = ?
        """
        params: list[object] = [agent_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return self._row_to_candidate(row) if row is not None else None

    def get_candidate(self, candidate_id: str) -> LessonCandidate:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT candidate_id, agent_id, source_fingerprints, candidate_text,
                       rationale, status, score, created_at
                FROM lesson_candidates
                WHERE candidate_id = ?
                LIMIT 1
                """,
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return self._row_to_candidate(row)

    def delete_candidate(self, candidate_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM lesson_candidates
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            )
        return cursor.rowcount > 0

    def save_lesson(self, lesson: SystemLesson) -> None:
        with self._connect() as conn:
            if lesson.active:
                conn.execute(
                    """
                    UPDATE system_lessons
                    SET active = 0, superseded_at = ?
                    WHERE agent_id = ? AND topic_key = ? AND active = 1
                    """,
                    (
                        lesson.created_at.isoformat(),
                        lesson.agent_id,
                        lesson.topic_key,
                    ),
                )
            conn.execute(
                """
                INSERT OR REPLACE INTO system_lessons (
                    lesson_id, agent_id, topic_key, lesson_text, source_fingerprints,
                    active, created_at, superseded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lesson.lesson_id,
                    lesson.agent_id,
                    lesson.topic_key,
                    lesson.lesson_text,
                    json.dumps(lesson.source_fingerprints),
                    int(lesson.active),
                    lesson.created_at.isoformat(),
                    lesson.superseded_at.isoformat() if lesson.superseded_at else None,
                ),
            )

    def list_active_lessons(self, *, agent_id: str) -> list[SystemLesson]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT lesson_id, agent_id, topic_key, lesson_text, source_fingerprints,
                       active, created_at, superseded_at
                FROM system_lessons
                WHERE agent_id = ? AND active = 1
                ORDER BY created_at DESC
                """,
                (agent_id,),
            ).fetchall()
        return [self._row_to_lesson(row) for row in rows]

    def latest_active_lesson(self, *, agent_id: str) -> SystemLesson | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT lesson_id, agent_id, topic_key, lesson_text, source_fingerprints,
                       active, created_at, superseded_at
                FROM system_lessons
                WHERE agent_id = ? AND active = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (agent_id,),
            ).fetchone()
        return self._row_to_lesson(row) if row is not None else None

    def get_lesson(self, lesson_id: str) -> SystemLesson:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT lesson_id, agent_id, topic_key, lesson_text, source_fingerprints,
                       active, created_at, superseded_at
                FROM system_lessons
                WHERE lesson_id = ?
                LIMIT 1
                """,
                (lesson_id,),
            ).fetchone()
        if row is None:
            raise KeyError(lesson_id)
        return self._row_to_lesson(row)

    def save_review_trigger(self, trigger: ReviewTrigger) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO review_triggers (
                    trigger_id, agent_id, trigger_kind, source_run_id, source_trace_id,
                    source_fingerprints, status, payload_json, semantic_fingerprint,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trigger.trigger_id,
                    trigger.agent_id,
                    trigger.trigger_kind,
                    trigger.source_run_id,
                    trigger.source_trace_id,
                    json.dumps(trigger.source_fingerprints),
                    trigger.status,
                    json.dumps(trigger.payload_json),
                    trigger.semantic_fingerprint,
                    trigger.created_at.isoformat(),
                    trigger.updated_at.isoformat(),
                ),
            )

    def create_review_trigger_if_absent(self, trigger: ReviewTrigger) -> ReviewTrigger | None:
        with self._lock:
            with self._connect() as conn:
                try:
                    conn.execute(
                        """
                        INSERT INTO review_triggers (
                            trigger_id, agent_id, trigger_kind, source_run_id, source_trace_id,
                            source_fingerprints, status, payload_json, semantic_fingerprint,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            trigger.trigger_id,
                            trigger.agent_id,
                            trigger.trigger_kind,
                            trigger.source_run_id,
                            trigger.source_trace_id,
                            json.dumps(trigger.source_fingerprints),
                            trigger.status,
                            json.dumps(trigger.payload_json),
                            trigger.semantic_fingerprint,
                            trigger.created_at.isoformat(),
                            trigger.updated_at.isoformat(),
                        ),
                    )
                except sqlite3.IntegrityError:
                    return None
        return trigger

    def get_review_trigger(self, trigger_id: str) -> ReviewTrigger:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT trigger_id, agent_id, trigger_kind, source_run_id, source_trace_id,
                       source_fingerprints, status, payload_json, semantic_fingerprint,
                       created_at, updated_at
                FROM review_triggers
                WHERE trigger_id = ?
                LIMIT 1
                """,
                (trigger_id,),
            ).fetchone()
        if row is None:
            raise KeyError(trigger_id)
        return self._row_to_review_trigger(row)

    def list_review_triggers(
        self,
        *,
        agent_id: str,
        limit: int,
        status: str | None = None,
    ) -> list[ReviewTrigger]:
        query = """
            SELECT trigger_id, agent_id, trigger_kind, source_run_id, source_trace_id,
                   source_fingerprints, status, payload_json, semantic_fingerprint,
                   created_at, updated_at
            FROM review_triggers
            WHERE agent_id = ?
        """
        params: list[object] = [agent_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_review_trigger(row) for row in rows]

    def latest_review_trigger_by_semantic_fingerprint(
        self,
        *,
        agent_id: str,
        semantic_fingerprint: str,
        status: str | None = None,
    ) -> ReviewTrigger | None:
        query = """
            SELECT trigger_id, agent_id, trigger_kind, source_run_id, source_trace_id,
                   source_fingerprints, status, payload_json, semantic_fingerprint,
                   created_at, updated_at
            FROM review_triggers
            WHERE agent_id = ? AND semantic_fingerprint = ?
        """
        params: list[object] = [agent_id, semantic_fingerprint]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return self._row_to_review_trigger(row) if row is not None else None

    def latest_review_trigger(self, *, agent_id: str, status: str | None = None) -> ReviewTrigger | None:
        query = """
            SELECT trigger_id, agent_id, trigger_kind, source_run_id, source_trace_id,
                   source_fingerprints, status, payload_json, semantic_fingerprint,
                   created_at, updated_at
            FROM review_triggers
            WHERE agent_id = ?
        """
        params: list[object] = [agent_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return self._row_to_review_trigger(row) if row is not None else None

    def update_review_trigger_status(self, trigger_id: str, *, status: str) -> ReviewTrigger:
        trigger = self.get_review_trigger(trigger_id)
        updated = trigger.model_copy(
            update={"status": status, "updated_at": datetime.now(timezone.utc)}
        )
        self.save_review_trigger(updated)
        return updated

    def save_skill_candidate(self, candidate: SkillCandidate) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO skill_candidates (
                    candidate_id, agent_id, status, title, slug, summary,
                    trigger_conditions, body_markdown, rationale, source_run_ids,
                    source_fingerprints, confidence, semantic_fingerprint,
                    created_at, reviewed_at, promoted_skill_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    candidate.agent_id,
                    candidate.status,
                    candidate.title,
                    candidate.slug,
                    candidate.summary,
                    json.dumps(candidate.trigger_conditions),
                    candidate.body_markdown,
                    candidate.rationale,
                    json.dumps(candidate.source_run_ids),
                    json.dumps(candidate.source_fingerprints),
                    candidate.confidence,
                    candidate.semantic_fingerprint,
                    candidate.created_at.isoformat(),
                    candidate.reviewed_at.isoformat() if candidate.reviewed_at else None,
                    candidate.promoted_skill_id,
                ),
            )

    def get_skill_candidate(self, candidate_id: str) -> SkillCandidate:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT candidate_id, agent_id, status, title, slug, summary,
                       trigger_conditions, body_markdown, rationale, source_run_ids,
                       source_fingerprints, confidence, semantic_fingerprint,
                       created_at, reviewed_at, promoted_skill_id
                FROM skill_candidates
                WHERE candidate_id = ?
                LIMIT 1
                """,
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return self._row_to_skill_candidate(row)

    def list_skill_candidates(
        self,
        *,
        agent_id: str,
        limit: int,
        status: str | None = None,
    ) -> list[SkillCandidate]:
        query = """
            SELECT candidate_id, agent_id, status, title, slug, summary,
                   trigger_conditions, body_markdown, rationale, source_run_ids,
                   source_fingerprints, confidence, semantic_fingerprint,
                   created_at, reviewed_at, promoted_skill_id
            FROM skill_candidates
            WHERE agent_id = ?
        """
        params: list[object] = [agent_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_skill_candidate(row) for row in rows]

    def latest_skill_candidate_by_semantic_fingerprint(
        self,
        *,
        agent_id: str,
        semantic_fingerprint: str,
        status: str | None = None,
    ) -> SkillCandidate | None:
        query = """
            SELECT candidate_id, agent_id, status, title, slug, summary,
                   trigger_conditions, body_markdown, rationale, source_run_ids,
                   source_fingerprints, confidence, semantic_fingerprint,
                   created_at, reviewed_at, promoted_skill_id
            FROM skill_candidates
            WHERE agent_id = ? AND semantic_fingerprint = ?
        """
        params: list[object] = [agent_id, semantic_fingerprint]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return self._row_to_skill_candidate(row) if row is not None else None

    def update_skill_candidate_status(
        self,
        candidate_id: str,
        *,
        status: str,
    ) -> SkillCandidate:
        candidate = self.get_skill_candidate(candidate_id)
        updated = candidate.model_copy(
            update={"status": status, "reviewed_at": datetime.now(timezone.utc)}
        )
        self.save_skill_candidate(updated)
        return updated

    def update_skill_candidate(
        self,
        candidate_id: str,
        *,
        title: str | None = None,
        slug: str | None = None,
        summary: str | None = None,
        trigger_conditions: list[str] | None = None,
        body_markdown: str | None = None,
        rationale: str | None = None,
        semantic_fingerprint: str | None = None,
    ) -> SkillCandidate:
        candidate = self.get_skill_candidate(candidate_id)
        updated = candidate.model_copy(
            update={
                "title": title if title is not None else candidate.title,
                "slug": slug if slug is not None else candidate.slug,
                "summary": summary if summary is not None else candidate.summary,
                "trigger_conditions": (
                    trigger_conditions
                    if trigger_conditions is not None
                    else candidate.trigger_conditions
                ),
                "body_markdown": (
                    body_markdown if body_markdown is not None else candidate.body_markdown
                ),
                "rationale": rationale if rationale is not None else candidate.rationale,
                "semantic_fingerprint": (
                    semantic_fingerprint
                    if semantic_fingerprint is not None
                    else candidate.semantic_fingerprint
                ),
            }
        )
        self.save_skill_candidate(updated)
        return updated

    def mark_skill_candidate_promoted(
        self,
        candidate_id: str,
        *,
        promoted_skill_id: str,
    ) -> SkillCandidate:
        candidate = self.get_skill_candidate(candidate_id)
        updated = candidate.model_copy(
            update={
                "status": "promoted",
                "promoted_skill_id": promoted_skill_id,
                "reviewed_at": datetime.now(timezone.utc),
            }
        )
        self.save_skill_candidate(updated)
        return updated

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_failure_events (
                    failure_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    error_code TEXT NOT NULL,
                    error_stage TEXT NOT NULL,
                    tool_name TEXT,
                    provider_name TEXT,
                    summary TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_recovery_events (
                    recovery_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    related_failure_fingerprint TEXT NOT NULL,
                    recovery_kind TEXT NOT NULL,
                    fix_summary TEXT NOT NULL,
                    success_evidence TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lesson_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    source_fingerprints TEXT NOT NULL,
                    candidate_text TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_lessons (
                    lesson_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    topic_key TEXT NOT NULL,
                    lesson_text TEXT NOT NULL,
                    source_fingerprints TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    superseded_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_triggers (
                    trigger_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    trigger_kind TEXT NOT NULL,
                    source_run_id TEXT NOT NULL,
                    source_trace_id TEXT NOT NULL,
                    source_fingerprints TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    semantic_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_review_triggers_active_semantic
                ON review_triggers (agent_id, semantic_fingerprint)
                WHERE status IN ('pending', 'queued', 'running')
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    trigger_conditions TEXT NOT NULL,
                    body_markdown TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    source_run_ids TEXT NOT NULL,
                    source_fingerprints TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    semantic_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    promoted_skill_id TEXT
                )
                """
            )
            for table in (
                "runtime_failure_events",
                "runtime_recovery_events",
                "lesson_candidates",
                "system_lessons",
                "review_triggers",
                "skill_candidates",
            ):
                conn.execute(
                    f"""
                    UPDATE {table}
                    SET agent_id = ?
                    WHERE LOWER(TRIM(COALESCE(agent_id, ''))) = 'assistant'
                    """,
                    (DEFAULT_AGENT_ID,),
                )

    def _row_to_failure(self, row: tuple[object, ...]) -> FailureEvent:
        return FailureEvent(
            failure_id=str(row[0]),
            agent_id=str(row[1]),
            run_id=str(row[2]),
            trace_id=str(row[3]),
            session_id=str(row[4]),
            error_code=str(row[5]),
            error_stage=str(row[6]),
            tool_name=str(row[7]) if row[7] is not None else None,
            provider_name=str(row[8]) if row[8] is not None else None,
            summary=str(row[9]),
            fingerprint=str(row[10]),
            created_at=str(row[11]),
        )

    def _row_to_recovery(self, row: tuple[object, ...]) -> RecoveryEvent:
        return RecoveryEvent(
            recovery_id=str(row[0]),
            agent_id=str(row[1]),
            run_id=str(row[2]),
            trace_id=str(row[3]),
            related_failure_fingerprint=str(row[4]),
            recovery_kind=str(row[5]),
            fix_summary=str(row[6]),
            success_evidence=str(row[7]),
            created_at=str(row[8]),
        )

    def _row_to_candidate(self, row: tuple[object, ...]) -> LessonCandidate:
        return LessonCandidate(
            candidate_id=str(row[0]),
            agent_id=str(row[1]),
            source_fingerprints=list(json.loads(str(row[2]))),
            candidate_text=str(row[3]),
            rationale=str(row[4]),
            status=str(row[5]),
            score=float(row[6]),
            created_at=str(row[7]),
        )

    def _row_to_lesson(self, row: tuple[object, ...]) -> SystemLesson:
        return SystemLesson(
            lesson_id=str(row[0]),
            agent_id=str(row[1]),
            topic_key=str(row[2]),
            lesson_text=str(row[3]),
            source_fingerprints=list(json.loads(str(row[4]))),
            active=bool(row[5]),
            created_at=str(row[6]),
            superseded_at=str(row[7]) if row[7] is not None else None,
        )

    def _row_to_review_trigger(self, row: tuple[object, ...]) -> ReviewTrigger:
        return ReviewTrigger(
            trigger_id=str(row[0]),
            agent_id=str(row[1]),
            trigger_kind=str(row[2]),
            source_run_id=str(row[3]),
            source_trace_id=str(row[4]),
            source_fingerprints=list(json.loads(str(row[5]))),
            status=str(row[6]),
            payload_json=dict(json.loads(str(row[7]))),
            semantic_fingerprint=str(row[8]),
            created_at=str(row[9]),
            updated_at=str(row[10]),
        )

    def _row_to_skill_candidate(self, row: tuple[object, ...]) -> SkillCandidate:
        return SkillCandidate(
            candidate_id=str(row[0]),
            agent_id=str(row[1]),
            status=str(row[2]),
            title=str(row[3]),
            slug=str(row[4]),
            summary=str(row[5]),
            trigger_conditions=list(json.loads(str(row[6]))),
            body_markdown=str(row[7]),
            rationale=str(row[8]),
            source_run_ids=list(json.loads(str(row[9]))),
            source_fingerprints=list(json.loads(str(row[10]))),
            confidence=float(row[11]),
            semantic_fingerprint=str(row[12]),
            created_at=str(row[13]),
            reviewed_at=str(row[14]) if row[14] is not None else None,
            promoted_skill_id=str(row[15]) if row[15] is not None else None,
        )
