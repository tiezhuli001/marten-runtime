import unittest

from marten_runtime.session.tool_outcome_summary import (
    ToolOutcomeFact,
    ToolOutcomeSummary,
    render_tool_outcome_summary_block,
)


class ToolOutcomeSummaryTests(unittest.TestCase):
    def test_tool_outcome_summary_trims_fact_count_and_summary_length(self) -> None:
        summary = ToolOutcomeSummary.create(
            run_id="run_1",
            source_kind="mcp",
            summary_text="结果 " * 120,
            facts=[
                ToolOutcomeFact.create("repo", "openai/codex"),
                ToolOutcomeFact.create("branch", "main"),
                ToolOutcomeFact.create("issue_count", 12),
                ToolOutcomeFact.create("ignored", "x"),
            ],
        )

        self.assertLessEqual(len(summary.summary_text), 220)
        self.assertEqual(len(summary.facts), 3)
        self.assertTrue(summary.truncated)
        self.assertFalse(summary.volatile)
        self.assertTrue(summary.keep_next_turn)

    def test_tool_outcome_summary_can_mark_volatile_and_skip_next_turn(self) -> None:
        summary = ToolOutcomeSummary.create(
            run_id="run_time",
            source_kind="builtin",
            summary_text="上一轮调用了 time 工具获取当前时间。",
            volatile=True,
            keep_next_turn=False,
            refresh_hint="若再次询问当前时间，应重新调用工具。",
        )

        self.assertTrue(summary.volatile)
        self.assertFalse(summary.keep_next_turn)
        self.assertEqual(summary.refresh_hint, "若再次询问当前时间，应重新调用工具。")

    def test_render_tool_outcome_summary_block_skips_volatile_or_not_kept_items(self) -> None:
        block = render_tool_outcome_summary_block(
            [
                ToolOutcomeSummary.create(
                    run_id="run_keep",
                    source_kind="mcp",
                    summary_text="上一轮通过 github MCP 查询了 repo=openai/codex。",
                    facts=[
                        ToolOutcomeFact.create("default_branch", "main"),
                        ToolOutcomeFact.create("name", "codex"),
                    ],
                    keep_next_turn=True,
                ),
                ToolOutcomeSummary.create(
                    run_id="run_time",
                    source_kind="builtin",
                    summary_text="上一轮调用了 time 工具获取当前时间。",
                    volatile=True,
                    keep_next_turn=False,
                ),
            ]
        )

        self.assertIsNotNone(block)
        assert block is not None
        self.assertIn("只有当前消息明确承接上一轮结果时才参考", block)
        self.assertIn("openai/codex", block)
        self.assertIn("default_branch=main", block)
        self.assertNotIn("time 工具", block)

    def test_render_tool_outcome_summary_block_respects_budget(self) -> None:
        summaries = [
            ToolOutcomeSummary.create(
                run_id=f"run_{idx}",
                source_kind="builtin",
                summary_text="结果 " * 40,
                keep_next_turn=True,
            )
            for idx in range(4)
        ]

        block = render_tool_outcome_summary_block(summaries, max_items=2, max_chars=140)

        self.assertIsNotNone(block)
        assert block is not None
        self.assertIn("工具结果摘要", block)
        self.assertLessEqual(len(block), 140)


if __name__ == "__main__":
    unittest.main()
