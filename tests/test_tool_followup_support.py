import unittest

from marten_runtime.runtime.llm_client import (
    FinalizationEvidenceLedger,
    LLMRequest,
    ToolExchange,
    ToolFollowupRender,
)
from marten_runtime.runtime.tool_followup_support import (
    append_tool_exchange,
    build_finalization_evidence_ledger,
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
        tool_result, followup = normalize_tool_result_for_followup(
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
        self.assertIsInstance(followup, ToolFollowupRender)
        self.assertEqual(tool_result["current_run"]["peak_stage"], "tool_followup")
        self.assertIn("当前会话下一次请求预计带入 100 tokens", followup.terminal_text or "")
        self.assertNotIn("show", followup.terminal_text or "")
        self.assertNotIn("resume", followup.terminal_text or "")
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn("当前会话下一次请求预计带入 100 tokens", followup.recovery_fragment.text)

    def test_normalize_tool_result_for_followup_does_not_direct_render_runtime_after_prior_tool_round_trip(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
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
            message="先看当前时间，再检查上下文占用。",
            tool_history_count=2,
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "Asia/Shanghai"},
                    tool_result={
                        "timezone": "Asia/Shanghai",
                        "iso_time": "2026-04-20T01:00:00+08:00",
                    },
                ),
                ToolExchange(
                    tool_name="runtime",
                    tool_payload={"action": "context_status"},
                    tool_result={
                        "action": "context_status",
                        "summary": "当前估算占用 100/184000 tokens（0%）。",
                    },
                ),
            ],
        )

        self.assertIsInstance(tool_result, dict)
        self.assertIsInstance(followup, ToolFollowupRender)
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn("当前会话下一次请求预计带入 100 tokens", followup.recovery_fragment.text)

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

    def test_normalize_tool_result_for_followup_direct_renders_session_list_when_llm_finalizes(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={"action": "list", "finalize_response": True},
            tool_result={
                "action": "list",
                "count": 1,
                "current_session": {
                    "session_id": "sess_live",
                    "session_title": "实时调试",
                    "message_count": 3,
                    "state": "running",
                },
                "items": [
                    {
                        "session_id": "sess_live",
                        "session_title": "实时调试",
                        "message_count": 3,
                        "state": "running",
                        "is_current": True,
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
        self.assertIn("当前有 1 个可见会话", followup.terminal_text or "")
        self.assertIn("当前会话：实时调试（running，3 条，session_id：sess_live）", followup.terminal_text or "")
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn("当前有 1 个可见会话", followup.recovery_fragment.text)

    def test_normalize_tool_result_for_followup_keeps_session_list_for_followup_llm(self) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={"action": "list"},
            tool_result={
                "action": "list",
                "count": 1,
                "current_session": {
                    "session_id": "sess_live",
                    "session_title": "实时调试",
                    "message_count": 3,
                    "state": "running",
                },
                "items": [
                    {
                        "session_id": "sess_live",
                        "session_title": "实时调试",
                        "message_count": 3,
                        "state": "running",
                        "is_current": True,
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
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn("当前有 1 个可见会话", followup.recovery_fragment.text)
        self.assertIn("当前会话：实时调试（running，3 条，session_id：sess_live）", followup.recovery_fragment.text)

    def test_normalize_tool_result_for_followup_does_not_direct_render_session_list_for_github_background_request(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={"action": "list"},
            tool_result={
                "action": "list",
                "count": 1,
                "current_session": {
                    "session_id": "sess_live",
                    "session_title": "实时调试",
                    "message_count": 3,
                    "state": "running",
                },
                "items": [
                    {
                        "session_id": "sess_live",
                        "session_title": "实时调试",
                        "message_count": 3,
                        "state": "running",
                        "is_current": True,
                    }
                ],
            },
            peak_input_tokens_estimate=120,
            peak_stage="initial_request",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="开启子代理查询 github 上 tiezhuli001/codex-skills 最近一次提交是什么时候",
        )

        self.assertEqual(tool_result["action"], "list")
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn("当前有 1 个可见会话", followup.recovery_fragment.text)

    def test_normalize_tool_result_for_followup_direct_renders_session_new_for_single_intent_query(self) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={"action": "new", "finalize_response": True},
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
        self.assertIn("已切换到新会话", followup.terminal_text or "")
        self.assertNotIn("查看某个会话", followup.terminal_text or "")
        self.assertNotIn("新开一个会话", followup.terminal_text or "")

    def test_normalize_tool_result_for_followup_direct_renders_session_resume_for_single_intent_query(self) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={"action": "resume", "session_id": "sess_dcce8f9c", "finalize_response": True},
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
        self.assertIn("已切换到会话 `sess_dcce8f9c`", followup.terminal_text or "")
        self.assertNotIn("查看某个会话", followup.terminal_text or "")
        self.assertNotIn("新开一个会话", followup.terminal_text or "")

    def test_normalize_tool_result_for_followup_does_not_direct_render_session_resume_inside_multi_step_request(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={"action": "resume", "session_id": "sess_dcce8f9c"},
            tool_result={
                "action": "resume",
                "transition": {
                    "mode": "switched",
                    "binding_changed": True,
                    "target_session_id": "sess_dcce8f9c",
                },
                "session": {
                    "session_id": "sess_dcce8f9c",
                    "session_title": "排查 Feishu 输出",
                    "message_count": 72,
                    "state": "running",
                },
            },
            peak_input_tokens_estimate=120,
            peak_stage="initial_request",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="先切换到会话 sess_dcce8f9c，再告诉我当前时间。",
        )

        self.assertEqual(tool_result["action"], "resume")
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn("已切换到会话 `sess_dcce8f9c`", followup.recovery_fragment.text)

    def test_normalize_tool_result_for_followup_does_not_direct_render_session_resume_for_after_clause_request(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={"action": "resume", "session_id": "sess_dcce8f9c"},
            tool_result={
                "action": "resume",
                "transition": {
                    "mode": "switched",
                    "binding_changed": True,
                    "target_session_id": "sess_dcce8f9c",
                },
                "session": {
                    "session_id": "sess_dcce8f9c",
                    "session_title": "排查 Feishu 输出",
                    "message_count": 72,
                    "state": "running",
                },
            },
            peak_input_tokens_estimate=120,
            peak_stage="initial_request",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="切换到 sess_dcce8f9c 后告诉我当前时间。",
        )

        self.assertEqual(tool_result["action"], "resume")
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)

    def test_normalize_tool_result_for_followup_direct_renders_same_session_resume_as_noop(self) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={
                "action": "resume",
                "session_id": "sess_dcce8f9c",
                "finalize_response": True,
            },
            tool_result={
                "action": "resume",
                "transition": {
                    "mode": "noop_same_session",
                    "binding_changed": False,
                },
                "session": {
                    "session_id": "sess_dcce8f9c",
                    "session_title": "排查 Feishu 输出",
                    "session_preview": "切换到问题会话继续排查",
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
            message="切换到会话 sess_dcce8f9c",
        )

        self.assertEqual(tool_result["action"], "resume")
        self.assertIn("当前已在会话 `sess_dcce8f9c`", followup.terminal_text or "")
        self.assertNotIn("已切换到会话 `sess_dcce8f9c`", followup.terminal_text or "")

    def test_normalize_tool_result_for_followup_direct_renders_session_show_for_single_intent_query(self) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="session",
            tool_payload={
                "action": "show",
                "session_id": "sess_dcce8f9c",
                "finalize_response": True,
            },
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
        self.assertIn("会话详情 `sess_dcce8f9c`", followup.terminal_text or "")
        self.assertNotIn("查看某个会话", followup.terminal_text or "")
        self.assertNotIn("新开一个会话", followup.terminal_text or "")

    def test_normalize_tool_result_for_followup_direct_renders_spawn_subagent_acceptance(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="spawn_subagent",
            tool_payload={
                "task": "查询最近一次提交时间",
                "label": "github-last-commit",
                "tool_profile": "standard",
                "notify_on_finish": True,
                "finalize_response": True,
            },
            tool_result={
                "ok": True,
                "status": "accepted",
                "task_id": "task_spawn_ack",
                "child_session_id": "sess_child_ack",
                "effective_tool_profile": "standard",
                "queue_state": "running",
            },
            peak_input_tokens_estimate=120,
            peak_stage="initial_request",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="开启子代理查询最近一次提交时间",
        )

        self.assertEqual(tool_result["status"], "accepted")
        self.assertEqual(
            followup.terminal_text,
            "已受理，子 agent 正在后台执行，完成后会通知你结果。",
        )

    def test_normalize_tool_result_for_followup_does_not_direct_render_spawn_subagent_inside_multi_step_request(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="spawn_subagent",
            tool_payload={
                "task": "查询最近一次提交时间",
                "label": "github-last-commit",
                "tool_profile": "standard",
                "notify_on_finish": True,
            },
            tool_result={
                "ok": True,
                "status": "accepted",
                "task_id": "task_spawn_ack",
                "child_session_id": "sess_child_ack",
                "effective_tool_profile": "standard",
                "queue_state": "running",
            },
            peak_input_tokens_estimate=120,
            peak_stage="tool_followup",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="开子代理查 GitHub，再告诉我当前时间。",
            tool_history_count=1,
            tool_history=[
                ToolExchange(
                    tool_name="spawn_subagent",
                    tool_payload={
                        "task": "查询最近一次提交时间",
                        "label": "github-last-commit",
                        "tool_profile": "standard",
                        "notify_on_finish": True,
                    },
                    tool_result={
                        "ok": True,
                        "status": "accepted",
                        "task_id": "task_spawn_ack",
                        "child_session_id": "sess_child_ack",
                        "effective_tool_profile": "standard",
                        "queue_state": "running",
                    },
                )
            ],
        )

        self.assertEqual(tool_result["status"], "accepted")
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn("已受理", followup.recovery_fragment.text)

    def test_normalize_tool_result_for_followup_does_not_direct_render_spawn_subagent_for_and_clause_request(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="spawn_subagent",
            tool_payload={
                "task": "查询最近一次提交时间",
                "label": "github-last-commit",
                "tool_profile": "standard",
                "notify_on_finish": True,
            },
            tool_result={
                "ok": True,
                "status": "accepted",
                "task_id": "task_spawn_ack",
                "child_session_id": "sess_child_ack",
                "effective_tool_profile": "standard",
                "queue_state": "running",
            },
            peak_input_tokens_estimate=120,
            peak_stage="tool_followup",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="开子代理并告诉我时间。",
            tool_history_count=1,
            tool_history=[
                ToolExchange(
                    tool_name="spawn_subagent",
                    tool_payload={
                        "task": "查询最近一次提交时间",
                        "label": "github-last-commit",
                        "tool_profile": "standard",
                        "notify_on_finish": True,
                    },
                    tool_result={
                        "ok": True,
                        "status": "accepted",
                        "task_id": "task_spawn_ack",
                        "child_session_id": "sess_child_ack",
                        "effective_tool_profile": "standard",
                        "queue_state": "running",
                    },
                )
            ],
        )

        self.assertEqual(tool_result["status"], "accepted")
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)

    def test_normalize_tool_result_for_followup_does_not_finalize_on_mcp_list_inside_multi_step_request(self) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
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
        self.assertIsNone(followup.terminal_text)

    def test_normalize_tool_result_for_followup_builds_time_fragment_for_multi_step_chain(self) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="time",
            tool_payload={"timezone": "Asia/Shanghai"},
            tool_result={
                "timezone": "Asia/Shanghai",
                "iso_time": "2026-04-20T01:00:00+08:00",
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
                    tool_payload={"timezone": "Asia/Shanghai"},
                    tool_result={
                        "timezone": "Asia/Shanghai",
                        "iso_time": "2026-04-20T01:00:00+08:00",
                    },
                )
            ],
        )

        self.assertEqual(tool_result["iso_time"], "2026-04-20T01:00:00+08:00")
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn("现在是北京时间", followup.recovery_fragment.text)

    def test_normalize_tool_result_for_followup_direct_renders_time_when_llm_finalizes(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="time",
            tool_payload={"timezone": "Asia/Shanghai", "finalize_response": True},
            tool_result={
                "timezone": "Asia/Shanghai",
                "iso_time": "2026-04-20T01:00:00+08:00",
            },
            peak_input_tokens_estimate=120,
            peak_stage="tool_followup",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="告诉我当前北京时间。",
            tool_history_count=1,
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "Asia/Shanghai", "finalize_response": True},
                    tool_result={
                        "timezone": "Asia/Shanghai",
                        "iso_time": "2026-04-20T01:00:00+08:00",
                    },
                )
            ],
        )

        self.assertEqual(tool_result["iso_time"], "2026-04-20T01:00:00+08:00")
        self.assertIn("现在是北京时间", followup.terminal_text or "")
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn("现在是北京时间", followup.recovery_fragment.text)

    def test_normalize_tool_result_for_followup_builds_mcp_list_fragment_for_multi_step_chain(self) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="mcp",
            tool_payload={"action": "list"},
            tool_result={
                "action": "list",
                "servers": [{"server_id": "github", "tool_count": 38, "state": "ready"}],
            },
            peak_input_tokens_estimate=120,
            peak_stage="tool_followup",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="请严格按顺序先调用 time，再调用 runtime，最后调用 mcp 并总结。",
            tool_history_count=3,
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "Asia/Shanghai"},
                    tool_result={
                        "timezone": "Asia/Shanghai",
                        "iso_time": "2026-04-20T01:00:00+08:00",
                    },
                ),
                ToolExchange(
                    tool_name="runtime",
                    tool_payload={"action": "context_status"},
                    tool_result={"action": "context_status", "summary": "当前估算占用 100/184000 tokens（0%）。"},
                ),
            ],
        )

        self.assertEqual(tool_result["action"], "list")
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn("当前可用 MCP 服务共 1 个", followup.recovery_fragment.text)

    def test_normalize_tool_result_for_followup_does_not_direct_render_mcp_call_inside_multi_step_request(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="mcp",
            tool_payload={
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
            },
            tool_result={
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"}}}]',
                "ok": True,
                "is_error": False,
            },
            peak_input_tokens_estimate=120,
            peak_stage="tool_followup",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="先查 GitHub 最近提交，再总结当前上下文。",
            tool_history_count=1,
            tool_history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "list_commits",
                        "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
                    },
                    tool_result={"ok": True},
                )
            ],
        )

        self.assertEqual(tool_result["tool_name"], "list_commits")
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)

    def test_normalize_tool_result_for_followup_does_not_direct_render_single_intent_without_finalize_signal(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="mcp",
            tool_payload={
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
            },
            tool_result={
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
                "result_text": (
                    '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"}}}]'
                ),
                "ok": True,
                "is_error": False,
            },
            peak_input_tokens_estimate=120,
            peak_stage="tool_followup",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库最近一次提交是什么时候？",
            tool_history_count=1,
            tool_history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "list_commits",
                        "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
                    },
                    tool_result={"ok": True},
                )
            ],
        )

        self.assertEqual(tool_result["tool_name"], "list_commits")
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn("CloudWide851/easy-agent 最近一次提交是", followup.recovery_fragment.text)

    def test_normalize_tool_result_for_followup_does_not_direct_render_mcp_call_for_after_clause_request(
        self,
    ) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="mcp",
            tool_payload={
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
            },
            tool_result={
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"}}}]',
                "ok": True,
                "is_error": False,
            },
            peak_input_tokens_estimate=120,
            peak_stage="tool_followup",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="查 GitHub 最近提交后总结当前上下文。",
            tool_history_count=1,
            tool_history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "list_commits",
                        "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
                    },
                    tool_result={"ok": True},
                )
            ],
        )

        self.assertEqual(tool_result["tool_name"], "list_commits")
        self.assertIsNone(followup.terminal_text)
        self.assertIsNotNone(followup.recovery_fragment)

    def test_normalize_tool_result_for_followup_direct_renders_github_commit_result(self) -> None:
        tool_result, followup = normalize_tool_result_for_followup(
            tool_name="mcp",
            tool_payload={
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
                "finalize_response": True,
            },
            tool_result={
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
                "result_text": (
                    '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"}}}]'
                ),
                "ok": True,
                "is_error": False,
            },
            peak_input_tokens_estimate=120,
            peak_stage="tool_followup",
            actual_peak_input_tokens=None,
            actual_peak_output_tokens=None,
            actual_peak_total_tokens=None,
            actual_peak_stage=None,
            message="请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库最近一次提交是什么时候？",
            tool_history_count=1,
            tool_history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "list_commits",
                        "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
                    },
                    tool_result={"ok": True},
                )
            ],
        )

        self.assertEqual(tool_result["tool_name"], "list_commits")
        self.assertIn(
            "CloudWide851/easy-agent 最近一次提交是",
            followup.terminal_text or "",
        )
        self.assertIsNotNone(followup.recovery_fragment)
        self.assertIn(
            "CloudWide851/easy-agent 最近一次提交是",
            followup.recovery_fragment.text,
        )

    def test_build_finalization_evidence_ledger_uses_one_successful_tool_as_required_evidence(
        self,
    ) -> None:
        ledger = build_finalization_evidence_ledger(
            user_message="请总结本轮结果",
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "UTC"},
                    tool_result={"iso_time": "2026-04-25T10:00:00Z"},
                )
            ],
            model_request_count=2,
            requires_result_coverage=True,
            requires_round_trip_report=False,
        )

        self.assertIsInstance(ledger, FinalizationEvidenceLedger)
        self.assertEqual(ledger.tool_call_count, 1)
        self.assertEqual(len(ledger.items), 1)
        self.assertEqual(ledger.items[0].ordinal, 1)
        self.assertEqual(ledger.items[0].tool_name, "time")
        self.assertEqual(ledger.items[0].payload_summary, "timezone=UTC")
        self.assertTrue(ledger.items[0].required_for_user_request)
        self.assertIn("现在是", ledger.items[0].result_summary)

    def test_build_finalization_evidence_ledger_preserves_order_and_prefers_recovery_fragment(
        self,
    ) -> None:
        ledger = build_finalization_evidence_ledger(
            user_message="请按顺序总结本轮结果",
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "UTC"},
                    tool_result={"iso_time": "2026-04-25T10:00:00Z"},
                ),
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "list"},
                    tool_result={"action": "list", "servers": [{"server_id": "github", "tool_count": 12}]},
                    recovery_fragment=None,
                ),
                ToolExchange(
                    tool_name="spawn_subagent",
                    tool_payload={"notify_on_finish": True},
                    tool_result={"status": "accepted", "ok": True},
                    recovery_fragment={
                        "text": "子 agent 已进入后台执行。",
                        "source": "tool_result",
                        "tool_name": "spawn_subagent",
                    },
                ),
            ],
            model_request_count=4,
            requires_result_coverage=True,
            requires_round_trip_report=False,
        )

        self.assertEqual([item.tool_name for item in ledger.items], ["time", "mcp", "spawn_subagent"])
        self.assertIn("github", ledger.items[1].result_summary)
        self.assertEqual(ledger.items[2].result_summary, "子 agent 已进入后台执行。")

    def test_build_finalization_evidence_ledger_adds_loop_meta_only_when_round_trip_reporting_is_required(
        self,
    ) -> None:
        without_loop_meta = build_finalization_evidence_ledger(
            user_message="总结一下",
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "UTC"},
                    tool_result={"iso_time": "2026-04-25T10:00:00Z"},
                )
            ],
            model_request_count=3,
            requires_result_coverage=True,
            requires_round_trip_report=False,
        )
        with_loop_meta = build_finalization_evidence_ledger(
            user_message="总结一下并说明往返次数",
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "UTC"},
                    tool_result={"iso_time": "2026-04-25T10:00:00Z"},
                )
            ],
            model_request_count=3,
            requires_result_coverage=True,
            requires_round_trip_report=True,
        )

        self.assertEqual(len(without_loop_meta.items), 1)
        self.assertEqual(len(with_loop_meta.items), 2)
        self.assertEqual(with_loop_meta.items[-1].evidence_source, "loop_meta")
        self.assertIn("3 次模型请求", with_loop_meta.items[-1].result_summary)

    def test_build_finalization_evidence_ledger_marks_failed_step_as_non_required_success_evidence(
        self,
    ) -> None:
        ledger = build_finalization_evidence_ledger(
            user_message="总结一下本轮情况",
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "UTC"},
                    tool_result={"iso_time": "2026-04-25T10:00:00Z"},
                ),
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "call", "server_id": "github", "tool_name": "get_me"},
                    tool_result={
                        "ok": False,
                        "is_error": True,
                        "error_code": "TOOL_EXECUTION_FAILED",
                        "error_text": "工具执行失败，请重试。",
                    },
                ),
            ],
            model_request_count=3,
            requires_result_coverage=True,
            requires_round_trip_report=False,
        )

        self.assertEqual(len(ledger.items), 2)
        self.assertTrue(ledger.items[0].required_for_user_request)
        self.assertFalse(ledger.items[1].required_for_user_request)
        self.assertIn("工具执行失败", ledger.items[1].result_summary)


if __name__ == "__main__":
    unittest.main()
