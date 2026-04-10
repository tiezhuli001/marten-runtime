import unittest

from marten_runtime.runtime.llm_client import ToolExchange
from marten_runtime.runtime.tool_outcome_flow import (
    collect_structured_hint_facts,
    infer_episode_source_kind,
    merge_tool_episode_facts,
    resolve_summary_volatile_flag,
)
from marten_runtime.session.tool_outcome_summary import ToolOutcomeFact, ToolOutcomeSummary
from marten_runtime.tools.registry import ToolSnapshot


class ToolOutcomeFlowTests(unittest.TestCase):
    def test_infer_episode_source_kind_returns_mixed_for_cross_source_history(self) -> None:
        source_kind = infer_episode_source_kind(
            [
                ToolExchange(tool_name="time", tool_result={"iso_time": "2026-04-09T00:00:00Z"}),
                ToolExchange(tool_name="mcp", tool_result={"server_id": "github"}),
            ],
            ToolSnapshot(tool_snapshot_id="tool_test", tool_metadata={"time": {"source_kind": "builtin"}}),
        )

        self.assertEqual(source_kind, "mixed")

    def test_collect_structured_hint_facts_reads_peak_usage_and_nested_json(self) -> None:
        facts = collect_structured_hint_facts(
            [
                ToolExchange(
                    tool_name="runtime",
                    tool_result={
                        "current_run": {
                            "initial_input_tokens_estimate": 100,
                            "peak_input_tokens_estimate": 220,
                            "peak_stage": "tool_followup",
                        },
                        "result_text": (
                            '{"items":[{"full_name":"CloudWide851/easy-agent","default_branch":"main",'
                            '"html_url":"https://github.com/CloudWide851/easy-agent"}]}'
                        ),
                    },
                )
            ]
        )

        self.assertEqual(
            [f"{item.key}={item.value}" for item in facts],
            [
                "peak_source=工具结果注入后",
                "peak_tokens=220",
                "full_name=CloudWide851/easy-agent",
            ],
        )

    def test_merge_tool_episode_facts_dedupes_and_preserves_order(self) -> None:
        merged = merge_tool_episode_facts(
            [
                ToolOutcomeFact.create("repo", "easy-agent"),
                ToolOutcomeFact.create("repo", "easy-agent"),
            ],
            [
                ToolOutcomeFact.create("branch", "main"),
                ToolOutcomeFact.create("url", "https://github.com/CloudWide851/easy-agent"),
            ],
        )

        self.assertEqual(
            [f"{item.key}={item.value}" for item in merged],
            [
                "repo=easy-agent",
                "branch=main",
                "url=https://github.com/CloudWide851/easy-agent",
            ],
        )

    def test_resolve_summary_volatile_flag_prefers_durable_facts_over_draft_flag(self) -> None:
        volatile = resolve_summary_volatile_flag(
            draft_volatile=True,
            facts=[ToolOutcomeFact.create("full_name", "CloudWide851/easy-agent")],
            fallback_summary=ToolOutcomeSummary.create(
                run_id="run_test",
                source_kind="mcp",
                summary_text="上一轮调用了 github MCP。",
                volatile=False,
            ),
        )

        self.assertFalse(volatile)


if __name__ == "__main__":
    unittest.main()
