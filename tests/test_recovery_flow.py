import unittest

from marten_runtime.runtime.llm_client import ToolExchange
from marten_runtime.runtime.recovery_flow import (
    is_generic_tool_failure_text,
    recover_successful_tool_followup_text,
    recover_tool_result_text,
)


class RecoveryFlowTests(unittest.TestCase):
    def test_is_generic_tool_failure_text_matches_known_failure_copy(self) -> None:
        self.assertTrue(is_generic_tool_failure_text("工具执行失败，请重试。"))
        self.assertTrue(is_generic_tool_failure_text("tool execution failed, please retry."))
        self.assertFalse(is_generic_tool_failure_text("这不是工具失败文案"))

    def test_recover_successful_tool_followup_text_renders_latest_successful_commit_result(self) -> None:
        text = recover_successful_tool_followup_text(
            [
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={
                        "server_id": "github",
                        "tool_name": "list_commits",
                        "arguments": {"owner": "CloudWide851", "repo": "easy-agent", "perPage": 1},
                    },
                    tool_result={
                        "server_id": "github",
                        "tool_name": "list_commits",
                        "ok": True,
                        "is_error": False,
                        "result_text": (
                            '[{"commit":{"message":"initial commit","author":{"date":"2026-04-01T02:24:49Z"}}}]'
                        ),
                    },
                )
            ]
        )

        self.assertIn("CloudWide851/easy-agent 最近一次提交是", text)
        self.assertIn("initial commit", text)

    def test_recover_successful_tool_followup_text_prefers_combined_three_step_sequence(self) -> None:
        text = recover_successful_tool_followup_text(
            [
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "Asia/Shanghai"},
                    tool_result={"timezone": "Asia/Shanghai", "iso_time": "2026-04-20T12:30:00+08:00"},
                ),
                ToolExchange(
                    tool_name="runtime",
                    tool_payload={"action": "context_status"},
                    tool_result={
                        "ok": True,
                        "action": "context_status",
                        "summary": "当前估算占用 1200/184000 tokens（1%）。",
                        "current_run": {
                            "initial_input_tokens_estimate": 1200,
                            "peak_input_tokens_estimate": 1200,
                            "peak_stage": "initial_request",
                            "actual_cumulative_input_tokens": 0,
                            "actual_cumulative_output_tokens": 0,
                            "actual_cumulative_total_tokens": 0,
                            "actual_peak_input_tokens": None,
                            "actual_peak_output_tokens": None,
                            "actual_peak_total_tokens": None,
                            "actual_peak_stage": None,
                        },
                        "next_request_estimate": {
                            "input_tokens_estimate": 1200,
                            "effective_window_tokens": 184000,
                            "context_window_tokens": 200000,
                            "estimator_kind": "rough",
                            "degraded": True,
                        },
                        "effective_window": 184000,
                        "context_window": 200000,
                        "estimated_usage": 1200,
                        "usage_percent": 1,
                        "compaction_status": "none",
                        "latest_checkpoint": "none",
                        "estimate_source": "rough",
                        "last_actual_usage": None,
                        "last_completed_run": None,
                        "model_profile": "minimax_m25",
                    },
                ),
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "list"},
                    tool_result={
                        "action": "list",
                        "servers": [{"server_id": "github", "tool_count": 38, "state": "ready"}],
                    },
                ),
            ]
        )

        self.assertIn("当前上下文使用详情", text)
        self.assertIn("当前可用 MCP 服务共 1 个", text)

    def test_recover_tool_result_text_returns_empty_for_missing_history(self) -> None:
        self.assertEqual(recover_tool_result_text([]), "")


if __name__ == "__main__":
    unittest.main()
