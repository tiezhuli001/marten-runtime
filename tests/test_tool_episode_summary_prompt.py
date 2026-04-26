import unittest

from marten_runtime.runtime.tool_episode_summary_prompt import (
    TOOL_EPISODE_SUMMARY_SYSTEM_PROMPT,
    TOOL_EPISODE_SUMMARY_BLOCK_MARKER,
    ToolEpisodeSummaryDraft,
    extract_tool_episode_summary_block,
    parse_tool_episode_summary_response,
    render_tool_episode_summary_input,
)
from marten_runtime.runtime.llm_client import ToolExchange


class ToolEpisodeSummaryPromptTests(unittest.TestCase):
    def test_render_tool_episode_summary_input_keeps_current_episode_only(self) -> None:
        text = render_tool_episode_summary_input(
            user_message="查看 easy-agent 仓库",
            tool_history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"server_id": "github", "tool_name": "get_file_contents"},
                    tool_result={"content": "X" * 2000},
                )
            ],
            final_reply="仓库存在，默认分支是 main。",
            max_tool_result_chars=120,
        )

        self.assertIn("查看 easy-agent 仓库", text)
        self.assertIn("get_file_contents", text)
        self.assertIn("默认分支是 main", text)
        self.assertLess(len(text), 1200)

    def test_parse_tool_episode_summary_response_validates_json_contract(self) -> None:
        parsed = parse_tool_episode_summary_response(
            """
            {
              "summary": "上一轮通过 github MCP 查询了 easy-agent，确认默认分支为 main。",
              "facts": [{"key": "repo", "value": "CloudWide851/easy-agent"}],
              "volatile": false,
              "keep_next_turn": true,
              "refresh_hint": ""
            }
            """
        )

        self.assertIsInstance(parsed, ToolEpisodeSummaryDraft)
        self.assertEqual(parsed.facts[0].key, "repo")

    def test_parse_tool_episode_summary_response_defaults_keep_next_turn_to_false(self) -> None:
        parsed = parse_tool_episode_summary_response(
            """
            {
              "summary": "上一轮通过 github MCP 查询了 easy-agent。",
              "facts": [{"key": "repo", "value": "CloudWide851/easy-agent"}],
              "volatile": false,
              "refresh_hint": ""
            }
            """
        )

        self.assertFalse(parsed.keep_next_turn)

    def test_prompt_requires_preserving_hidden_but_durable_tool_facts(self) -> None:
        self.assertIn("即使最终回复为了遵守用户要求而省略细节", TOOL_EPISODE_SUMMARY_SYSTEM_PROMPT)
        self.assertIn("keep_next_turn: 默认 false", TOOL_EPISODE_SUMMARY_SYSTEM_PROMPT)

    def test_extract_tool_episode_summary_block_splits_visible_text_and_summary(self) -> None:
        parsed = extract_tool_episode_summary_block(
            "仓库默认分支是 main。\n\n"
            f"```{TOOL_EPISODE_SUMMARY_BLOCK_MARKER}\n"
            '{"summary":"上一轮通过 github MCP 查询了 easy-agent。","facts":[{"key":"repo","value":"CloudWide851/easy-agent"}],"volatile":false,"keep_next_turn":true,"refresh_hint":""}\n'
            "```"
        )

        self.assertEqual(parsed.final_text, "仓库默认分支是 main。")
        self.assertIsNotNone(parsed.summary_draft)
        self.assertEqual(parsed.summary_draft.facts[0].key, "repo")

    def test_extract_tool_episode_summary_block_hides_invalid_trailing_protocol(self) -> None:
        parsed = extract_tool_episode_summary_block(
            "仓库默认分支是 main。\n\n"
            f"```{TOOL_EPISODE_SUMMARY_BLOCK_MARKER}\nnot-json\n```"
        )

        self.assertEqual(parsed.final_text, "仓库默认分支是 main。")
        self.assertIsNone(parsed.summary_draft)


if __name__ == "__main__":
    unittest.main()
