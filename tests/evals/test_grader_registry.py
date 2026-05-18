import unittest

from marten_runtime.evals.graders import grade_case_result
from marten_runtime.evals.models import (
    EvalCaseObservation,
    EvalCaseSpec,
    EvalContextExpectations,
    EvalDiagnosticsExpectations,
    EvalEfficiencyExpectations,
    EvalExpectations,
    EvalFinalTextExpectations,
    EvalToolCallExpectations,
    EvalToolCallRule,
    EvalTurnSpec,
    EvalWeights,
)
from marten_runtime.evals.grader_registry import resolve_case_grader


class EvalGraderRegistryTests(unittest.TestCase):
    def test_main_chain_grader_writes_component_breakdown(self) -> None:
        case = EvalCaseSpec(
            case_id="time_single_tool_cn",
            suite_id="main_chain_core",
            family="single_tool",
            grader_id="main_chain_core",
            description="time tool case",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="告诉我北京时间")],
            expectations=EvalExpectations(
                final_text=EvalFinalTextExpectations(contains_all=["现在是北京时间"]),
                tool_path=EvalToolCallExpectations(
                    required_calls=[EvalToolCallRule(tool_name="time", min_calls=1, max_calls=1)]
                ),
                efficiency=EvalEfficiencyExpectations(max_llm_requests=1, max_tool_calls=1),
                context=EvalContextExpectations(expect_compaction=False),
                diagnostics=EvalDiagnosticsExpectations(expect_provider_ref="openai"),
            ),
            weights=EvalWeights(outcome=70, tool_path=20, efficiency=5, context=5),
        )
        observation = EvalCaseObservation(
            case_id="time_single_tool_cn",
            family="single_tool",
            final_text="现在是北京时间 2026年4月30日 12:00",
            llm_request_count=1,
            tool_calls_count=1,
            run_id="run_1",
            trace_id="trace_1",
            tool_calls=[{"tool_name": "time"}],
            diagnostics_json={
                "provider_ref": "openai",
                "compaction": {"used_compacted_context": False},
            },
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        components = result.score_breakdown_json.get("components") or []
        self.assertEqual([item["key"] for item in components], ["outcome", "tool_path", "efficiency", "context"])
        self.assertEqual(sum(float(item["score"]) for item in components), result.total_score)

    def test_registry_resolves_memory_family_grader(self) -> None:
        case = EvalCaseSpec(
            case_id="memory_capture_preference_cn",
            suite_id="memory_long_horizon",
            family="memory_long_horizon",
            grader_id="memory_long_horizon",
            description="memory family",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="记住偏好")],
            component_weights={"capture": 70, "utility_gain": 30},
            gate_components=["capture"],
            grader_case={
                "expected_memory_action": "append",
                "expected_section": "preferences",
                "expected_content_contains": ["中文"],
            },
        )

        self.assertEqual(resolve_case_grader(case).__name__, "grade_memory_long_horizon_case_result")

    def test_registry_resolves_subagent_family_grader(self) -> None:
        case = EvalCaseSpec(
            case_id="subagent_background_task_acceptance_cn",
            suite_id="subagent_task_progress",
            family="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="subagent family",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="后台处理")],
            component_weights={"delegation_quality": 60, "child_progress": 40},
            gate_components=["delegation_quality"],
            grader_case={"expected_spawn_count": 1},
        )

        self.assertEqual(resolve_case_grader(case).__name__, "grade_subagent_task_progress_case_result")

    def test_registry_resolves_challenge_grader(self) -> None:
        case = EvalCaseSpec(
            case_id="challenge_sample",
            suite_id="challenge_memory",
            family="challenge",
            grader_id="challenge",
            description="sample",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="test")],
            component_weights={"task_success": 100},
            gate_components=["task_success"],
        )

        self.assertEqual(resolve_case_grader(case).__name__, "grade_challenge_case_result")


if __name__ == "__main__":
    unittest.main()
