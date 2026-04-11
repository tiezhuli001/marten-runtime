import unittest

from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import ToolExchange
from marten_runtime.runtime.run_outcome_flow import (
    append_post_turn_summary,
    tool_rejection_text,
)
from marten_runtime.tools.registry import ToolSnapshot


class RunOutcomeFlowTests(unittest.TestCase):
    def test_tool_rejection_text_maps_known_and_fallback_codes(self) -> None:
        self.assertEqual(
            tool_rejection_text("TOOL_NOT_ALLOWED"),
            "当前操作未被允许，请换个说法或缩小范围。",
        )
        self.assertEqual(
            tool_rejection_text("TOOL_NOT_FOUND"),
            "当前所需工具不可用，请稍后重试。",
        )
        self.assertEqual(tool_rejection_text("CUSTOM_ERROR"), "custom_error")

    def test_append_post_turn_summary_skips_runtime_context_status(self) -> None:
        history = InMemoryRunHistory()
        run = history.start(
            session_id="sess_skip_runtime",
            trace_id="trace_skip_runtime",
            config_snapshot_id="cfg",
            bootstrap_manifest_id="boot",
            context_snapshot_id="ctx",
            skill_snapshot_id="skill",
            tool_snapshot_id="tool",
        )

        append_post_turn_summary(
            history=history,
            user_message="当前上下文窗口多大？",
            tool_history=[
                ToolExchange(
                    tool_name="runtime",
                    tool_payload={"action": "context_status"},
                    tool_result={"action": "context_status"},
                )
            ],
            final_text="当前上下文使用详情",
            combined_summary_draft=None,
            run_id=run.run_id,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool"),
        )

        self.assertEqual(history.get(run.run_id).tool_outcome_summaries, [])

    def test_append_post_turn_summary_appends_fallback_summary_for_normal_tool(self) -> None:
        history = InMemoryRunHistory()
        run = history.start(
            session_id="sess_append_summary",
            trace_id="trace_append_summary",
            config_snapshot_id="cfg",
            bootstrap_manifest_id="boot",
            context_snapshot_id="ctx",
            skill_snapshot_id="skill",
            tool_snapshot_id="tool",
        )

        append_post_turn_summary(
            history=history,
            user_message="现在几点",
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "UTC"},
                    tool_result={"iso_time": "2026-04-11T00:00:00Z"},
                )
            ],
            final_text="现在是 UTC 时间",
            combined_summary_draft=None,
            run_id=run.run_id,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool"),
        )

        summaries = history.get(run.run_id).tool_outcome_summaries
        self.assertEqual(len(summaries), 1)
        self.assertTrue(summaries[0].summary_text)


if __name__ == "__main__":
    unittest.main()
