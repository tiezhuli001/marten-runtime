import unittest

from marten_runtime.evals.family_graders.subagent_task_progress import grade_subagent_task_progress_case_result
from marten_runtime.evals.models import EvalCaseObservation, EvalCaseSpec, EvalTurnSpec


class SubagentFamilyGraderTests(unittest.TestCase):
    def test_grade_subagent_case_passes_with_child_completion_and_parent_integration(self) -> None:
        case = EvalCaseSpec(
            case_id="subagent_followup_uses_child_result_cn",
            suite_id="subagent_task_progress",
            family="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[
                EvalTurnSpec(role="user", content="后台看一下最近提交都在改什么。"),
                EvalTurnSpec(role="user", content="直接告诉我你吸收后的结论。"),
            ],
            component_weights={"delegation_quality": 20, "child_completion": 30, "parent_integration": 50},
            gate_components=["child_completion", "parent_integration"],
            grader_case={
                "expected_spawn_count": 1,
                "integration_contains_all": ["最近提交", "评测"],
            },
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="我吸收后的结论：最近提交主要集中在评测与报告。",
            tool_calls=[{"tool_name": "spawn_subagent"}],
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {
                            "task_id": "task_1",
                            "label": "commit-check",
                            "status": "succeeded",
                            "child_session_id": "sess_child",
                            "child_run_id": "run_child",
                            "result_summary": "最近提交主要集中在评测与报告。",
                            "child_run": {"final_text": "最近提交主要集中在评测与报告。"},
                        }
                    ],
                    "parent_session": {
                        "history": [
                            {"role": "system", "content": "subagent task completed: commit-check\nsummary: 最近提交主要集中在评测与报告。"}
                        ]
                    },
                }
            },
        )

        result = grade_subagent_task_progress_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)

    def test_grade_subagent_case_penalizes_duplicate_dispatch(self) -> None:
        case = EvalCaseSpec(
            case_id="subagent_duplicate_dispatch_penalty_cn",
            suite_id="subagent_task_progress",
            family="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="继续跟进刚才那个后台任务。")],
            component_weights={"duplicate_dispatch_penalty": 100},
            gate_components=["duplicate_dispatch_penalty"],
            grader_case={"expected_spawn_count": 1, "max_spawn_count": 1},
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="已有结果。",
            tool_calls=[{"tool_name": "spawn_subagent"}, {"tool_name": "spawn_subagent"}],
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {"task_id": "task_1", "label": "readme-check", "status": "succeeded"},
                        {"task_id": "task_2", "label": "readme-check", "status": "succeeded"},
                    ]
                }
            },
        )

        result = grade_subagent_task_progress_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "failed")
        penalty = result.score_breakdown_json["components"][0]
        self.assertFalse(penalty["passed"])

    def test_grade_subagent_case_accepts_paraphrase_when_child_evidence_and_anchor_groups_match(self) -> None:
        case = EvalCaseSpec(
            case_id="subagent_followup_uses_child_result_cn",
            suite_id="subagent_task_progress",
            family="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[
                EvalTurnSpec(role="user", content="后台看一下最近提交都在改什么。"),
                EvalTurnSpec(role="user", content="把吸收后的结论直接告诉我。"),
            ],
            component_weights={"child_completion": 40, "parent_integration": 60},
            gate_components=["child_completion", "parent_integration"],
            grader_case={
                "expected_spawn_count": 1,
                "integration_contains_all": ["最近提交"],
                "integration_anchor_groups": [
                    ["最近提交", "近期提交"],
                    ["评测", "评估"],
                    ["报告", "汇总"],
                ],
            },
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="我已经吸收了后台结果：近期提交主要围绕评估链路和汇总输出。",
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {
                            "task_id": "task_1",
                            "label": "commit-check",
                            "status": "succeeded",
                            "child_session_id": "sess_child",
                            "child_run_id": "run_child",
                            "result_summary": "最近提交主要集中在评测与报告。",
                            "child_run": {"final_text": "最近提交主要集中在评测与报告。"},
                        }
                    ],
                    "parent_session": {
                        "history": [
                            {"role": "system", "content": "subagent task completed: commit-check\nsummary: 最近提交主要集中在评测与报告。"}
                        ]
                    },
                }
            },
        )

        result = grade_subagent_task_progress_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "passed")
        components = {item["key"]: item for item in result.score_breakdown_json["components"]}
        self.assertTrue(components["parent_integration"]["passed"])

    def test_grade_subagent_case_ignores_runtime_owned_self_improve_children(self) -> None:
        case = EvalCaseSpec(
            case_id="subagent_multi_child_progress_cn",
            suite_id="subagent_task_progress",
            family="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[
                EvalTurnSpec(role="user", content="拆成两个子任务。"),
                EvalTurnSpec(role="user", content="合并两个子任务结果。"),
            ],
            component_weights={
                "delegation_quality": 20,
                "child_progress": 20,
                "child_completion": 20,
                "parent_integration": 20,
                "duplicate_dispatch_penalty": 20,
            },
            gate_components=["child_completion", "parent_integration", "duplicate_dispatch_penalty"],
            grader_case={
                "expected_spawn_count": 2,
                "max_spawn_count": 2,
                "expected_task_labels": ["commit-check", "readme-check"],
                "integration_contains_all": ["最近提交", "README结构"],
                "integration_anchor_groups": [
                    ["最近提交", "近期提交"],
                    ["README结构", "README 结构"],
                    ["快速开始", "配置", "评测入口"],
                ],
            },
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="两个子任务都完成了：最近提交主要集中在评测与报告；README结构包含快速开始、配置和评测入口。",
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {
                            "task_id": "task_1",
                            "label": "commit-check",
                            "status": "succeeded",
                            "child_session_id": "sess_commit",
                            "child_run_id": "run_commit",
                            "result_summary": "最近提交主要集中在评测与报告。",
                            "child_run": {"final_text": "最近提交主要集中在评测与报告。"},
                        },
                        {
                            "task_id": "task_2",
                            "label": "readme-check",
                            "status": "succeeded",
                            "child_session_id": "sess_readme",
                            "child_run_id": "run_readme",
                            "result_summary": "README结构包含快速开始、配置和评测入口。",
                            "child_run": {"final_text": "README结构包含快速开始、配置和评测入口。"},
                        },
                        {
                            "task_id": "task_3",
                            "label": "self-improve-review:trigger_demo",
                            "status": "succeeded",
                            "child_session_id": "sess_internal",
                            "child_run_id": "run_internal",
                            "result_summary": "内部候选已审查。",
                            "child_run": {"final_text": "内部候选已审查。"},
                        },
                    ],
                    "parent_session": {
                        "history": [
                            {"role": "system", "content": "subagent task completed: commit-check\nsummary: 最近提交主要集中在评测与报告。"},
                            {"role": "system", "content": "subagent task completed: readme-check\nsummary: README结构包含快速开始、配置和评测入口。"},
                        ]
                    },
                }
            },
        )

        result = grade_subagent_task_progress_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)

    def test_grade_subagent_case_accepts_child_summary_when_parent_history_notice_is_missing(self) -> None:
        case = EvalCaseSpec(
            case_id="subagent_multi_child_progress_cn",
            suite_id="subagent_task_progress",
            family="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[
                EvalTurnSpec(role="user", content="拆成两个子任务。"),
                EvalTurnSpec(role="user", content="合并两个子任务结果。"),
            ],
            component_weights={"child_completion": 40, "parent_integration": 60},
            gate_components=["child_completion", "parent_integration"],
            grader_case={
                "integration_contains_all": ["最近提交", "README结构"],
                "integration_anchor_groups": [
                    ["最近提交", "近期提交"],
                    ["README结构", "README 结构"],
                    ["快速开始", "配置", "评测入口"],
                ],
            },
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="两个子任务都完成了：最近提交主要集中在评测与报告；README结构包含快速开始、配置和评测入口。",
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {
                            "task_id": "task_1",
                            "label": "commit-check",
                            "status": "succeeded",
                            "child_session_id": "sess_commit",
                            "child_run_id": "run_commit",
                            "result_summary": "最近提交主要集中在评测与报告。",
                            "child_run": {"final_text": "最近提交主要集中在评测与报告。"},
                        },
                        {
                            "task_id": "task_2",
                            "label": "readme-check",
                            "status": "succeeded",
                            "child_session_id": "sess_readme",
                            "child_run_id": "run_readme",
                            "result_summary": "README结构包含快速开始、配置和评测入口。",
                            "child_run": {"final_text": "README结构包含快速开始、配置和评测入口。"},
                        },
                    ],
                    "parent_session": {
                        "history": [
                            {"role": "system", "content": "subagent task completed: commit-check\nsummary: 最近提交主要集中在评测与报告。"},
                        ]
                    },
                }
            },
        )

        result = grade_subagent_task_progress_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "passed")
        components = {item["key"]: item for item in result.score_breakdown_json["components"]}
        self.assertTrue(components["parent_integration"]["passed"])

    def test_grade_child_completion_notice_accepts_anchor_groups_from_child_evidence_when_final_text_is_short(self) -> None:
        case = EvalCaseSpec(
            case_id="subagent_child_completion_notice_cn",
            suite_id="subagent_task_progress",
            family="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[
                EvalTurnSpec(role="user", content="把这个仓库的结构梳理放到后台做，完成后通知我。"),
                EvalTurnSpec(role="user", content="子任务完成了吗？直接给我一句中文摘要，明确它梳理的对象和结论。"),
            ],
            component_weights={"parent_integration": 100},
            gate_components=["parent_integration"],
            grader_case={
                "integration_contains_all": ["仓库结构"],
                "integration_anchor_groups": [
                    ["仓库结构", "项目结构"],
                    ["顶层目录", "主要模块", "关键配置", "测试与文档"],
                ],
            },
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="已完成。仓库结构已经梳理完，结论是主链清晰。",
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {
                            "task_id": "task_1",
                            "label": "梳理仓库结构",
                            "status": "succeeded",
                            "child_session_id": "sess_child",
                            "child_run_id": "run_child",
                            "result_summary": "仓库结构梳理覆盖了顶层目录、主要模块、关键配置与测试和文档位置。",
                            "child_run": {},
                        }
                    ],
                    "parent_session": {
                        "history": [
                            {
                                "role": "system",
                                "content": "subagent task completed: 梳理仓库结构\nsummary: 仓库结构梳理覆盖了顶层目录、主要模块、关键配置与测试和文档位置。"
                            }
                        ]
                    },
                }
            },
        )

        result = grade_subagent_task_progress_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "passed")
        components = {item["key"]: item for item in result.score_breakdown_json["components"]}
        self.assertTrue(components["parent_integration"]["passed"])

    def test_grade_duplicate_dispatch_case_accepts_required_tokens_from_child_final_text(self) -> None:
        case = EvalCaseSpec(
            case_id="subagent_duplicate_dispatch_penalty_cn",
            suite_id="subagent_task_progress",
            family="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="demo",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[
                EvalTurnSpec(role="user", content="把 README 结构放到后台看一下。"),
                EvalTurnSpec(role="user", content="继续跟进刚才那个后台任务，直接告诉我已有结果。"),
            ],
            component_weights={"parent_integration": 100},
            gate_components=["parent_integration"],
            grader_case={"integration_contains_all": ["README", "快速开始"]},
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="后台子任务《README 结构梳理》已完成。README 结构清晰。",
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {
                            "task_id": "task_1",
                            "label": "README 结构梳理",
                            "status": "succeeded",
                            "child_session_id": "sess_child",
                            "child_run_id": "run_child",
                            "result_summary": "README 结构整体清晰。",
                            "child_run": {
                                "final_text": "README 结构整体清晰，快速开始部分给出了本地初始化入口。"
                            },
                        }
                    ],
                    "parent_session": {
                        "history": [
                            {
                                "role": "system",
                                "content": "subagent task completed: README 结构梳理\nsummary: README 结构整体清晰。"
                            }
                        ]
                    },
                }
            },
        )

        result = grade_subagent_task_progress_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "passed")
        components = {item["key"]: item for item in result.score_breakdown_json["components"]}
        self.assertTrue(components["parent_integration"]["passed"])


if __name__ == "__main__":
    unittest.main()
