import unittest

from marten_runtime.runtime.llm_client import LLMRequest, ToolExchange
from marten_runtime.runtime.tool_followup_support import (
    append_tool_exchange,
    build_tool_followup_request,
    normalize_tool_result_for_followup,
)


class ToolFollowupSupportTests(unittest.TestCase):
    def test_append_tool_exchange_keeps_payload_and_dict_result(self) -> None:
        history: list[ToolExchange] = []

        append_tool_exchange(
            history,
            tool_name="time",
            tool_payload={"timezone": "UTC"},
            tool_result={"iso_time": "2026-04-11T00:00:00Z"},
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].tool_name, "time")
        self.assertEqual(history[0].tool_payload, {"timezone": "UTC"})
        self.assertEqual(history[0].tool_result["iso_time"], "2026-04-11T00:00:00Z")

    def test_normalize_tool_result_for_followup_renders_runtime_context_status(self) -> None:
        tool_result, rendered = normalize_tool_result_for_followup(
            tool_name="runtime",
            tool_payload={"action": "context_status"},
            tool_result={"action": "context_status", "summary": "当前估算占用 100/184000 tokens（0%）。"},
            peak_input_tokens_estimate=120,
            peak_stage="tool_followup",
            actual_peak_input_tokens=130,
            actual_peak_output_tokens=7,
            actual_peak_total_tokens=137,
            actual_peak_stage="tool_followup",
        )

        self.assertIsInstance(tool_result, dict)
        assert isinstance(tool_result, dict)
        self.assertEqual(tool_result["current_run"]["peak_stage"], "tool_followup")
        self.assertIn("当前上下文使用详情", rendered or "")

    def test_build_tool_followup_request_copies_followup_fields(self) -> None:
        base_request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="继续",
            agent_id="main",
            app_id="main_agent",
        )
        history = [
            ToolExchange(
                tool_name="mcp",
                tool_payload={"action": "call"},
                tool_result={"ok": True},
            )
        ]

        updated = build_tool_followup_request(
            base_request,
            tool_history=history,
            tool_result={"ok": True},
            requested_tool_name="mcp",
            requested_tool_payload={"action": "call"},
        )

        self.assertEqual(updated.requested_tool_name, "mcp")
        self.assertEqual(updated.requested_tool_payload, {"action": "call"})
        self.assertEqual(len(updated.tool_history), 1)
        self.assertEqual(updated.tool_result, {"ok": True})
        self.assertEqual(base_request.tool_history, [])


if __name__ == "__main__":
    unittest.main()
