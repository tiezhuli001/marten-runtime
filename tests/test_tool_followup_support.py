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

    def test_normalize_tool_result_for_followup_direct_renders_runtime_context_status_for_single_intent_query(self) -> None:
        tool_result, rendered = normalize_tool_result_for_followup(
            tool_name="runtime",
            tool_payload={"action": "context_status"},
            tool_result={
                "action": "context_status",
                "summary": "当前估算占用 100/184000 tokens（0%）。",
                "effective_window": 184000,
                "usage_percent": 0,
                "next_request_estimate": {
                    "input_tokens_estimate": 100,
                    "estimator_kind": "tokenizer",
                },
                "compaction_status": "none",
            },
            peak_input_tokens_estimate=120,
            peak_stage="tool_followup",
            actual_peak_input_tokens=130,
            actual_peak_output_tokens=7,
            actual_peak_total_tokens=137,
            actual_peak_stage="tool_followup",
            message="现在上下文用了多少，简短一点。",
        )

        self.assertIsInstance(tool_result, dict)
        assert isinstance(tool_result, dict)
        self.assertEqual(tool_result["current_run"]["peak_stage"], "tool_followup")
        self.assertIn("当前会话下一次请求预计带入 100 tokens", rendered or "")
        self.assertNotIn("show", rendered or "")
        self.assertNotIn("resume", rendered or "")

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

    def test_normalize_tool_result_for_followup_direct_renders_session_list_for_single_intent_query(self) -> None:
        tool_result, rendered = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={"action": "list"},
            tool_result={
                "action": "list",
                "count": 1,
                "items": [
                    {
                        "session_id": "sess_live",
                        "session_title": "实时调试",
                        "message_count": 3,
                    }
                ],
            },
            peak_input_tokens_estimate=120,
            peak_stage="initial_request",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="当前有哪些会话列表？",
        )

        self.assertEqual(tool_result["action"], "list")
        self.assertIn("当前有 1 个可见会话", rendered or "")
        self.assertNotIn("查看某个会话", rendered or "")
        self.assertNotIn("新开一个会话", rendered or "")

    def test_normalize_tool_result_for_followup_direct_renders_session_new_for_single_intent_query(self) -> None:
        tool_result, rendered = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={"action": "new"},
            tool_result={
                "action": "new",
                "session": {
                    "session_id": "sess_new_1",
                    "message_count": 0,
                    "state": "created",
                    "created_at": "2026-04-20T06:00:00+00:00",
                },
            },
            peak_input_tokens_estimate=120,
            peak_stage="initial_request",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="切换到新会话",
        )

        self.assertEqual(tool_result["action"], "new")
        self.assertIn("已切换到新会话", rendered or "")
        self.assertNotIn("查看某个会话", rendered or "")
        self.assertNotIn("新开一个会话", rendered or "")

    def test_normalize_tool_result_for_followup_direct_renders_session_resume_for_single_intent_query(self) -> None:
        tool_result, rendered = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={"action": "resume", "session_id": "sess_dcce8f9c"},
            tool_result={
                "action": "resume",
                "session": {
                    "session_id": "sess_dcce8f9c",
                    "session_title": "@_user_1 开启子代理查询github上…",
                    "session_preview": "@_user_1 开启子代理查询github上的[GitHub - tiezhuli001/codex-skills](https://github.com/tiezhuli001/codex-skills) 最近一次提交是什么时候。",
                    "message_count": 64,
                    "state": "running",
                    "created_at": "2026-04-19T15:30:41+00:00",
                },
            },
            peak_input_tokens_estimate=120,
            peak_stage="initial_request",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="切换到会话 sess_dcce8f9c",
        )

        self.assertEqual(tool_result["action"], "resume")
        self.assertIn("已切换到会话 `sess_dcce8f9c`", rendered or "")
        self.assertNotIn("查看某个会话", rendered or "")
        self.assertNotIn("新开一个会话", rendered or "")

    def test_normalize_tool_result_for_followup_direct_renders_session_show_for_single_intent_query(self) -> None:
        tool_result, rendered = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={"action": "show", "session_id": "sess_dcce8f9c"},
            tool_result={
                "action": "show",
                "session": {
                    "session_id": "sess_dcce8f9c",
                    "session_title": "排查 Feishu 输出",
                    "session_preview": "排查 session 卡片输出",
                    "message_count": 72,
                    "state": "running",
                    "created_at": "2026-04-19T15:30:41+00:00",
                },
            },
            peak_input_tokens_estimate=120,
            peak_stage="initial_request",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="查看会话 sess_dcce8f9c 详情",
        )

        self.assertEqual(tool_result["action"], "show")
        self.assertIn("会话详情 `sess_dcce8f9c`", rendered or "")
        self.assertNotIn("查看某个会话", rendered or "")
        self.assertNotIn("新开一个会话", rendered or "")

    def test_normalize_tool_result_for_followup_does_not_finalize_on_mcp_list_inside_multi_step_request(self) -> None:
        tool_result, rendered = normalize_tool_result_for_followup(
            tool_name="mcp",
            tool_payload={"action": "list"},
            tool_result={
                "action": "list",
                "servers": [{"server_id": "github", "tool_count": 38}],
            },
            peak_input_tokens_estimate=120,
            peak_stage="tool_followup",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="请严格按顺序先调用 time，再调用 runtime，最后调用 mcp 并总结。",
            tool_history_count=2,
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={},
                    tool_result={"timezone": "Asia/Shanghai", "iso_time": "2026-04-20T01:00:00+08:00"},
                ),
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "list"},
                    tool_result={"action": "list", "servers": [{"server_id": "github", "tool_count": 38}]},
                ),
            ],
        )

        self.assertEqual(tool_result["action"], "list")
        self.assertIsNone(rendered)


if __name__ == "__main__":
    unittest.main()
