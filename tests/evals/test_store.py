import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from marten_runtime.evals.models import EvalCaseResult, EvalRunSummary
from marten_runtime.evals.store import SQLiteEvalStore


class EvalStoreTests(unittest.TestCase):

    def _summary(self, eval_run_id: str, *, suite_id: str = "main_chain_core") -> EvalRunSummary:
        return EvalRunSummary(
            eval_run_id=eval_run_id,
            suite_id=suite_id,
            git_branch="feature/eval",
            git_sha="deadbeef",
            git_dirty=False,
            eval_mode="scripted",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            provider_ref="openai",
            model_name="gpt-5.4",
            config_fingerprint="cfg123",
            suite_fingerprint="suite123",
            total_score=100.0,
            pass_rate=1.0,
            status="passed",
            artifact_root=f"reports/evals/{eval_run_id}",
        )

    def _case(self, eval_run_id: str, *, score: float = 100.0) -> EvalCaseResult:
        return EvalCaseResult(
            eval_run_id=eval_run_id,
            case_id="direct_answer_cn",
            family="direct_answer",
            status="passed" if score >= 100.0 else "failed",
            total_score=score,
            outcome_score=score,
            tool_path_score=0.0,
            efficiency_score=0.0,
            context_score=0.0,
            llm_request_count=1,
            tool_calls_count=0,
            duration_ms=10,
            run_id=f"run_{eval_run_id}",
            trace_id=f"trace_{eval_run_id}",
            final_text="你好",
            diagnostics_json={"provider_ref": "openai"},
            score_breakdown_json={"outcome": {"matched": score >= 100.0}},
        )
    def test_store_initializes_schema_and_records_run_and_case_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEvalStore(Path(tmpdir) / "evals.sqlite3")
            summary = EvalRunSummary(
                eval_run_id="eval_1",
                suite_id="main_chain_core",
                git_branch="feature/eval",
                git_sha="deadbeef",
                git_dirty=False,
                eval_mode="scripted",
                agent_id="main",
                profile_name="openai_gpt_5_4",
                provider_ref="openai",
                model_name="gpt-5.4",
                config_fingerprint="cfg123",
                suite_fingerprint="suite123",
                total_score=0.0,
                pass_rate=0.0,
                status="running",
                artifact_root="reports/evals/eval_1",
            )
            store.record_run_start(summary)
            store.record_case_result(
                EvalCaseResult(
                    eval_run_id="eval_1",
                    case_id="direct_answer_cn",
                    family="direct_answer",
                    status="passed",
                    total_score=100.0,
                    outcome_score=100.0,
                    tool_path_score=0.0,
                    efficiency_score=0.0,
                    context_score=0.0,
                    llm_request_count=1,
                    tool_calls_count=0,
                    duration_ms=10,
                    run_id="run_1234",
                    trace_id="trace_1234",
                    langfuse_url=None,
                    final_text="你好",
                    diagnostics_json={"provider_ref": "openai"},
                    score_breakdown_json={"outcome": {"matched": True}},
                    artifact_path="reports/evals/eval_1/cases/direct_answer_cn.json",
                )
            )
            store.record_run_finish(
                "eval_1",
                total_score=100.0,
                pass_rate=1.0,
                status="passed",
            )

            loaded = store.get_run("eval_1")
            case_results = store.list_case_results("eval_1")

            self.assertEqual(loaded.status, "passed")
            self.assertEqual(case_results[0].case_id, "direct_answer_cn")

    def test_store_reads_and_writes_named_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEvalStore(Path(tmpdir) / "evals.sqlite3")
            summary = EvalRunSummary(
                eval_run_id="eval_1",
                suite_id="main_chain_core",
                git_branch="feature/eval",
                git_sha="deadbeef",
                git_dirty=False,
                eval_mode="scripted",
                agent_id="main",
                profile_name="openai_gpt_5_4",
                provider_ref="openai",
                model_name="gpt-5.4",
                config_fingerprint="cfg123",
                suite_fingerprint="suite123",
                total_score=100.0,
                pass_rate=1.0,
                status="passed",
                artifact_root="reports/evals/eval_1",
            )
            store.record_run_start(summary)
            store.record_run_finish("eval_1", total_score=100.0, pass_rate=1.0, status="passed")
            store.write_baseline("main_chain_core", "latest_passed", "eval_1")

            self.assertEqual(store.resolve_baseline("main_chain_core", "latest_passed"), "eval_1")

    def test_store_lists_recent_runs_by_suite_profile_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEvalStore(Path(tmpdir) / "evals.sqlite3")
            summaries = [
                EvalRunSummary(
                    eval_run_id="eval_old",
                    suite_id="memory_long_horizon",
                    git_branch="feature/eval",
                    git_sha="deadbeef",
                    git_dirty=False,
                    eval_mode="live",
                    agent_id="main",
                    profile_name="openai_gpt_5_4",
                    provider_ref="openai",
                    model_name="gpt-5.4",
                    config_fingerprint="cfg123",
                    suite_fingerprint="suite123",
                    total_score=80.0,
                    pass_rate=1.0,
                    status="passed",
                    artifact_root="reports/evals/eval_old",
                ),
                EvalRunSummary(
                    eval_run_id="eval_other_profile",
                    suite_id="memory_long_horizon",
                    git_branch="feature/eval",
                    git_sha="deadbeef",
                    git_dirty=False,
                    eval_mode="live",
                    agent_id="main",
                    profile_name="minimax_m2_7_highspeed",
                    provider_ref="minimax",
                    model_name="MiniMax-M2.7-highspeed",
                    config_fingerprint="cfg123",
                    suite_fingerprint="suite123",
                    total_score=88.0,
                    pass_rate=1.0,
                    status="passed",
                    artifact_root="reports/evals/eval_other_profile",
                ),
                EvalRunSummary(
                    eval_run_id="eval_new",
                    suite_id="memory_long_horizon",
                    git_branch="feature/eval",
                    git_sha="deadbeef",
                    git_dirty=False,
                    eval_mode="live",
                    agent_id="main",
                    profile_name="openai_gpt_5_4",
                    provider_ref="openai",
                    model_name="gpt-5.4",
                    config_fingerprint="cfg123",
                    suite_fingerprint="suite123",
                    total_score=92.0,
                    pass_rate=1.0,
                    status="failed",
                    artifact_root="reports/evals/eval_new",
                ),
                EvalRunSummary(
                    eval_run_id="eval_other_mode",
                    suite_id="memory_long_horizon",
                    git_branch="feature/eval",
                    git_sha="deadbeef",
                    git_dirty=False,
                    eval_mode="scripted",
                    agent_id="main",
                    profile_name="openai_gpt_5_4",
                    provider_ref="openai",
                    model_name="gpt-5.4",
                    config_fingerprint="cfg123",
                    suite_fingerprint="suite123",
                    total_score=100.0,
                    pass_rate=1.0,
                    status="passed",
                    artifact_root="reports/evals/eval_other_mode",
                ),
            ]
            for summary in summaries:
                store.record_run_start(summary)
                store.record_run_finish(
                    summary.eval_run_id,
                    total_score=summary.total_score,
                    pass_rate=summary.pass_rate,
                    status=summary.status,
                )

            recent = store.list_recent_runs(
                suite_id="memory_long_horizon",
                profile_name="openai_gpt_5_4",
                eval_mode="live",
                git_sha="deadbeef",
                config_fingerprint="cfg123",
                suite_fingerprint="suite123",
                limit=2,
            )

            self.assertEqual([item.eval_run_id for item in recent], ["eval_new", "eval_old"])


    def test_store_creates_incrementing_eval_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEvalStore(Path(tmpdir) / "evals.sqlite3")
            first = self._summary("eval_1")
            second = self._summary("eval_2", suite_id="challenge_memory")
            store.record_run_start(first)
            store.record_run_start(second)

            version = store.create_eval_version(
                eval_run_ids=["eval_1", "eval_2"],
                created_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
            )
            next_version = store.create_eval_version(
                eval_run_ids=["eval_1"],
                created_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
            )

            self.assertEqual(version["version_id"], "v2026.05.18-1")
            self.assertEqual(next_version["version_id"], "v2026.05.18-2")
            self.assertEqual(store.latest_eval_version()["version_id"], "v2026.05.18-2")
            runs = store.list_eval_version_runs("v2026.05.18-1")
            self.assertEqual({item["role"] for item in runs}, {"gate", "challenge"})

    def test_store_rejects_duplicate_suite_when_creating_eval_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEvalStore(Path(tmpdir) / "evals.sqlite3")
            first = self._summary("eval_1", suite_id="challenge_memory")
            second = self._summary("eval_2", suite_id="challenge_memory")
            store.record_run_start(first)
            store.record_run_start(second)

            with self.assertRaisesRegex(ValueError, "duplicate suite_id"):
                store.create_eval_version(eval_run_ids=["eval_1", "eval_2"])



if __name__ == "__main__":
    unittest.main()
