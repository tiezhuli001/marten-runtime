from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from marten_runtime.evals.models import EvalCaseResult, EvalRunSummary
from marten_runtime.sqlite_support import connect_sqlite, prepare_sqlite_path


class SQLiteEvalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = prepare_sqlite_path(path)
        self._lock = threading.RLock()
        self.init_schema()

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS eval_runs (
                    eval_run_id TEXT PRIMARY KEY,
                    suite_id TEXT NOT NULL,
                    git_branch TEXT NOT NULL,
                    git_sha TEXT NOT NULL,
                    git_dirty INTEGER NOT NULL,
                    eval_mode TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    provider_ref TEXT,
                    model_name TEXT,
                    config_fingerprint TEXT NOT NULL,
                    suite_fingerprint TEXT NOT NULL,
                    baseline_eval_run_id TEXT,
                    total_score REAL NOT NULL,
                    pass_rate REAL NOT NULL,
                    status TEXT NOT NULL,
                    artifact_root TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS eval_case_results (
                    eval_run_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_score REAL NOT NULL,
                    outcome_score REAL NOT NULL,
                    tool_path_score REAL NOT NULL,
                    efficiency_score REAL NOT NULL,
                    context_score REAL NOT NULL,
                    llm_request_count INTEGER NOT NULL,
                    tool_calls_count INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    run_id TEXT,
                    trace_id TEXT,
                    langfuse_url TEXT,
                    final_text TEXT NOT NULL,
                    diagnostics_json TEXT NOT NULL,
                    score_breakdown_json TEXT NOT NULL,
                    artifact_path TEXT,
                    blocked_reason TEXT,
                    PRIMARY KEY (eval_run_id, case_id)
                );
                CREATE TABLE IF NOT EXISTS eval_baselines (
                    suite_id TEXT NOT NULL,
                    baseline_name TEXT NOT NULL,
                    eval_run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (suite_id, baseline_name)
                );
                """
            )

    def record_run_start(self, summary: EvalRunSummary) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_runs (
                    eval_run_id, suite_id, git_branch, git_sha, git_dirty, eval_mode,
                    agent_id, profile_name, provider_ref, model_name, config_fingerprint,
                    suite_fingerprint, baseline_eval_run_id, total_score, pass_rate, status,
                    artifact_root, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.eval_run_id,
                    summary.suite_id,
                    summary.git_branch,
                    summary.git_sha,
                    1 if summary.git_dirty else 0,
                    summary.eval_mode,
                    summary.agent_id,
                    summary.profile_name,
                    summary.provider_ref,
                    summary.model_name,
                    summary.config_fingerprint,
                    summary.suite_fingerprint,
                    summary.baseline_eval_run_id,
                    summary.total_score,
                    summary.pass_rate,
                    summary.status,
                    summary.artifact_root,
                    summary.started_at.isoformat(),
                    summary.finished_at.isoformat() if summary.finished_at else None,
                ),
            )

    def record_case_result(self, result: EvalCaseResult) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_case_results (
                    eval_run_id, case_id, family, status, total_score, outcome_score,
                    tool_path_score, efficiency_score, context_score, llm_request_count,
                    tool_calls_count, duration_ms, run_id, trace_id, langfuse_url,
                    final_text, diagnostics_json, score_breakdown_json, artifact_path,
                    blocked_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.eval_run_id,
                    result.case_id,
                    result.family,
                    result.status,
                    result.total_score,
                    result.outcome_score,
                    result.tool_path_score,
                    result.efficiency_score,
                    result.context_score,
                    result.llm_request_count,
                    result.tool_calls_count,
                    result.duration_ms,
                    result.run_id,
                    result.trace_id,
                    result.langfuse_url,
                    result.final_text,
                    json.dumps(result.diagnostics_json, ensure_ascii=False),
                    json.dumps(result.score_breakdown_json, ensure_ascii=False),
                    result.artifact_path,
                    result.blocked_reason,
                ),
            )

    def record_run_finish(self, eval_run_id: str, *, total_score: float, pass_rate: float, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE eval_runs
                SET total_score = ?, pass_rate = ?, status = ?, finished_at = ?
                WHERE eval_run_id = ?
                """,
                (
                    total_score,
                    pass_rate,
                    status,
                    datetime.now(timezone.utc).isoformat(),
                    eval_run_id,
                ),
            )

    def get_run(self, eval_run_id: str) -> EvalRunSummary:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT eval_run_id, suite_id, git_branch, git_sha, git_dirty, eval_mode,
                       agent_id, profile_name, provider_ref, model_name, config_fingerprint,
                       suite_fingerprint, baseline_eval_run_id, total_score, pass_rate, status,
                       artifact_root, started_at, finished_at
                FROM eval_runs WHERE eval_run_id = ? LIMIT 1
                """,
                (eval_run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(eval_run_id)
        return self._row_to_run_summary(row)

    def list_recent_runs(
        self,
        *,
        suite_id: str,
        profile_name: str,
        eval_mode: str,
        git_sha: str | None = None,
        config_fingerprint: str | None = None,
        suite_fingerprint: str | None = None,
        limit: int = 5,
    ) -> list[EvalRunSummary]:
        filters = [
            "suite_id = ?",
            "profile_name = ?",
            "eval_mode = ?",
            "finished_at IS NOT NULL",
            "status IN ('passed', 'failed')",
        ]
        params: list[object] = [suite_id, profile_name, eval_mode]
        if git_sha is not None:
            filters.append("git_sha = ?")
            params.append(git_sha)
        if config_fingerprint is not None:
            filters.append("config_fingerprint = ?")
            params.append(config_fingerprint)
        if suite_fingerprint is not None:
            filters.append("suite_fingerprint = ?")
            params.append(suite_fingerprint)
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT eval_run_id, suite_id, git_branch, git_sha, git_dirty, eval_mode,
                       agent_id, profile_name, provider_ref, model_name, config_fingerprint,
                       suite_fingerprint, baseline_eval_run_id, total_score, pass_rate, status,
                       artifact_root, started_at, finished_at
                FROM eval_runs
                WHERE {' AND '.join(filters)}
                ORDER BY finished_at DESC, started_at DESC, eval_run_id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._row_to_run_summary(row) for row in rows]

    def list_runs(self, *, limit: int = 20) -> list[EvalRunSummary]:
        capped_limit = max(1, min(int(limit), 200))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT eval_run_id, suite_id, git_branch, git_sha, git_dirty, eval_mode,
                       agent_id, profile_name, provider_ref, model_name, config_fingerprint,
                       suite_fingerprint, baseline_eval_run_id, total_score, pass_rate, status,
                       artifact_root, started_at, finished_at
                FROM eval_runs
                ORDER BY started_at DESC, eval_run_id DESC
                LIMIT ?
                """,
                (capped_limit,),
            ).fetchall()
        return [self._row_to_run_summary(row) for row in rows]

    def list_case_results(self, eval_run_id: str) -> list[EvalCaseResult]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT eval_run_id, case_id, family, status, total_score, outcome_score,
                       tool_path_score, efficiency_score, context_score, llm_request_count,
                       tool_calls_count, duration_ms, run_id, trace_id, langfuse_url,
                       final_text, diagnostics_json, score_breakdown_json, artifact_path,
                       blocked_reason
                FROM eval_case_results WHERE eval_run_id = ? ORDER BY case_id ASC
                """,
                (eval_run_id,),
            ).fetchall()
        return [
            EvalCaseResult(
                eval_run_id=str(row[0]),
                case_id=str(row[1]),
                family=str(row[2]),
                status=str(row[3]),
                total_score=float(row[4]),
                outcome_score=float(row[5]),
                tool_path_score=float(row[6]),
                efficiency_score=float(row[7]),
                context_score=float(row[8]),
                llm_request_count=int(row[9]),
                tool_calls_count=int(row[10]),
                duration_ms=int(row[11]),
                run_id=row[12],
                trace_id=row[13],
                langfuse_url=row[14],
                final_text=str(row[15]),
                diagnostics_json=json.loads(str(row[16])),
                score_breakdown_json=json.loads(str(row[17])),
                artifact_path=row[18],
                blocked_reason=row[19],
            )
            for row in rows
        ]

    def write_baseline(self, suite_id: str, baseline_name: str, eval_run_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_baselines (suite_id, baseline_name, eval_run_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (suite_id, baseline_name, eval_run_id, datetime.now(timezone.utc).isoformat()),
            )

    def resolve_baseline(self, suite_id: str, baseline_name: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT eval_run_id FROM eval_baselines
                WHERE suite_id = ? AND baseline_name = ?
                LIMIT 1
                """,
                (suite_id, baseline_name),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def _row_to_run_summary(self, row: sqlite3.Row | tuple[object, ...]) -> EvalRunSummary:
        return EvalRunSummary(
            eval_run_id=str(row[0]),
            suite_id=str(row[1]),
            git_branch=str(row[2]),
            git_sha=str(row[3]),
            git_dirty=bool(row[4]),
            eval_mode=str(row[5]),
            agent_id=str(row[6]),
            profile_name=str(row[7]),
            provider_ref=row[8],
            model_name=row[9],
            config_fingerprint=str(row[10]),
            suite_fingerprint=str(row[11]),
            baseline_eval_run_id=row[12],
            total_score=float(row[13]),
            pass_rate=float(row[14]),
            status=str(row[15]),
            artifact_root=str(row[16]),
            started_at=datetime.fromisoformat(str(row[17])),
            finished_at=datetime.fromisoformat(str(row[18])) if row[18] else None,
        )

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            return connect_sqlite(self.path)
