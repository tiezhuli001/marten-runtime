import unittest

from marten_runtime.runtime.tool_outcome_extractor import extract_tool_outcome_summary


class ToolOutcomeExtractorTests(unittest.TestCase):
    def test_extract_runtime_context_status_returns_none_to_avoid_cross_turn_pollution(self) -> None:
        summary = extract_tool_outcome_summary(
            run_id="run_runtime",
            tool_name="runtime",
            tool_payload={"action": "context_status"},
            tool_result={
                "action": "context_status",
                "estimated_usage": 2694,
                "effective_window": 245760,
                "current_run": {
                    "initial_input_tokens_estimate": 2507,
                    "peak_input_tokens_estimate": 2568,
                    "peak_stage": "tool_followup",
                    "actual_peak_total_tokens": 14066,
                    "actual_peak_stage": "llm_second",
                },
            },
            tool_metadata={"source_kind": "builtin"},
        )

        self.assertIsNone(summary)

    def test_extract_skill_fallback_summary_does_not_persist_skill_body(self) -> None:
        summary = extract_tool_outcome_summary(
            run_id="run_skill",
            tool_name="skill",
            tool_payload={"action": "load", "skill_id": "repo_helper"},
            tool_result={
                "action": "load",
                "skill_id": "repo_helper",
                "name": "Repo Helper",
                "body": "Read repository files before proposing edits." * 50,
            },
            tool_metadata={"source_kind": "skill"},
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertIn("repo_helper", summary.summary_text)
        self.assertNotIn("Read repository files", summary.summary_text)
        self.assertTrue(summary.keep_next_turn)

    def test_extract_time_fallback_summary_marks_volatile(self) -> None:
        summary = extract_tool_outcome_summary(
            run_id="run_time",
            tool_name="time",
            tool_payload={"timezone": "UTC"},
            tool_result={"iso_time": "2026-04-07T12:00:00Z"},
            tool_metadata={"source_kind": "builtin"},
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertTrue(summary.volatile)
        self.assertFalse(summary.keep_next_turn)

    def test_extract_mcp_summary_can_read_nested_result_text_json(self) -> None:
        summary = extract_tool_outcome_summary(
            run_id="run_mcp_nested",
            tool_name="mcp",
            tool_payload={"action": "call", "server_id": "github", "tool_name": "search_repositories"},
            tool_result={
                "result_text": '{"items":[{"full_name":"CloudWide851/easy-agent","default_branch":"main","html_url":"https://github.com/CloudWide851/easy-agent"}]}'
            },
            tool_metadata={"source_kind": "mcp", "server_id": "github"},
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(
            [f"{item.key}={item.value}" for item in summary.facts],
            [
                "full_name=CloudWide851/easy-agent",
                "default_branch=main",
                "url=https://github.com/CloudWide851/easy-agent",
            ],
        )
        self.assertFalse(summary.keep_next_turn)

    def test_extract_generic_tool_summary_returns_none_when_noisy_or_unstructured(self) -> None:
        summary = extract_tool_outcome_summary(
            run_id="run_generic",
            tool_name="big_tool",
            tool_payload={"query": "x"},
            tool_result={"blob": "X" * 8000},
            tool_metadata={"source_kind": "builtin"},
        )

        self.assertIsNone(summary)


if __name__ == "__main__":
    unittest.main()
