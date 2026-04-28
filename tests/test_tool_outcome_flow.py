import unittest

from marten_runtime.runtime.llm_client import ToolExchange
from marten_runtime.runtime.tool_episode_summary_prompt import ToolEpisodeSummaryDraft
from marten_runtime.runtime.tool_outcome_flow import (
    build_combined_tool_episode_summary,
    build_fallback_tool_episode_summary,
    collect_structured_hint_facts,
    extract_rule_based_tool_outcome_summary,
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

    def test_extract_rule_based_tool_outcome_summary_uses_latest_tool_history_item(self) -> None:
        summary = extract_rule_based_tool_outcome_summary(
            run_id="run_test",
            history=[
                ToolExchange(tool_name="time", tool_result={"iso_time": "2026-04-09T00:00:00Z"}),
                ToolExchange(
                    tool_name="skill",
                    tool_payload={"skill_id": "test_time_skill"},
                    tool_result={"skill_id": "test_time_skill"},
                ),
            ],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_test", tool_metadata={}),
        )

        self.assertIsNotNone(summary)
        self.assertEqual(summary.tool_name, "skill")
        self.assertEqual(summary.summary_text, "上一轮加载了 skill test_time_skill。")

    def test_build_fallback_tool_episode_summary_returns_generic_final_text_when_no_rule_summary(self) -> None:
        summary = build_fallback_tool_episode_summary(
            run_id="run_test",
            history=[ToolExchange(tool_name="mock_search", tool_result={"issue_count": 12})],
            final_text="已完成查询",
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_test", tool_metadata={}),
        )

        self.assertIsNotNone(summary)
        self.assertEqual(summary.summary_text, "上一轮工具调用完成：已完成查询")
        self.assertEqual(summary.source_kind, "builtin")
        self.assertFalse(summary.keep_next_turn)

    def test_build_combined_tool_episode_summary_merges_draft_and_fallback_semantics(self) -> None:
        summary = build_combined_tool_episode_summary(
            run_id="run_test",
            history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_result={
                        "result_text": '{"items":[{"full_name":"CloudWide851/easy-agent","default_branch":"main"}]}'
                    },
                )
            ],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_test", tool_metadata={}),
            draft=ToolEpisodeSummaryDraft(
                summary="已完成检查该仓库。",
                facts=[],
                volatile=True,
                keep_next_turn=True,
                refresh_hint="",
            ),
            fallback_summary=ToolOutcomeSummary.create(
                run_id="run_test",
                source_kind="mcp",
                summary_text="上一轮调用了 github MCP。",
                facts=[ToolOutcomeFact.create("url", "https://github.com/CloudWide851/easy-agent")],
                volatile=False,
                keep_next_turn=True,
                refresh_hint="fallback-hint",
            ),
        )

        self.assertEqual(summary.summary_text, "已完成检查该仓库。")
        self.assertFalse(summary.volatile)
        self.assertTrue(summary.keep_next_turn)
        self.assertEqual(summary.refresh_hint, "fallback-hint")
        self.assertEqual(
            [f"{item.key}={item.value}" for item in summary.facts],
            [
                "full_name=CloudWide851/easy-agent",
                "default_branch=main",
                "url=https://github.com/CloudWide851/easy-agent",
            ],
        )

    def test_build_combined_tool_episode_summary_restores_keep_next_turn_from_durable_facts(self) -> None:
        fallback = build_fallback_tool_episode_summary(
            run_id="run_test",
            history=[
                ToolExchange(
                    tool_name="mock_search",
                    tool_result={
                        "full_name": "CloudWide851/easy-agent",
                        "default_branch": "main",
                    },
                )
            ],
            final_text="已完成检查",
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_test", tool_metadata={}),
        )

        summary = build_combined_tool_episode_summary(
            run_id="run_test",
            history=[
                ToolExchange(
                    tool_name="mock_search",
                    tool_result={
                        "full_name": "CloudWide851/easy-agent",
                        "default_branch": "main",
                    },
                )
            ],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_test", tool_metadata={}),
            draft=ToolEpisodeSummaryDraft(
                summary="已完成检查该仓库。",
                facts=[],
                volatile=False,
                keep_next_turn=False,
                refresh_hint="",
            ),
            fallback_summary=fallback,
        )

        self.assertFalse(fallback.keep_next_turn)
        self.assertTrue(summary.keep_next_turn)


if __name__ == "__main__":
    unittest.main()
