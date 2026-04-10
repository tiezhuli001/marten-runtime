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

    def test_recover_tool_result_text_returns_empty_for_missing_history(self) -> None:
        self.assertEqual(recover_tool_result_text([]), "")


if __name__ == "__main__":
    unittest.main()
