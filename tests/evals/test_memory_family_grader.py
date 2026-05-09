import unittest

from marten_runtime.evals.family_graders.memory_long_horizon import grade_memory_long_horizon_case_result
from marten_runtime.evals.models import EvalCaseObservation, EvalCaseSpec, EvalTurnSpec


class MemoryFamilyGraderTests(unittest.TestCase):
    def test_grade_memory_case_passes_with_expected_capture_and_recall(self) -> None:
        case = EvalCaseSpec(
            case_id="memory_delayed_recall_same_session_cn",
            suite_id="memory_long_horizon",
            family="memory_long_horizon",
            grader_id="memory_long_horizon",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[
                EvalTurnSpec(role="user", content="记住：周报默认先给结论后给细节。"),
                EvalTurnSpec(role="user", content="我刚才的周报偏好是什么？"),
            ],
            component_weights={"capture": 30, "delayed_recall": 70},
            gate_components=["capture", "delayed_recall"],
            grader_case={
                "expected_memory_action": "append",
                "expected_section": "preferences",
                "expected_content_contains": ["先给结论后给细节"],
                "recall_contains_all": ["先给结论后给细节"],
                "max_memory_calls": 1,
            },
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="你刚才设定的是：周报默认先给结论后给细节。",
            tool_calls=[
                {
                    "tool_name": "memory",
                    "tool_payload": {
                        "action": "append",
                        "section": "preferences",
                        "content": "周报默认先给结论后给细节。",
                    },
                }
            ],
            diagnostics_json={"turns": [{}, {}]},
        )

        result = grade_memory_long_horizon_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)
        self.assertEqual(result.score_breakdown_json["components"][0]["key"], "capture")

    def test_grade_memory_case_fails_when_stale_value_leaks(self) -> None:
        case = EvalCaseSpec(
            case_id="memory_stale_conflict_rejection_cn",
            suite_id="memory_long_horizon",
            family="memory_long_horizon",
            grader_id="memory_long_horizon",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="现在再说一遍周报顺序。")],
            component_weights={"overwrite_correctness": 40, "stale_rejection": 60},
            gate_components=["overwrite_correctness", "stale_rejection"],
            grader_case={
                "expected_memory_action": "replace",
                "recall_contains_all": ["先结论", "后细节"],
                "recall_forbid_all": ["先背景", "后结论"],
            },
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="周报还是先背景后结论。",
            tool_calls=[
                {
                    "tool_name": "memory",
                    "tool_payload": {
                        "action": "replace",
                        "section": "preferences",
                        "content": "先结论，后细节。",
                    },
                }
            ],
            diagnostics_json={"turns": [{}, {}]},
        )

        result = grade_memory_long_horizon_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "failed")
        stale = {item["key"]: item for item in result.score_breakdown_json["components"]}["stale_rejection"]
        self.assertFalse(stale["passed"])

    def test_grade_memory_case_accepts_paraphrase_when_anchor_groups_and_memory_evidence_match(self) -> None:
        case = EvalCaseSpec(
            case_id="memory_long_gap_with_interference_recall_cn",
            suite_id="memory_long_horizon",
            family="memory_long_horizon",
            grader_id="memory_long_horizon",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[
                EvalTurnSpec(role="user", content="记住：日报先给风险再给结论。"),
                EvalTurnSpec(role="user", content="隔几轮后提醒我刚才的日报顺序。"),
            ],
            component_weights={"delayed_recall": 60, "utility_gain": 40},
            gate_components=["delayed_recall", "utility_gain"],
            grader_case={
                "recall_contains_all": ["日报", "先给风险", "再给结论"],
                "recall_anchor_groups": [
                    ["先讲风险", "先给风险", "风险放前面"],
                    ["再下结论", "再给结论", "结论放后面"],
                ],
                "utility_contains_all": ["日报", "先给风险", "再给结论"],
                "utility_anchor_groups": [
                    ["先讲风险", "先给风险", "风险放前面"],
                    ["再下结论", "再给结论", "结论放后面"],
                ],
                "max_memory_calls": 1,
            },
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="沿用你刚才设定的日报顺序：风险放前面，结论放后面。",
            tool_calls=[
                {
                    "tool_name": "memory",
                    "tool_payload": {"action": "get", "section": "preferences"},
                    "tool_result": {"ok": True, "action": "get", "sections": {"preferences": ["日报先给风险再给结论。"]}},
                }
            ],
            diagnostics_json={"turns": [{}, {}, {}, {}]},
        )

        result = grade_memory_long_horizon_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "passed")
        components = {item["key"]: item for item in result.score_breakdown_json["components"]}
        self.assertTrue(components["delayed_recall"]["passed"])
        self.assertTrue(components["utility_gain"]["passed"])

    def test_overwrite_correctness_ignores_stale_memory_call_text_when_final_text_uses_new_order(self) -> None:
        case = EvalCaseSpec(
            case_id="memory_overwrite_then_recall_cn",
            suite_id="memory_long_horizon",
            family="memory_long_horizon",
            grader_id="memory_long_horizon",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[
                EvalTurnSpec(role="user", content="更新偏好：以后日报先给风险，再给结论。"),
                EvalTurnSpec(role="user", content="现在日报该怎么组织？"),
            ],
            component_weights={"capture": 20, "overwrite_correctness": 50, "stale_rejection": 30},
            gate_components=["overwrite_correctness", "stale_rejection"],
            grader_case={
                "expected_memory_action": "replace",
                "expected_section": "preferences",
                "expected_content_contains": ["先给风险", "再给结论"],
                "recall_anchor_groups": [
                    ["1. **风险**", "先给风险", "风险在前"],
                    ["2. **结论**", "再给结论", "结论在后"],
                ],
                "recall_forbid_all": ["只给结论"],
            },
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="按当前偏好组织：\n1. **风险**\n2. **结论**",
            tool_calls=[
                {
                    "tool_name": "memory",
                    "tool_payload": {
                        "action": "replace",
                        "section": "preferences",
                        "content": "日报默认只给结论，不展开风险。",
                    },
                },
                {
                    "tool_name": "memory",
                    "tool_payload": {
                        "action": "replace",
                        "section": "preferences",
                        "content": "日报先给风险，再给结论。",
                    },
                },
            ],
            diagnostics_json={"turns": [{}, {}, {}]},
        )

        result = grade_memory_long_horizon_case_result(case, observation, "eval_1")

        components = {item["key"]: item for item in result.score_breakdown_json["components"]}
        self.assertTrue(components["overwrite_correctness"]["passed"])
        self.assertTrue(components["stale_rejection"]["passed"])


if __name__ == "__main__":
    unittest.main()
