import unittest

from pydantic import ValidationError

from marten_runtime.evals.models import (
    EvalCaseResult,
    EvalCaseSpec,
    EvalComponentComparison,
    EvalComponentScore,
    EvalComponentSummary,
    EvalEfficiencyExpectations,
    EvalExpectations,
    EvalFinalTextExpectations,
    EvalRunStabilitySummary,
    EvalRunSummary,
    EvalStabilityCaseSummary,
    EvalStabilityComponentSummary,
    EvalStabilityStats,
    EvalSuiteSpec,
    EvalToolCallExpectations,
    EvalToolCallRule,
    EvalTurnSpec,
    EvalWeights,
)


class EvalModelsTests(unittest.TestCase):
    def test_weights_sum_to_100(self) -> None:
        weights = EvalWeights(outcome=60, tool_path=25, efficiency=10, context=5)

        self.assertEqual(weights.total(), 100)

    def test_weights_reject_invalid_total(self) -> None:
        with self.assertRaises(ValidationError):
            EvalWeights(outcome=60, tool_path=25, efficiency=10, context=10)

    def test_tool_call_rule_rejects_invalid_range(self) -> None:
        with self.assertRaises(ValidationError):
            EvalToolCallRule(tool_name="time", min_calls=2, max_calls=1)

    def test_case_spec_requires_turns(self) -> None:
        case = EvalCaseSpec(
            case_id="case_1",
            suite_id="suite_1",
            family="direct_answer",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="你好")],
            expectations=EvalExpectations(
                final_text=EvalFinalTextExpectations(contains_any=["你好"]),
                tool_path=EvalToolCallExpectations(
                    required_calls=[EvalToolCallRule(tool_name="time", min_calls=0, max_calls=1)]
                ),
                efficiency=EvalEfficiencyExpectations(max_llm_requests=2, max_tool_calls=1),
            ),
            weights=EvalWeights(outcome=70, tool_path=20, efficiency=10, context=0),
        )

        self.assertEqual(case.turns[0].role, "user")
        self.assertEqual(case.weights.total(), 100)

    def test_suite_spec_rejects_invalid_mode(self) -> None:
        with self.assertRaises(ValidationError):
            EvalSuiteSpec(
                suite_id="suite_1",
                description="demo",
                default_mode="invalid",
                scripted_supported=True,
                required_dependencies=["provider"],
                baseline_policy="latest_passed_auto",
                case_files=["evals/cases/main_chain_core/direct_answer_cn.toml"],
            )

    def test_case_spec_accepts_component_weights_and_gate_components(self) -> None:
        case = EvalCaseSpec(
            case_id="memory_capture_preference_cn",
            suite_id="memory_long_horizon",
            family="memory_long_horizon",
            grader_id="memory_long_horizon",
            description="memory capture",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="记住以后始终用中文回复")],
            expectations=EvalExpectations(),
            component_weights={"capture": 60, "delayed_recall": 40},
            gate_components=["capture"],
            grader_case={"expected_memory_action": "append"},
        )

        self.assertEqual(case.grader_id, "memory_long_horizon")
        self.assertEqual(case.component_weights["capture"], 60)
        self.assertEqual(case.gate_components, ["capture"])

    def test_case_spec_rejects_invalid_component_weights_total(self) -> None:
        with self.assertRaises(ValidationError):
            EvalCaseSpec(
                case_id="memory_capture_preference_cn",
                suite_id="memory_long_horizon",
                family="memory_long_horizon",
                grader_id="memory_long_horizon",
                description="memory capture",
                agent_id="main",
                profile_name="openai_gpt_5_4",
                turns=[EvalTurnSpec(role="user", content="记住以后始终用中文回复")],
                expectations=EvalExpectations(),
                component_weights={"capture": 60, "delayed_recall": 20},
                gate_components=["capture"],
                grader_case={"expected_memory_action": "append"},
            )

    def test_case_spec_rejects_unknown_gate_component(self) -> None:
        with self.assertRaises(ValidationError):
            EvalCaseSpec(
                case_id="memory_capture_preference_cn",
                suite_id="memory_long_horizon",
                family="memory_long_horizon",
                grader_id="memory_long_horizon",
                description="memory capture",
                agent_id="main",
                profile_name="openai_gpt_5_4",
                turns=[EvalTurnSpec(role="user", content="记住以后始终用中文回复")],
                expectations=EvalExpectations(),
                component_weights={"capture": 100},
                gate_components=["delayed_recall"],
                grader_case={"expected_memory_action": "append"},
            )

    def test_case_result_and_run_summary_store_required_fields(self) -> None:
        case_result = EvalCaseResult(
            eval_run_id="eval_main_chain_core_20260430010101_deadbee",
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
            score_breakdown_json={
                "components": [
                    EvalComponentScore(
                        key="outcome",
                        label="结果",
                        weight=70,
                        ratio=1.0,
                        score=70.0,
                        passed=True,
                        details={"matched": True},
                    ).model_dump(mode="json")
                ]
            },
            artifact_path="reports/evals/eval_main_chain_core_20260430010101_deadbee/cases/direct_answer_cn.json",
        )
        run_summary = EvalRunSummary(
            eval_run_id="eval_main_chain_core_20260430010101_deadbee",
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
            artifact_root="reports/evals/eval_main_chain_core_20260430010101_deadbee",
        )

        self.assertEqual(case_result.run_id, "run_1234")
        self.assertEqual(run_summary.eval_mode, "scripted")

    def test_run_summary_accepts_component_summary(self) -> None:
        run_summary = EvalRunSummary(
            eval_run_id="eval_memory_long_horizon_20260502010101_deadbee",
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
            total_score=90.0,
            pass_rate=1.0,
            status="passed",
            artifact_root="reports/evals/eval_memory_long_horizon_20260502010101_deadbee",
            component_summary=[
                EvalComponentSummary(
                    key="capture",
                    label="记忆写入",
                    current_score=95.0,
                    baseline_score=90.0,
                    delta=5.0,
                    case_count=3,
                )
            ],
        )

        self.assertEqual(run_summary.component_summary[0].key, "capture")
        self.assertEqual(run_summary.component_summary[0].delta, 5.0)

    def test_stability_models_store_nested_stats(self) -> None:
        summary = EvalRunStabilitySummary(
            suite_id="memory_long_horizon",
            profile_name="openai_gpt_5_4",
            eval_mode="live",
            window_size=5,
            sample_size=3,
            history_eval_run_ids=["eval_3", "eval_2", "eval_1"],
            total_score=EvalStabilityStats(sample_size=3, mean=95.0, min=90.0, max=100.0, range=10.0, stddev=4.0825),
            pass_rate=EvalStabilityStats(sample_size=3, mean=1.0, min=1.0, max=1.0, range=0.0, stddev=0.0),
            token_total=EvalStabilityStats(sample_size=3, mean=1200.0, min=1000.0, max=1500.0, range=500.0, stddev=204.1241),
            failover_rate=0.3333,
            unstable_case_count=1,
            unstable_component_count=1,
            cases=[
                EvalStabilityCaseSummary(
                    case_id="memory_delayed_recall_same_session_cn",
                    run_count=3,
                    status_values=["passed", "failed"],
                    pass_rate=0.6667,
                    score=EvalStabilityStats(sample_size=3, mean=76.6667, min=60.0, max=100.0, range=40.0, stddev=16.9967),
                    token_total=EvalStabilityStats(sample_size=3, mean=800.0, min=700.0, max=900.0, range=200.0, stddev=81.6497),
                    failover_rate=0.3333,
                    anchor_signal_count=5,
                    anchor_strength="strong",
                    unstable=True,
                    unstable_reasons=["score_range", "status_flap"],
                    components=[
                        EvalStabilityComponentSummary(
                            key="delayed_recall",
                            label="延迟召回",
                            score=EvalStabilityStats(
                                sample_size=3,
                                mean=46.6667,
                                min=20.0,
                                max=70.0,
                                range=50.0,
                                stddev=20.548,
                            ),
                            unstable=True,
                        )
                    ],
                )
            ],
            components=[
                EvalStabilityComponentSummary(
                    key="delayed_recall",
                    label="延迟召回",
                    score=EvalStabilityStats(sample_size=3, mean=60.0, min=50.0, max=70.0, range=20.0, stddev=8.165),
                    unstable=True,
                )
            ],
        )

        self.assertEqual(summary.sample_size, 3)
        self.assertEqual(summary.cases[0].anchor_strength, "strong")
        self.assertTrue(summary.components[0].unstable)


if __name__ == "__main__":
    unittest.main()
