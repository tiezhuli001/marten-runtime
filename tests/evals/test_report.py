import json
import tempfile
import unittest
from pathlib import Path

from marten_runtime.evals.models import EvalCaseResult, EvalRunSummary
from marten_runtime.evals.report import write_eval_report


class EvalReportTests(unittest.TestCase):
    def _summary(self) -> EvalRunSummary:
        return EvalRunSummary(
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
            baseline_eval_run_id="eval_base",
            total_score=100.0,
            pass_rate=1.0,
            status="passed",
            artifact_root="reports/evals/eval_1",
        )

    def _case(self) -> EvalCaseResult:
        return EvalCaseResult(
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
            diagnostics_json={
                "provider_ref": "openai",
                "turns": [
                    {
                        "run": {
                            "run_id": "run_1234",
                            "status": "succeeded",
                            "latest_actual_usage": {"total_tokens": 321},
                            "attempted_profiles": ["openai_gpt_5_4"],
                            "attempted_providers": ["openai", "minimax"],
                            "provider_ref": "openai",
                            "final_provider_ref": "minimax",
                            "final_text": "你好",
                            "provider_calls": [
                                {
                                    "provider_name": "openai",
                                    "model_name": "gpt-5.4",
                                    "profile_name": "openai_gpt_5_4",
                                    "completed": False,
                                    "final_error_code": "PROVIDER_TIMEOUT",
                                    "error_kind": "transient",
                                    "attempts": [
                                        {"attempt": 1, "ok": False, "retryable": True},
                                        {"attempt": 2, "ok": False, "retryable": True},
                                    ],
                                },
                                {
                                    "provider_name": "minimax",
                                    "model_name": "minimax-text",
                                    "profile_name": "minimax_default",
                                    "completed": True,
                                    "final_error_code": None,
                                    "attempts": [{"attempt": 1, "ok": True, "retryable": False}],
                                },
                            ],
                        }
                    }
                ],
            },
            score_breakdown_json={"outcome": {"matched": True}},
            artifact_path="reports/evals/eval_1/cases/direct_answer_cn.json",
        )

    def test_write_eval_report_creates_json_and_markdown_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_root = Path(tmpdir)
            compare_result = {
                "baseline_eval_run_id": "eval_base",
                "baseline_source": "latest_passed",
                "total_score_delta": 0.0,
                "pass_rate_delta": 0.0,
                "token_total_delta": -500.0,
                "tool_calls_delta": -1.0,
                "llm_requests_delta": -1.0,
                "component_summary": [
                    {
                        "key": "capture",
                        "label": "记忆写入",
                        "current_score": 95.0,
                        "baseline_score": 90.0,
                        "delta": 5.0,
                        "case_count": 3,
                    }
                ],
                "regressions": [],
                "improvements": [],
                "cases": [
                    {
                        "case_id": "direct_answer_cn",
                        "current_status": "passed",
                        "baseline_status": "failed",
                        "current_total_score": 100.0,
                        "baseline_total_score": 60.0,
                        "total_score_delta": 40.0,
                        "change_kind": "improvement",
                        "components": [
                            {
                                "key": "outcome",
                                "label": "结果",
                                "current_score": 100.0,
                                "baseline_score": 60.0,
                                "delta": 40.0,
                                "current_passed": True,
                                "baseline_passed": False,
                            }
                        ],
                    }
                ],
            }
            stability_result = {
                "suite_id": "main_chain_core",
                "profile_name": "openai_gpt_5_4",
                "eval_mode": "live",
                "window_size": 5,
                "sample_size": 3,
                "history_eval_run_ids": ["eval_1", "eval_base", "eval_prev"],
                "total_score": {
                    "sample_size": 3,
                    "mean": 98.3333,
                    "min": 95.0,
                    "max": 100.0,
                    "range": 5.0,
                    "stddev": 2.357,
                },
                "pass_rate": {
                    "sample_size": 3,
                    "mean": 1.0,
                    "min": 1.0,
                    "max": 1.0,
                    "range": 0.0,
                    "stddev": 0.0,
                },
                "token_total": {
                    "sample_size": 3,
                    "mean": 812.0,
                    "min": 760.0,
                    "max": 900.0,
                    "range": 140.0,
                    "stddev": 58.0,
                },
                "failover_rate": 0.3333,
                "unstable_case_count": 1,
                "unstable_component_count": 1,
                "cases": [
                    {
                        "case_id": "direct_answer_cn",
                        "run_count": 3,
                        "status_values": ["passed"],
                        "pass_rate": 1.0,
                        "score": {
                            "sample_size": 3,
                            "mean": 96.6667,
                            "min": 90.0,
                            "max": 100.0,
                            "range": 10.0,
                            "stddev": 4.714,
                        },
                        "token_total": {
                            "sample_size": 3,
                            "mean": 405.0,
                            "min": 380.0,
                            "max": 430.0,
                            "range": 50.0,
                            "stddev": 20.412,
                        },
                        "failover_rate": 0.3333,
                        "anchor_signal_count": 4,
                        "anchor_strength": "strong",
                        "unstable": True,
                        "unstable_reasons": ["score_range"],
                        "components": [
                            {
                                "key": "outcome",
                                "label": "结果",
                                "score": {
                                    "sample_size": 3,
                                    "mean": 96.6667,
                                    "min": 90.0,
                                    "max": 100.0,
                                    "range": 10.0,
                                    "stddev": 4.714,
                                },
                                "unstable": True,
                            }
                        ],
                    }
                ],
                "components": [
                    {
                        "key": "outcome",
                        "label": "结果",
                        "score": {
                            "sample_size": 3,
                            "mean": 96.6667,
                            "min": 90.0,
                            "max": 100.0,
                            "range": 10.0,
                            "stddev": 4.714,
                        },
                        "unstable": True,
                    }
                ],
            }

            artifact_root = write_eval_report(
                self._summary(),
                [self._case()],
                report_root=report_root,
                compare_result=compare_result,
                stability_result=stability_result,
                blocked_reason="eval_blocked",
            )

            summary_json = artifact_root / "summary.json"
            summary_md = artifact_root / "summary.md"
            summary_html = artifact_root / "summary.html"
            index_html = report_root / "index.html"
            case_json = artifact_root / "cases" / "direct_answer_cn.json"
            self.assertTrue(summary_json.exists())
            self.assertTrue(summary_md.exists())
            self.assertTrue(summary_html.exists())
            self.assertTrue(index_html.exists())
            self.assertTrue(case_json.exists())
            body = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual(body["eval_run_id"], "eval_1")
            self.assertEqual(body["compare_result"]["baseline_source"], "latest_passed")
            self.assertEqual(body["stability_result"]["sample_size"], 3)
            self.assertEqual(body["token_total"], 321.0)
            self.assertEqual(body["token_cases"], 1)
            self.assertEqual(body["failover_rate"], 1.0)
            self.assertIn("provider_reliability", body)
            self.assertEqual(body["provider_reliability"]["retry_count"], 1)
            self.assertEqual(body["provider_reliability"]["fallback_count"], 1)
            self.assertEqual(body["provider_reliability"]["provider_error_count"], 1)
            self.assertEqual(body["provider_reliability"]["empty_output_count"], 0)
            self.assertEqual(body["provider_reliability"]["latest_final_provider_ref"], "minimax")
            markdown = summary_md.read_text(encoding="utf-8")
            self.assertLess(markdown.index("blocked_reason"), markdown.index("## Provider 评估"))
            self.assertIn("## Baseline Compare", markdown)
            self.assertIn("/evals/reports/eval_base", markdown)
            self.assertNotIn("../eval_base/summary.html", markdown)
            self.assertIn("## Stability", markdown)
            self.assertIn("## Provider 评估", markdown)
            self.assertIn("eval_blocked", markdown)
            self.assertIn("retry_count", markdown)
            self.assertIn("anchor_strength", markdown)
            self.assertIn("trace_1234", markdown)
            html = summary_html.read_text(encoding="utf-8")
            self.assertIn("<title>评测报告：eval_1</title>", html)
            self.assertIn("最近一次通过的同套件运行", html)
            self.assertIn("cases/direct_answer_cn.json", html)
            self.assertIn("用例详情", html)
            self.assertIn("trace_1234", html)
            self.assertIn("本次结果与基线", html)
            self.assertIn("运行元信息", html)
            self.assertIn("当前分数", html)
            self.assertIn("基线分数", html)
            self.assertIn("分数变化", html)
            self.assertIn("变化类型", html)
            self.assertIn("提升", html)
            self.assertIn("仅看变化", html)
            self.assertIn("组件汇总", html)
            self.assertIn("稳定性观察", html)
            self.assertIn("Provider 评估", html)
            self.assertIn("Provider 状态", html)
            self.assertIn("有错误", html)
            self.assertIn("重试", html)
            self.assertIn("回退", html)
            self.assertIn("空输出", html)
            self.assertIn("minimax", html)
            self.assertIn("波动用例", html)
            self.assertIn("锚点强度", html)
            self.assertIn("记忆写入", html)
            self.assertIn("结果", html)
            index = index_html.read_text(encoding="utf-8")
            self.assertIn("Eval 总览", index)
            self.assertIn("Gate Eval", index)
            self.assertIn("scripted 优先", index)
            self.assertIn("主链黄金链路", index)
            self.assertIn("查看详情", index)
            self.assertIn("/evals/reports/eval_1", index)
            self.assertNotIn("eval_1/summary.html", index)


    def test_write_eval_report_renders_challenge_delta_for_challenge_suites(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_root = Path(tmpdir)
            summary = self._summary().model_copy(update={"suite_id": "challenge_memory"})
            compare_result = {
                "baseline_eval_run_id": "eval_base",
                "baseline_source": "latest_passed",
                "total_score_delta": 5.0,
                "pass_rate_delta": 0.0,
                "token_total_delta": -500.0,
                "tool_calls_delta": -1.0,
                "llm_requests_delta": -1.0,
                "component_summary": [],
                "regressions": [],
                "improvements": [],
                "cases": [],
            }

            artifact_root = write_eval_report(
                summary,
                [self._case()],
                report_root=report_root,
                compare_result=compare_result,
            )

            markdown = (artifact_root / "summary.md").read_text(encoding="utf-8")
            html = (artifact_root / "summary.html").read_text(encoding="utf-8")
            self.assertIn("## Challenge Delta", markdown)
            self.assertIn("token_total_delta", markdown)
            self.assertIn("tool_calls_delta", markdown)
            self.assertIn("llm_requests_delta", markdown)
            self.assertIn("Challenge Delta", html)
            self.assertIn("-500.0", html)


    def test_write_eval_report_renders_challenge_failed_components_and_rubrics_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_root = Path(tmpdir)
            summary = self._summary().model_copy(
                update={
                    "eval_run_id": "eval_challenge_memory_1",
                    "suite_id": "challenge_memory",
                    "total_score": 68.75,
                    "pass_rate": 0.5,
                    "status": "failed",
                }
            )
            case = self._case().model_copy(
                update={
                    "eval_run_id": "eval_challenge_memory_1",
                    "case_id": "memory_scope_isolation_cn",
                    "family": "challenge",
                    "status": "failed",
                    "total_score": 50.0,
                    "score_breakdown_json": {
                        "case_meta": {"display_name": "记忆 scope 隔离", "description": "Load only visible memory"},
                        "components": [
                            {
                                "key": "task_success",
                                "label": "任务完成",
                                "score": 0.0,
                                "passed": False,
                                "details": {
                                    "rubric_items": [
                                        {"id": "hidden_scope_absent", "passed": False, "earned": 0.0, "points": 3.0}
                                    ]
                                },
                            },
                            {
                                "key": "tool_path_quality",
                                "label": "工具路径质量",
                                "score": 20.0,
                                "passed": True,
                                "details": {},
                            },
                        ]
                    },
                }
            )
            compare_result = {
                "baseline_eval_run_id": "eval_base",
                "baseline_source": "latest_passed",
                "total_score_delta": -10.0,
                "pass_rate_delta": -0.25,
                "token_total_delta": 200.0,
                "tool_calls_delta": 1.0,
                "llm_requests_delta": 2.0,
                "component_summary": [
                    {
                        "key": "task_success",
                        "label": "任务完成",
                        "current_score": 40.0,
                        "baseline_score": 60.0,
                        "delta": -20.0,
                        "case_count": 1,
                    }
                ],
                "regressions": [
                    {
                        "case_id": "memory_scope_isolation_cn",
                        "total_score_delta": -10.0,
                        "change_kind": "regression",
                    }
                ],
                "improvements": [],
                "cases": [
                    {
                        "case_id": "memory_scope_isolation_cn",
                        "current_status": "failed",
                        "baseline_status": "passed",
                        "current_total_score": 50.0,
                        "baseline_total_score": 60.0,
                        "total_score_delta": -10.0,
                        "change_kind": "regression",
                        "components": [
                            {
                                "key": "task_success",
                                "label": "任务完成",
                                "current_score": 0.0,
                                "baseline_score": 20.0,
                                "delta": -20.0,
                                "current_passed": False,
                                "baseline_passed": True,
                            }
                        ],
                    }
                ],
            }
            stability_result = {
                "sample_size": 2,
                "window_size": 5,
                "history_eval_run_ids": ["eval_challenge_memory_1", "eval_base"],
                "total_score": {"mean": 73.75, "range": 10.0, "stddev": 5.0},
                "pass_rate": {"mean": 0.75, "range": 0.5, "stddev": 0.25},
                "token_total": {"mean": 1000, "range": 100, "stddev": 50},
                "failover_rate": 0.0,
                "cases": [],
                "components": [],
            }

            artifact_root = write_eval_report(
                summary,
                [case],
                report_root=report_root,
                compare_result=compare_result,
                stability_result=stability_result,
            )

            html = (artifact_root / "summary.html").read_text(encoding="utf-8")
            focus_index = html.index("Challenge 重点视图")
            detail_index = html.index("用例详情")
            self.assertLess(focus_index, detail_index)
            self.assertIn("待提升组件", html)
            self.assertIn("memory_scope_isolation_cn", html)
            self.assertIn("task_success", html)
            self.assertIn("hidden_scope_absent", html)
            self.assertIn("历史报告", html)
            self.assertIn("/evals/reports/eval_base", html)
            self.assertIn("记忆 scope 隔离", html)
            self.assertIn("待提升", html)
            self.assertIn("Case 分数对比", html)
            self.assertIn("基线 ID", html)
            self.assertIn("eval_base", html)
            self.assertIn("组件分数对比", html)
            self.assertIn("score-chart", html)
            self.assertIn("score-card", html)
            self.assertIn("当前 50", html)
            self.assertIn("基线 60", html)
            self.assertNotIn("bar-pair", html)
            self.assertNotIn("Load only visible memory", html.split("评分原始 JSON")[0])

    def test_write_eval_report_rewrites_artifact_paths_to_actual_custom_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_root = Path(tmpdir) / "custom-reports"
            artifact_root = write_eval_report(
                self._summary(),
                [self._case()],
                report_root=report_root,
            )

            body = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))

            self.assertEqual(body["artifact_root"], str(artifact_root))
            self.assertEqual(
                body["case_results"][0]["artifact_path"],
                str(artifact_root / "cases" / "direct_answer_cn.json"),
            )
            self.assertEqual(body["token_total"], 321.0)
            self.assertEqual(body["token_cases"], 1)
            self.assertEqual(body["failover_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
