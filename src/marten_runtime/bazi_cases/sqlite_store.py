from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from marten_runtime.bazi_cases.models import (
    BaziCaseEvent,
    BaziCaseInterpretation,
    BaziCasePrediction,
    BaziCaseRecord,
    BaziCaseReview,
    BaziCaseSourceRef,
    BaziExtractionQuality,
    BaziTopicConclusion,
    SHARED_CASE_OWNER_KEY,
)


class SQLiteBaziCaseStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bazi_cases (
                    case_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    case_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_run_id TEXT NOT NULL,
                    source_session_id TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    engine_json TEXT NOT NULL,
                    result_schema_version TEXT NOT NULL,
                    time_basis_json TEXT,
                    chart_snapshot_json TEXT NOT NULL,
                    chart_features_json TEXT NOT NULL,
                    question TEXT NOT NULL,
                    analysis_summary TEXT NOT NULL,
                    raw_case_text TEXT NOT NULL DEFAULT '',
                    interpretation_json TEXT NOT NULL DEFAULT '{}',
                    topic_conclusions_json TEXT NOT NULL DEFAULT '[]',
                    predictions_json TEXT NOT NULL DEFAULT '[]',
                    reviews_json TEXT NOT NULL DEFAULT '[]',
                    projection_namespace TEXT NOT NULL,
                    projection_source_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_bazi_cases_owner_status
                    ON bazi_cases(owner_key, status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS bazi_case_events (
                    event_id TEXT NOT NULL,
                    case_id TEXT NOT NULL REFERENCES bazi_cases(case_id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(case_id, event_id)
                );
                CREATE INDEX IF NOT EXISTS idx_bazi_case_events_case
                    ON bazi_case_events(case_id, ordinal);
                """
            )
            self._ensure_compatible_columns(conn)

    @staticmethod
    def _ensure_compatible_columns(conn: sqlite3.Connection) -> None:
        existing = {str(row["name"]) for row in conn.execute("PRAGMA table_info(bazi_cases)")}
        additions = {
            "raw_case_text": "TEXT NOT NULL DEFAULT ''",
            "interpretation_json": "TEXT NOT NULL DEFAULT '{}'",
            "topic_conclusions_json": "TEXT NOT NULL DEFAULT '[]'",
            "predictions_json": "TEXT NOT NULL DEFAULT '[]'",
            "reviews_json": "TEXT NOT NULL DEFAULT '[]'",
            "source_ref_json": "TEXT NOT NULL DEFAULT '{}'",
            "extraction_quality_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, definition in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE bazi_cases ADD COLUMN {name} {definition}")

    def save(self, record: BaziCaseRecord) -> None:
        values = _case_values(record)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT owner_key FROM bazi_cases WHERE case_id=?", (record.case_id,)
            ).fetchone()
            if existing is not None and str(existing["owner_key"]) != record.owner_key:
                raise ValueError("case owner mismatch")
            conn.execute(
                """
                INSERT INTO bazi_cases (
                    case_id, owner_key, schema_version, case_version, status, visibility,
                    source_type, source_run_id, source_session_id, input_fingerprint,
                    engine_json, result_schema_version, time_basis_json, chart_snapshot_json,
                    chart_features_json, question, analysis_summary, raw_case_text,
                    interpretation_json, topic_conclusions_json, predictions_json, reviews_json,
                    source_ref_json, extraction_quality_json,
                    projection_namespace, projection_source_id, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(case_id) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    case_version=excluded.case_version, status=excluded.status,
                    visibility=excluded.visibility, source_type=excluded.source_type,
                    source_run_id=excluded.source_run_id,
                    source_session_id=excluded.source_session_id,
                    input_fingerprint=excluded.input_fingerprint,
                    engine_json=excluded.engine_json,
                    result_schema_version=excluded.result_schema_version,
                    time_basis_json=excluded.time_basis_json,
                    chart_snapshot_json=excluded.chart_snapshot_json,
                    question=excluded.question, analysis_summary=excluded.analysis_summary,
                    chart_features_json=excluded.chart_features_json,
                    raw_case_text=excluded.raw_case_text,
                    interpretation_json=excluded.interpretation_json,
                    topic_conclusions_json=excluded.topic_conclusions_json,
                    predictions_json=excluded.predictions_json,
                    reviews_json=excluded.reviews_json,
                    source_ref_json=excluded.source_ref_json,
                    extraction_quality_json=excluded.extraction_quality_json,
                    projection_namespace=excluded.projection_namespace,
                    projection_source_id=excluded.projection_source_id,
                    updated_at=excluded.updated_at
                WHERE bazi_cases.owner_key=excluded.owner_key
                """,
                values,
            )
            conn.execute("DELETE FROM bazi_case_events WHERE case_id=?", (record.case_id,))
            conn.executemany(
                "INSERT INTO bazi_case_events(event_id, case_id, ordinal, category, payload_json) VALUES(?,?,?,?,?)",
                [
                    (
                        event.event_id,
                        record.case_id,
                        index,
                        event.category,
                        _json(event.model_dump(mode="json")),
                    )
                    for index, event in enumerate(record.events)
                ],
            )

    def get(self, owner_key: str, case_id: str, *, include_deleted: bool = False) -> BaziCaseRecord | None:
        status_clause = "" if include_deleted else " AND status!='deleted'"
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM bazi_cases WHERE owner_key=? AND case_id=?{status_clause}",
                (owner_key, case_id),
            ).fetchone()
            return self._record(conn, row) if row is not None else None

    def list(self, owner_key: str, *, include_archived: bool = False) -> list[BaziCaseRecord]:
        active_status = "active_shared" if owner_key == SHARED_CASE_OWNER_KEY else "active_private"
        statuses = (active_status, "archived") if include_archived else (active_status,)
        marks = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM bazi_cases WHERE owner_key=? AND status IN ({marks}) ORDER BY updated_at DESC, case_id",
                (owner_key, *statuses),
            ).fetchall()
            return [self._record(conn, row) for row in rows]

    def get_by_input_fingerprint(
        self, owner_key: str, input_fingerprint: str
    ) -> BaziCaseRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM bazi_cases
                WHERE owner_key=? AND input_fingerprint=? AND status!='deleted'
                ORDER BY updated_at DESC LIMIT 1
                """,
                (owner_key, input_fingerprint),
            ).fetchone()
            return self._record(conn, row) if row is not None else None

    def list_active_private_imports_by_source_digest(
        self, content_sha256: str
    ) -> list[BaziCaseRecord]:
        if not content_sha256:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM bazi_cases
                WHERE owner_key!=?
                  AND status='active_private'
                  AND source_type='operator_imported'
                  AND json_extract(source_ref_json, '$.content_sha256')=?
                ORDER BY updated_at DESC, case_id
                """,
                (SHARED_CASE_OWNER_KEY, content_sha256),
            ).fetchall()
            return [self._record(conn, row) for row in rows]

    def list_active_private_owners(self) -> list[str]:
        with self._connect() as conn:
            return [
                str(row["owner_key"])
                for row in conn.execute(
                    "SELECT DISTINCT owner_key FROM bazi_cases WHERE status='active_private'"
                )
            ]

    def _record(self, conn: sqlite3.Connection, row: sqlite3.Row) -> BaziCaseRecord:
        event_rows = conn.execute(
            "SELECT payload_json FROM bazi_case_events WHERE case_id=? ORDER BY ordinal",
            (str(row["case_id"]),),
        ).fetchall()
        return BaziCaseRecord(
            case_id=row["case_id"],
            owner_key=row["owner_key"],
            schema_version=row["schema_version"],
            case_version=row["case_version"],
            status=row["status"],
            visibility=row["visibility"],
            source_type=row["source_type"],
            source_run_id=row["source_run_id"],
            source_session_id=row["source_session_id"],
            input_fingerprint=row["input_fingerprint"],
            engine=json.loads(row["engine_json"]),
            result_schema_version=row["result_schema_version"],
            time_basis=json.loads(row["time_basis_json"]) if row["time_basis_json"] else None,
            chart_snapshot=json.loads(row["chart_snapshot_json"]),
            chart_features=json.loads(row["chart_features_json"]),
            question=row["question"],
            analysis_summary=row["analysis_summary"],
            raw_case_text=row["raw_case_text"],
            interpretation=BaziCaseInterpretation(**json.loads(row["interpretation_json"] or "{}")),
            topic_conclusions=[
                BaziTopicConclusion(**item)
                for item in json.loads(row["topic_conclusions_json"] or "[]")
            ],
            predictions=[
                BaziCasePrediction(**item)
                for item in json.loads(row["predictions_json"] or "[]")
            ],
            events=[BaziCaseEvent(**json.loads(item["payload_json"])) for item in event_rows],
            reviews=[
                BaziCaseReview(**item) for item in json.loads(row["reviews_json"] or "[]")
            ],
            source_ref=BaziCaseSourceRef(**json.loads(row["source_ref_json"] or "{}")),
            extraction_quality=BaziExtractionQuality(
                **json.loads(row["extraction_quality_json"] or "{}")
            ),
            projection_namespace=row["projection_namespace"],
            projection_source_id=row["projection_source_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _case_values(record: BaziCaseRecord) -> tuple[object, ...]:
    return (
        record.case_id, record.owner_key, record.schema_version, record.case_version,
        record.status, record.visibility, record.source_type, record.source_run_id,
        record.source_session_id, record.input_fingerprint, _json(record.engine),
        record.result_schema_version, _json(record.time_basis) if record.time_basis is not None else None,
        _json(record.chart_snapshot), _json(record.chart_features), record.question,
        record.analysis_summary, record.raw_case_text,
        _json(record.interpretation.model_dump(mode="json")),
        _json([item.model_dump(mode="json") for item in record.topic_conclusions]),
        _json([item.model_dump(mode="json") for item in record.predictions]),
        _json([item.model_dump(mode="json") for item in record.reviews]),
        _json(record.source_ref.model_dump(mode="json")),
        _json(record.extraction_quality.model_dump(mode="json")),
        record.projection_namespace, record.projection_source_id,
        record.created_at, record.updated_at,
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
