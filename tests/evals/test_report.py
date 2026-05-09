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
                            "latest_actual_usage": {"total_tokens": 321},
                            "attempted_profiles": ["openai_gpt_5_4"],
                            "provider_ref": "openai",
                            "final_provider_ref": "openai",
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
            )

            summary_json = artifact_root / "summary.json"
            summary_md = artifact_root / "summary.md"
            summary_html = artifact_root / "summary.html"
            case_json = artifact_root / "cases" / "direct_answer_cn.json"
            self.assertTrue(summary_json.exists())
            self.assertTrue(summary_md.exists())
            self.assertTrue(summary_html.exists())
            self.assertTrue(case_json.exists())
            body = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual(body["eval_run_id"], "eval_1")
            self.assertEqual(body["compare_result"]["baseline_source"], "latest_passed")
            self.assertEqual(body["stability_result"]["sample_size"], 3)
            self.assertEqual(body["token_total"], 321.0)
            self.assertEqual(body["token_cases"], 1)
            self.assertEqual(body["failover_rate"], 0.0)
            markdown = summary_md.read_text(encoding="utf-8")
            self.assertIn("## Baseline Compare", markdown)
            self.assertIn("## Stability", markdown)
            self.assertIn("anchor_strength", markdown)
            self.assertIn("trace_1234", markdown)
            html = summary_html.read_text(encoding="utf-8")
            self.assertIn("<title>评测报告：eval_1</title>", html)
            self.assertIn("latest_passed", html)
            self.assertIn("cases/direct_answer_cn.json", html)
            self.assertIn("用例详情", html)
            self.assertIn("trace_1234", html)
            self.assertIn("基线对比", html)
            self.assertIn("当前分数", html)
            self.assertIn("基线分数", html)
            self.assertIn("分数变化", html)
            self.assertIn("变化类型", html)
            self.assertIn("improvement", html)
            self.assertIn("仅看变化", html)
            self.assertIn("组件汇总", html)
            self.assertIn("稳定性观察", html)
            self.assertIn("波动用例", html)
            self.assertIn("锚点强度", html)
            self.assertIn("记忆写入", html)
            self.assertIn("结果", html)

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
            self.assertEqual(body["failover_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
