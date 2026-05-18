import unittest

import tempfile
from pathlib import Path

from marten_runtime.evals.compare import (
    build_eval_run_stability_summary,
    compare_eval_runs,
    resolve_compare_baseline,
)
from marten_runtime.evals.models import (
    EvalCaseResult,
    EvalCaseSpec,
    EvalComponentComparison,
    EvalRunSummary,
    EvalTurnSpec,
)
from marten_runtime.evals.store import SQLiteEvalStore


class EvalCompareTests(unittest.TestCase):
    def _summary(self, eval_run_id: str, *, total_score: float, pass_rate: float) -> EvalRunSummary:
        return EvalRunSummary(
            eval_run_id=eval_run_id,
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
            total_score=total_score,
            pass_rate=pass_rate,
            status="passed",
            artifact_root=f"reports/evals/{eval_run_id}",
        )

    def _case(
        self,
        eval_run_id: str,
        case_id: str,
        *,
        total_score: float,
        status: str,
        components: list[dict[str, object]] | None = None,
    ) -> EvalCaseResult:
        return EvalCaseResult(
            eval_run_id=eval_run_id,
            case_id=case_id,
            family="direct_answer",
            status=status,
            total_score=total_score,
            outcome_score=total_score,
            tool_path_score=0.0,
            efficiency_score=0.0,
            context_score=0.0,
            llm_request_count=1,
            tool_calls_count=0,
            duration_ms=10,
            run_id=f"run_{case_id}",
            trace_id=f"trace_{case_id}",
            langfuse_url=None,
            final_text="ok",
            diagnostics_json={"provider_ref": "openai"},
            score_breakdown_json={"components": components or []},
        )

    def test_compare_eval_runs_reports_deltas_and_sorted_regressions(self) -> None:
        baseline_summary = self._summary("eval_base", total_score=100.0, pass_rate=1.0)
        current_summary = self._summary("eval_now", total_score=90.0, pass_rate=0.5)
        baseline_cases = [
            self._case("eval_base", "direct_answer_cn", total_score=100.0, status="passed"),
            self._case("eval_base", "time_single_tool_cn", total_score=100.0, status="passed"),
        ]
        current_cases = [
            self._case("eval_now", "direct_answer_cn", total_score=100.0, status="passed"),
            self._case("eval_now", "time_single_tool_cn", total_score=80.0, status="failed"),
        ]

        compare = compare_eval_runs(
            current_summary,
            current_cases,
            baseline_summary,
            baseline_cases,
            baseline_source="latest_passed",
        )

        self.assertEqual(compare.baseline_eval_run_id, "eval_base")
        self.assertEqual(compare.total_score_delta, -10.0)
        self.assertEqual(compare.pass_rate_delta, -0.5)
        self.assertEqual(compare.regressions[0].case_id, "time_single_tool_cn")
        self.assertEqual(compare.regressions[0].total_score_delta, -20.0)
        self.assertEqual(compare.improvements, [])

    def test_compare_eval_runs_reports_component_summary_and_case_component_deltas(self) -> None:
        baseline_summary = self._summary("eval_base", total_score=90.0, pass_rate=1.0)
        current_summary = self._summary("eval_now", total_score=95.0, pass_rate=1.0)
        baseline_cases = [
            self._case(
                "eval_base",
                "memory_capture_preference_cn",
                total_score=90.0,
                status="passed",
                components=[
                    {"key": "capture", "label": "记忆写入", "score": 60.0, "passed": True},
                    {"key": "utility_gain", "label": "结果应用", "score": 30.0, "passed": True},
                ],
            ),
        ]
        current_cases = [
            self._case(
                "eval_now",
                "memory_capture_preference_cn",
                total_score=95.0,
                status="passed",
                components=[
                    {"key": "capture", "label": "记忆写入", "score": 60.0, "passed": True},
                    {"key": "utility_gain", "label": "结果应用", "score": 35.0, "passed": True},
                ],
            ),
        ]

        compare = compare_eval_runs(
            current_summary,
            current_cases,
            baseline_summary,
            baseline_cases,
            baseline_source="latest_passed",
        )

        self.assertEqual(compare.component_summary[0].key, "capture")
        self.assertEqual(compare.component_summary[0].delta, 0.0)
        self.assertEqual(compare.component_summary[1].key, "utility_gain")
        self.assertEqual(compare.component_summary[1].delta, 5.0)
        self.assertEqual(compare.cases[0].components[1].key, "utility_gain")
        self.assertEqual(compare.cases[0].components[1].delta, 5.0)

    def test_resolve_compare_baseline_prefers_explicit_run_then_named_then_latest_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEvalStore(Path(tmpdir) / "evals.sqlite3")
            store.write_baseline("main_chain_core", "main", "eval_main")
            store.write_baseline("main_chain_core", "latest_passed", "eval_latest")

            run_id, source = resolve_compare_baseline(
                store,
                suite_id="main_chain_core",
                baseline_name="main",
                baseline_run_id="eval_explicit",
            )
            self.assertEqual((run_id, source), ("eval_explicit", "explicit_run"))

            run_id, source = resolve_compare_baseline(
                store,
                suite_id="main_chain_core",
                baseline_name="main",
                baseline_run_id=None,
            )
            self.assertEqual((run_id, source), ("eval_main", "named:main"))

            run_id, source = resolve_compare_baseline(
                store,
                suite_id="main_chain_core",
                baseline_name=None,
                baseline_run_id=None,
            )
            self.assertEqual((run_id, source), ("eval_latest", "latest_passed"))

    def test_build_eval_run_stability_summary_reports_case_and_component_volatility(self) -> None:
        summaries = [
            self._summary("eval_3", total_score=90.0, pass_rate=1.0),
            self._summary("eval_2", total_score=100.0, pass_rate=1.0),
            self._summary("eval_1", total_score=80.0, pass_rate=0.0),
        ]
        history = {
            "eval_3": [
                self._case(
                    "eval_3",
                    "memory_delayed_recall_same_session_cn",
                    total_score=90.0,
                    status="passed",
                    components=[
                        {"key": "delayed_recall", "label": "延迟召回", "score": 60.0, "passed": True},
                    ],
                ).model_copy(
                    update={
                        "diagnostics_json": {
                            "turns": [
                                {
                                    "run": {
                                        "latest_actual_usage": {"total_tokens": 720},
                                        "attempted_profiles": ["openai_gpt_5_4"],
                                        "provider_ref": "openai",
                                        "final_provider_ref": "openai",
                                    }
                                }
                            ]
                        }
                    }
                )
            ],
            "eval_2": [
                self._case(
                    "eval_2",
                    "memory_delayed_recall_same_session_cn",
                    total_score=100.0,
                    status="passed",
                    components=[
                        {"key": "delayed_recall", "label": "延迟召回", "score": 70.0, "passed": True},
                    ],
                ).model_copy(
                    update={
                        "diagnostics_json": {
                            "turns": [
                                {
                                    "run": {
                                        "latest_actual_usage": {"total_tokens": 810},
                                        "attempted_profiles": ["openai_gpt_5_4", "minimax_m2_7_highspeed"],
                                        "provider_ref": "openai",
                                        "final_provider_ref": "minimax",
                                        "failover_trigger": "PROVIDER_UPSTREAM_UNAVAILABLE",
                                    }
                                }
                            ]
                        }
                    }
                )
            ],
            "eval_1": [
                self._case(
                    "eval_1",
                    "memory_delayed_recall_same_session_cn",
                    total_score=60.0,
                    status="failed",
                    components=[
                        {"key": "delayed_recall", "label": "延迟召回", "score": 20.0, "passed": False},
                    ],
                ).model_copy(
                    update={
                        "diagnostics_json": {
                            "turns": [
                                {
                                    "run": {
                                        "latest_actual_usage": {"total_tokens": 940},
                                        "attempted_profiles": ["openai_gpt_5_4"],
                                        "provider_ref": "openai",
                                        "final_provider_ref": "openai",
                                    }
                                }
                            ]
                        }
                    }
                )
            ],
        }
        case_specs = [
            EvalCaseSpec(
                case_id="memory_delayed_recall_same_session_cn",
                suite_id="memory_long_horizon",
                family="memory_long_horizon",
                grader_id="memory_long_horizon",
                description="demo",
                agent_id="main",
                profile_name="openai_gpt_5_4",
                turns=[
                    EvalTurnSpec(role="user", content="记住：日报先给风险，再给结论。"),
                    EvalTurnSpec(role="user", content="过几轮后提醒我刚才的日报顺序。"),
                ],
                component_weights={"delayed_recall": 100},
                gate_components=["delayed_recall"],
                grader_case={
                    "recall_contains_all": ["日报"],
                    "recall_anchor_groups": [
                        ["先给风险", "风险优先"],
                        ["再给结论", "后给结论"],
                    ],
                    "max_memory_calls": 1,
                },
            )
        ]

        stability = build_eval_run_stability_summary(
            suite_id="memory_long_horizon",
            profile_name="openai_gpt_5_4",
            eval_mode="live",
            run_summaries=summaries,
            case_results_by_run_id=history,
            case_specs=case_specs,
            window_size=5,
        )

        self.assertEqual(stability.sample_size, 3)
        self.assertEqual(stability.total_score.range, 20.0)
        self.assertEqual(stability.cases[0].case_id, "memory_delayed_recall_same_session_cn")
        self.assertEqual(stability.cases[0].anchor_strength, "strong")
        self.assertAlmostEqual(stability.cases[0].failover_rate, 0.3333, places=4)
        self.assertTrue(stability.cases[0].unstable)
        self.assertIn("status_flap", stability.cases[0].unstable_reasons)
        self.assertEqual(stability.components[0].key, "delayed_recall")
        self.assertEqual(stability.components[0].score.range, 50.0)

    def test_extract_total_tokens_from_result_falls_back_to_run_level_totals(self) -> None:
        result = self._case(
            "eval_now",
            "direct_answer_cn",
            total_score=100.0,
            status="passed",
        ).model_copy(
            update={
                "diagnostics_json": {
                    "turns": [
                        {
                            "run": {
                                "actual_cumulative_total_tokens": 4653,
                                "actual_peak_total_tokens": 3280,
                            }
                        }
                    ]
                }
            }
        )

        from marten_runtime.evals.compare import _extract_total_tokens_from_result

        self.assertEqual(_extract_total_tokens_from_result(result), 4653.0)

    def test_compare_eval_runs_reports_token_tool_and_llm_request_deltas(self) -> None:
        baseline_summary = self._summary("eval_base", total_score=90.0, pass_rate=1.0)
        current_summary = self._summary("eval_now", total_score=95.0, pass_rate=1.0)
        baseline_cases = [
            self._case("eval_base", "challenge_case", total_score=90.0, status="passed").model_copy(
                update={
                    "llm_request_count": 4,
                    "tool_calls_count": 5,
                    "diagnostics_json": {
                        "turns": [
                            {"run": {"latest_actual_usage": {"total_tokens": 2000}}}
                        ]
                    },
                }
            )
        ]
        current_cases = [
            self._case("eval_now", "challenge_case", total_score=95.0, status="passed").model_copy(
                update={
                    "llm_request_count": 3,
                    "tool_calls_count": 4,
                    "diagnostics_json": {
                        "turns": [
                            {"run": {"latest_actual_usage": {"total_tokens": 1500}}}
                        ]
                    },
                }
            )
        ]

        compare = compare_eval_runs(
            current_summary,
            current_cases,
            baseline_summary,
            baseline_cases,
            baseline_source="latest_passed",
        )

        self.assertEqual(compare.token_total_delta, -500.0)
        self.assertEqual(compare.tool_calls_delta, -1.0)
        self.assertEqual(compare.llm_requests_delta, -1.0)


if __name__ == "__main__":
    unittest.main()
