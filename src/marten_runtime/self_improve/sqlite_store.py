from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from marten_runtime.self_improve.models import (
    FailureEvent,
    LessonCandidate,
    RecoveryEvent,
    SystemLesson,
)


class SQLiteSelfImproveStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def count_recent_failures_since(
        self,
        *,
        agent_id: str,
        fingerprint: str,
        created_at_gte: str,
    ) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(1)
                FROM runtime_failure_events
                WHERE agent_id = ? AND fingerprint = ? AND created_at >= ?
                """,
                (agent_id, fingerprint, created_at_gte),
            ).fetchone()
        return int(row[0] if row is not None else 0)

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

    def create_threshold_trigger(
        self,
        *,
        agent_id: str,
        fingerprint: str,
        window_start: str,
    ) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO self_improve_triggers (
                        agent_id, fingerprint, window_start, status, created_at
                    ) VALUES (?, ?, ?, 'pending', ?)
                    """,
                    (agent_id, fingerprint, window_start, window_start),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def list_pending_triggers(self, *, agent_id: str, limit: int) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT agent_id, fingerprint, window_start, status, created_at
                FROM self_improve_triggers
                WHERE agent_id = ? AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_id, limit),
            ).fetchall()
        return [
            {
                "agent_id": str(row[0]),
                "fingerprint": str(row[1]),
                "window_start": str(row[2]),
                "status": str(row[3]),
                "created_at": str(row[4]),
            }
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

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
                CREATE TABLE IF NOT EXISTS self_improve_triggers (
                    agent_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (agent_id, fingerprint, window_start)
                )
                """
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
