import unittest

from marten_runtime.evals.graders import grade_case_result
from marten_runtime.evals.models import EvalCaseObservation, EvalCaseSpec, EvalTurnSpec


def _case(*, component_weights: dict[str, int], gate_components: list[str] | None = None, grader_case=None) -> EvalCaseSpec:
    return EvalCaseSpec(
        case_id="challenge_case",
        suite_id="challenge_memory",
        family="challenge",
        grader_id="challenge",
        description="challenge case",
        agent_id="main",
        profile_name="openai_gpt_5_4",
        turns=[EvalTurnSpec(role="user", content="test")],
        component_weights=component_weights,
        gate_components=gate_components or list(component_weights),
        grader_case=grader_case or {},
    )


class ChallengeFamilyGraderTests(unittest.TestCase):
    def test_challenge_grader_scores_text_anchor_components(self) -> None:
        case = _case(
            component_weights={"task_success": 60, "reasoning_quality": 40},
            grader_case={
                "task_success": {
                    "contains_all": ["SQLite"],
                    "contains_any": ["memory", "记忆"],
                    "forbid_all": ["无法确认"],
                    "anchor_groups": [["scope", "隔离"]],
                },
                "reasoning_quality": {
                    "contains_all": ["证据"],
                },
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="基于证据，SQLite memory 已保持 scope 隔离。",
            diagnostics_json={},
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)
        components = {item["key"]: item for item in result.score_breakdown_json["components"]}
        self.assertTrue(components["task_success"]["passed"])
        self.assertTrue(components["reasoning_quality"]["passed"])

    def test_challenge_grader_partial_score_when_one_component_fails(self) -> None:
        case = _case(
            component_weights={"task_success": 70, "reasoning_quality": 30},
            gate_components=["task_success"],
            grader_case={
                "task_success": {"contains_all": ["SQLite"]},
                "reasoning_quality": {"contains_all": ["证据"]},
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="SQLite memory 已完成。",
            diagnostics_json={},
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 70.0)
        components = {item["key"]: item for item in result.score_breakdown_json["components"]}
        self.assertFalse(components["reasoning_quality"]["passed"])

    def test_challenge_grader_scores_tool_path_rules(self) -> None:
        case = _case(
            component_weights={"tool_path_quality": 100},
            grader_case={
                "tool_path_quality": {
                    "required_tools": ["memory"],
                    "forbidden_tools": ["spawn_subagent"],
                    "min_tool_calls": 1,
                    "max_tool_calls": 2,
                    "required_skill_ids": ["long-run-execution"],
                    "forbidden_skill_ids": ["code-review"],
                }
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="done",
            tool_calls_count=2,
            tool_calls=[
                {"tool_name": "memory", "tool_payload": {"action": "get"}},
                {"tool_name": "skill", "tool_payload": {"skill_id": "long-run-execution"}},
            ],
            diagnostics_json={},
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)

    def test_challenge_grader_fails_forbidden_tool_path_rules(self) -> None:
        case = _case(
            component_weights={"tool_path_quality": 100},
            grader_case={
                "tool_path_quality": {
                    "required_tools": ["memory"],
                    "forbidden_tools": ["spawn_subagent"],
                    "max_tool_calls": 1,
                    "forbidden_skill_ids": ["code-review"],
                }
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="done",
            tool_calls_count=3,
            tool_calls=[
                {"tool_name": "memory", "tool_payload": {"action": "get"}},
                {"tool_name": "spawn_subagent", "tool_payload": {"task": "x"}},
                {"tool_name": "skill", "tool_payload": {"skill_id": "code-review"}},
            ],
            diagnostics_json={},
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.total_score, 0.0)

    def test_challenge_grader_scores_state_continuity(self) -> None:
        case = _case(
            component_weights={"state_continuity": 100},
            grader_case={
                "state_continuity": {
                    "required_memory_sections": ["preferences"],
                    "forbidden_memory_tokens": ["旧偏好"],
                    "required_subagent_labels": ["repo-investigation"],
                    "require_subagent_completion": True,
                    "required_skill_ids": ["long-run-execution"],
                }
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="done",
            tool_calls=[
                {
                    "tool_name": "memory",
                    "tool_payload": {"section": "preferences", "content": "新偏好"},
                    "tool_result": {"sections": {"preferences": ["新偏好"]}},
                },
                {"tool_name": "skill", "tool_result": {"skill_id": "long-run-execution"}},
            ],
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {
                            "label": "repo-investigation",
                            "status": "succeeded",
                            "result_summary": "done",
                        }
                    ]
                }
            },
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)


    def test_challenge_grader_rejects_tool_failure_as_success(self) -> None:
        case = _case(
            component_weights={"task_success": 50, "tool_path_quality": 50},
            gate_components=["task_success", "tool_path_quality"],
            grader_case={
                "task_success": {
                    "contains_all": ["风险", "结论"],
                    "forbid_all": ["工具执行失败", "请重试"],
                },
                "tool_path_quality": {"required_tools": ["memory", "mcp"], "min_tool_calls": 2},
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="工具执行失败，请重试。",
            tool_calls=[{"tool_name": "memory", "tool_payload": {"section": "preferences"}}],
            diagnostics_json={},
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "failed")
        components = {item["key"]: item for item in result.score_breakdown_json["components"]}
        self.assertFalse(components["task_success"]["passed"])
        self.assertFalse(components["tool_path_quality"]["passed"])

    def test_challenge_grader_requires_child_mcp_completion(self) -> None:
        case = _case(
            component_weights={"state_continuity": 100},
            gate_components=["state_continuity"],
            grader_case={
                "state_continuity": {
                    "require_subagent_completion": True,
                    "required_child_tools": ["mcp"],
                }
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="已受理，子 agent 正在后台执行，完成后会通知你结果。",
            diagnostics_json={"subagent": {"tasks": []}},
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "failed")
        components = {item["key"]: item for item in result.score_breakdown_json["components"]}
        self.assertFalse(components["state_continuity"]["passed"])


    def test_challenge_grader_scores_text_rubric_items_partially(self) -> None:
        case = _case(
            component_weights={"task_success": 100},
            gate_components=[],
            grader_case={
                "task_success": {
                    "rubric_items": [
                        {"id": "has_risk", "points": 4, "contains_all": ["风险"]},
                        {"id": "has_conclusion", "points": 4, "contains_all": ["结论"]},
                        {"id": "no_guess", "points": 2, "forbid_all": ["我猜"]},
                    ]
                }
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="风险：需要补证据。",
            diagnostics_json={},
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.total_score, 60.0)
        component = result.score_breakdown_json["components"][0]
        self.assertEqual(component["ratio"], 0.6)
        rubric = component["details"]["rubric_items"]
        self.assertEqual([item["id"] for item in rubric], ["has_risk", "has_conclusion", "no_guess"])
        self.assertEqual([item["earned"] for item in rubric], [4.0, 0.0, 2.0])

    def test_challenge_grader_zeroes_rubric_when_component_prerequisite_fails(self) -> None:
        case = _case(
            component_weights={"task_success": 100},
            gate_components=["task_success"],
            grader_case={
                "task_success": {
                    "contains_all": ["风险"],
                    "rubric_items": [
                        {"id": "has_conclusion", "points": 4, "contains_all": ["结论"]},
                    ],
                }
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="结论：可以继续。",
            diagnostics_json={},
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.total_score, 0.0)
        component = result.score_breakdown_json["components"][0]
        self.assertFalse(component["details"]["prerequisite_passed"])

    def test_challenge_grader_scores_tool_and_state_rubric_items_partially(self) -> None:
        case = _case(
            component_weights={"tool_path_quality": 50, "state_continuity": 50},
            gate_components=[],
            grader_case={
                "tool_path_quality": {
                    "rubric_items": [
                        {"id": "called_memory", "points": 2, "required_tools": ["memory"]},
                        {"id": "called_mcp", "points": 4, "required_tools": ["mcp"]},
                    ]
                },
                "state_continuity": {
                    "rubric_items": [
                        {"id": "used_preferences", "points": 3, "required_memory_sections": ["preferences"]},
                        {"id": "child_mcp", "points": 3, "require_subagent_completion": True, "required_child_tools": ["mcp"]},
                    ]
                },
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="done",
            tool_calls=[
                {"tool_name": "memory", "tool_payload": {"section": "preferences"}},
            ],
            diagnostics_json={"subagent": {"tasks": []}},
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.total_score, 41.6667)
        components = {item["key"]: item for item in result.score_breakdown_json["components"]}
        self.assertEqual(components["tool_path_quality"]["ratio"], 0.3333)
        self.assertEqual(components["state_continuity"]["ratio"], 0.5)
        self.assertEqual([item["earned"] for item in components["tool_path_quality"]["details"]["rubric_items"]], [2.0, 0.0])
        self.assertEqual([item["earned"] for item in components["state_continuity"]["details"]["rubric_items"]], [3.0, 0.0])


    def test_challenge_grader_requires_subagent_prompt_tokens(self) -> None:
        case = _case(
            component_weights={"state_continuity": 100},
            gate_components=["state_continuity"],
            grader_case={
                "state_continuity": {
                    "required_subagent_prompt_tokens": ["README", "评测入口"],
                }
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="done",
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {
                            "label": "repo-investigation",
                            "status": "succeeded",
                            "result_summary": "done",
                            "task_prompt": "inspect README main chain only",
                        }
                    ]
                }
            },
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "failed")
        component = result.score_breakdown_json["components"][0]
        self.assertFalse(component["passed"])
        self.assertEqual(component["details"]["required_subagent_prompt_tokens"], ["README", "评测入口"])

    def test_challenge_grader_requires_final_text_to_cover_child_result_tokens(self) -> None:
        case = _case(
            component_weights={"state_continuity": 100},
            gate_components=["state_continuity"],
            grader_case={
                "state_continuity": {
                    "required_child_result_tokens_in_final": ["runtime harness", "scripts/run_eval.py"],
                }
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="整合子代理结果：runtime harness。",
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {
                            "label": "repo-investigation",
                            "status": "succeeded",
                            "result_summary": "runtime harness; scripts/run_eval.py",
                        }
                    ]
                }
            },
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "failed")
        component = result.score_breakdown_json["components"][0]
        self.assertFalse(component["passed"])
        self.assertEqual(component["details"]["required_child_result_tokens_in_final"], ["runtime harness", "scripts/run_eval.py"])


    def test_challenge_grader_can_limit_text_rules_to_final_answer(self) -> None:
        case = _case(
            component_weights={"task_success": 100},
            gate_components=["task_success"],
            grader_case={
                "task_success": {
                    "evidence_source": "final",
                    "contains_all": ["风险", "结论"],
                    "forbid_all": ["临时改成先写结论"],
                }
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="现在默认先写风险，再写结论。",
            tool_calls=[
                {"tool_name": "memory", "tool_payload": {"source_excerpt": "临时改成先写结论"}},
            ],
            diagnostics_json={},
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)
        component = result.score_breakdown_json["components"][0]
        self.assertEqual(component["details"]["evidence_source"], "final")

    def test_challenge_grader_scores_efficiency(self) -> None:
        case = _case(
            component_weights={"efficiency": 100},
            grader_case={
                "efficiency": {
                    "max_llm_requests": 2,
                    "max_tool_calls": 1,
                    "max_total_tokens": 500,
                    "max_repair_attempts": 1,
                    "allow_failover": False,
                }
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="done",
            llm_request_count=2,
            tool_calls_count=1,
            diagnostics_json={
                "turns": [
                    {"run": {"latest_actual_usage": {"total_tokens": 450}, "contract_repair_count": 1}}
                ]
            },
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)

    def test_challenge_grader_fails_efficiency_thresholds(self) -> None:
        case = _case(
            component_weights={"efficiency": 100},
            grader_case={
                "efficiency": {
                    "max_llm_requests": 1,
                    "max_tool_calls": 1,
                    "max_total_tokens": 100,
                    "max_repair_attempts": 0,
                    "allow_failover": False,
                }
            },
        )
        observation = EvalCaseObservation(
            case_id="challenge_case",
            family="challenge",
            final_text="done",
            llm_request_count=2,
            tool_calls_count=2,
            diagnostics_json={
                "turns": [
                    {
                        "run": {
                            "latest_actual_usage": {"total_tokens": 450},
                            "contract_repair_count": 1,
                            "attempted_profiles": ["openai", "minimax"],
                        }
                    }
                ]
            },
        )

        result = grade_case_result(case, observation, eval_run_id="eval_1")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.total_score, 0.0)


if __name__ == "__main__":
    unittest.main()
