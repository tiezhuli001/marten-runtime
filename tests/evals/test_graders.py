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


class EvalGradersTests(unittest.TestCase):
    def _build_case(self) -> EvalCaseSpec:
        return EvalCaseSpec(
            case_id="time_single_tool_cn",
            suite_id="main_chain_core",
            family="single_tool",
            description="time tool case",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="告诉我北京时间")],
            expectations=EvalExpectations(
                final_text=EvalFinalTextExpectations(
                    contains_all=["现在是北京时间"],
                    contains_any=[":", "点"],
                    forbid_all=["无法访问"],
                ),
                tool_path=EvalToolCallExpectations(
                    required_calls=[EvalToolCallRule(tool_name="time", min_calls=1, max_calls=1)],
                    forbidden_calls=["mcp"],
                ),
                efficiency=EvalEfficiencyExpectations(max_llm_requests=1, max_tool_calls=1),
                context=EvalContextExpectations(expect_compaction=False),
                diagnostics=EvalDiagnosticsExpectations(expect_provider_ref="openai"),
            ),
            weights=EvalWeights(outcome=60, tool_path=25, efficiency=10, context=5),
        )

    def test_grade_case_result_for_full_match(self) -> None:
        case = self._build_case()
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

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)

    def test_grade_case_result_marks_failure_for_missing_required_tool(self) -> None:
        case = self._build_case()
        observation = EvalCaseObservation(
            case_id="time_single_tool_cn",
            family="single_tool",
            final_text="现在是北京时间 2026年4月30日 12:00",
            llm_request_count=1,
            tool_calls_count=0,
            run_id="run_1",
            trace_id="trace_1",
            tool_calls=[],
            diagnostics_json={
                "provider_ref": "openai",
                "compaction": {"used_compacted_context": False},
            },
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "failed")
        self.assertLess(result.total_score, 100.0)
        self.assertEqual(result.tool_path_score, 0.0)


if __name__ == "__main__":
    unittest.main()
