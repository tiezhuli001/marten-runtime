import unittest

from marten_runtime.runtime.llm_client import ToolExchange, ToolFollowupFragment
from marten_runtime.runtime.recovery_flow import (
    assess_finalization_text,
    is_generic_tool_failure_text,
    recover_successful_tool_followup_text,
    recover_successful_tool_followup_text_with_meta,
    recover_tool_result_text,
)
from marten_runtime.runtime.tool_followup_support import build_finalization_evidence_ledger


class RecoveryFlowTests(unittest.TestCase):
    def _fragment_history(self) -> list[ToolExchange]:
        return [
            ToolExchange(
                tool_name="time",
                tool_payload={"timezone": "Asia/Shanghai"},
                tool_result={"ok": True},
                recovery_fragment=ToolFollowupFragment(
                    text="现在是北京时间 2026-04-20 12:30:00。",
                    source="tool_result",
                    tool_name="time",
                ),
            ),
            ToolExchange(
                tool_name="runtime",
                tool_payload={"action": "context_status"},
                tool_result={"ok": True},
                recovery_fragment=ToolFollowupFragment(
                    text="当前上下文使用详情：预计占用 1234/184000 tokens。",
                    source="tool_result",
                    tool_name="runtime",
                ),
            ),
            ToolExchange(
                tool_name="mcp",
                tool_payload={"action": "list"},
                tool_result={"ok": True},
                recovery_fragment=ToolFollowupFragment(
                    text="当前可用 MCP 服务共 1 个。",
                    source="tool_result",
                    tool_name="mcp",
                ),
            ),
        ]

    def test_is_generic_tool_failure_text_matches_known_failure_copy(self) -> None:
        self.assertTrue(is_generic_tool_failure_text("工具执行失败，请重试。"))
        self.assertTrue(is_generic_tool_failure_text("tool execution failed, please retry."))
        self.assertFalse(is_generic_tool_failure_text("这不是工具失败文案"))

    def test_assess_finalization_text_marks_empty_text_retryable_when_safe_fragments_exist(
        self,
    ) -> None:
        self.assertEqual(
            assess_finalization_text(self._fragment_history(), ""),
            "retryable_degraded",
        )

    def test_assess_finalization_text_marks_generic_failure_copy_retryable_when_safe_fragments_exist(
        self,
    ) -> None:
        self.assertEqual(
            assess_finalization_text(self._fragment_history(), "工具执行失败，请重试。"),
            "retryable_degraded",
        )

    def test_assess_finalization_text_marks_strict_fragment_subset_retryable(self) -> None:
        self.assertEqual(
            assess_finalization_text(
                self._fragment_history(),
                "现在是北京时间 2026-04-20 12:30:00。\n\n当前可用 MCP 服务共 1 个。",
            ),
            "retryable_degraded",
        )

    def test_assess_finalization_text_accepts_richer_freeform_text(self) -> None:
        self.assertEqual(
            assess_finalization_text(
                self._fragment_history(),
                (
                    "这轮链路已经完成。当前时间和上下文状态都已获取，"
                    "同时 GitHub MCP 服务可用，所以这是一条完整的多轮工具链路。"
                ),
            ),
            "accepted",
        )

    def test_assess_finalization_text_rejects_unbacked_current_session_identity_claim(
        self,
    ) -> None:
        self.assertEqual(
            assess_finalization_text([], "当前会话 id 是 sess_fake123。"),
            "unrecoverable",
        )

    def test_assess_finalization_text_accepts_current_session_identity_claim_when_history_confirms(
        self,
    ) -> None:
        history = [
            ToolExchange(
                tool_name="session",
                tool_payload={"action": "show", "finalize_response": True},
                tool_result={
                    "action": "show",
                    "session": {
                        "session_id": "sess_current123",
                        "session_title": "当前会话",
                        "state": "running",
                        "message_count": 2,
                        "created_at": "2026-04-20T06:00:00+00:00",
                    },
                },
            )
        ]

        self.assertEqual(
            assess_finalization_text(history, "当前会话 id 是 sess_current123。"),
            "accepted",
        )

    def test_assess_finalization_text_marks_abstract_chain_summary_retryable_when_current_turn_explicitly_requires_full_coverage(
        self,
    ) -> None:
        self.assertEqual(
            assess_finalization_text(
                self._fragment_history(),
                "已按顺序完成，且这次请求明确发生了多次模型/工具往返。",
                user_message=(
                    "请严格按顺序先调用 time 获取当前时间，"
                    "再调用 runtime 查看当前 run 的 context_status，"
                    "再调用 mcp 列出 github server 的可用工具，"
                    "最后用中文总结这次链路，并明确说明这次请求是否发生了多次模型/工具往返。"
                ),
                model_request_count=4,
            ),
            "retryable_degraded",
        )

    def test_assess_finalization_text_accepts_explicit_chain_summary_after_covering_each_current_turn_result(
        self,
    ) -> None:
        self.assertEqual(
            assess_finalization_text(
                self._fragment_history(),
                (
                    "现在是北京时间 2026-04-20 12:30:00。"
                    "当前上下文使用详情显示预计占用 1234/184000 tokens。"
                    "当前可用 MCP 服务共 1 个。"
                    "这次请求发生了多次模型/工具往返。"
                ),
                user_message=(
                    "请严格按顺序先调用 time 获取当前时间，"
                    "再调用 runtime 查看当前 run 的 context_status，"
                    "再调用 mcp 列出 github server 的可用工具，"
                    "最后用中文总结这次链路，并明确说明这次请求是否发生了多次模型/工具往返。"
                ),
                model_request_count=4,
            ),
            "accepted",
        )

    def test_assess_finalization_text_accepts_when_ledger_required_items_are_all_covered(
        self,
    ) -> None:
        history = self._fragment_history()
        ledger = build_finalization_evidence_ledger(
            user_message="请按顺序总结本轮结果",
            tool_history=history,
            model_request_count=4,
            requires_result_coverage=True,
            requires_round_trip_report=False,
        )

        self.assertEqual(
            assess_finalization_text(
                history,
                (
                    "现在是北京时间 2026-04-20 12:30:00。"
                    "当前上下文使用详情：预计占用 1234/184000 tokens。"
                    "当前可用 MCP 服务共 1 个。"
                ),
                user_message="contract_repair",
                model_request_count=4,
                finalization_evidence_ledger=ledger,
            ),
            "accepted",
        )

    def test_assess_finalization_text_marks_omitted_required_ledger_item_retryable(
        self,
    ) -> None:
        history = self._fragment_history()
        ledger = build_finalization_evidence_ledger(
            user_message="请按顺序总结本轮结果",
            tool_history=history,
            model_request_count=4,
            requires_result_coverage=True,
            requires_round_trip_report=False,
        )

        self.assertEqual(
            assess_finalization_text(
                history,
                "现在是北京时间 2026-04-20 12:30:00。\n\n当前可用 MCP 服务共 1 个。",
                user_message="contract_repair",
                model_request_count=4,
                finalization_evidence_ledger=ledger,
            ),
            "retryable_degraded",
        )

    def test_assess_finalization_text_requires_round_trip_statement_when_ledger_marks_it_required(
        self,
    ) -> None:
        history = self._fragment_history()
        ledger = build_finalization_evidence_ledger(
            user_message="请按顺序总结本轮结果并说明往返次数",
            tool_history=history,
            model_request_count=4,
            requires_result_coverage=True,
            requires_round_trip_report=True,
        )

        accepted_text = (
            "现在是北京时间 2026-04-20 12:30:00。"
            "当前上下文使用详情：预计占用 1234/184000 tokens。"
            "当前可用 MCP 服务共 1 个。"
            "本次请求共发生 4 次模型请求和 3 次工具调用，属于多次模型/工具往返。"
        )
        degraded_text = (
            "现在是北京时间 2026-04-20 12:30:00。"
            "当前上下文使用详情：预计占用 1234/184000 tokens。"
            "当前可用 MCP 服务共 1 个。"
        )

        self.assertEqual(
            assess_finalization_text(
                history,
                accepted_text,
                user_message="contract_repair",
                model_request_count=4,
                finalization_evidence_ledger=ledger,
            ),
            "accepted",
        )
        self.assertEqual(
            assess_finalization_text(
                history,
                degraded_text,
                user_message="contract_repair",
                model_request_count=4,
                finalization_evidence_ledger=ledger,
            ),
            "retryable_degraded",
        )

    def test_recover_successful_tool_followup_text_with_meta_keeps_partial_success_truthful_under_ledger(
        self,
    ) -> None:
        history = [
            ToolExchange(
                tool_name="time",
                tool_payload={"timezone": "UTC"},
                tool_result={"timezone": "UTC", "iso_time": "2026-04-20T04:30:00Z"},
                recovery_fragment=ToolFollowupFragment(
                    text="现在是 UTC 2026-04-20 04:30。",
                    source="tool_result",
                    tool_name="time",
                ),
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
        ]
        ledger = build_finalization_evidence_ledger(
            user_message="总结一下本轮情况",
            tool_history=history,
            model_request_count=3,
            requires_result_coverage=True,
            requires_round_trip_report=False,
        )

        text = recover_successful_tool_followup_text_with_meta(
            history,
            model_request_count=3,
            finalization_evidence_ledger=ledger,
        )

        self.assertIn("现在是 UTC 2026-04-20 04:30。", text)
        self.assertNotIn("工具执行失败，请重试。", text)

    def test_contract_repair_style_recheck_uses_same_bounded_ledger_source(
        self,
    ) -> None:
        history = self._fragment_history()
        ledger = build_finalization_evidence_ledger(
            user_message="请按顺序总结本轮结果",
            tool_history=history,
            model_request_count=4,
            requires_result_coverage=True,
            requires_round_trip_report=False,
        )

        self.assertEqual(
            assess_finalization_text(
                history,
                (
                    "现在是北京时间 2026-04-20 12:30:00。"
                    "当前上下文使用详情：预计占用 1234/184000 tokens。"
                    "当前可用 MCP 服务共 1 个。"
                ),
                user_message="这一轮来自 contract_repair，但判断仍应只看当前证据",
                model_request_count=4,
                finalization_evidence_ledger=ledger,
            ),
            "accepted",
        )

    def test_assess_finalization_text_marks_unbacked_same_session_claim_unrecoverable(
        self,
    ) -> None:
        self.assertEqual(
            assess_finalization_text(
                [],
                "当前已在会话 `sess_dcce8f9c`。",
            ),
            "unrecoverable",
        )

    def test_assess_finalization_text_accepts_backed_same_session_noop_claim(
        self,
    ) -> None:
        history = [
            ToolExchange(
                tool_name="session",
                tool_payload={"action": "resume", "session_id": "sess_dcce8f9c"},
                tool_result={
                    "ok": True,
                    "action": "resume",
                    "transition": {
                        "mode": "noop_same_session",
                        "binding_changed": False,
                    },
                    "session": {
                        "session_id": "sess_dcce8f9c",
                    },
                },
            )
        ]

        self.assertEqual(
            assess_finalization_text(
                history,
                "当前已在会话 `sess_dcce8f9c`。",
            ),
            "accepted",
        )

    def test_assess_finalization_text_rejects_session_claim_with_wrong_session_id(
        self,
    ) -> None:
        history = [
            ToolExchange(
                tool_name="session",
                tool_payload={"action": "resume", "session_id": "sess_real"},
                tool_result={
                    "ok": True,
                    "action": "resume",
                    "transition": {
                        "mode": "switched",
                        "binding_changed": True,
                        "target_session_id": "sess_real",
                    },
                    "session": {
                        "session_id": "sess_real",
                    },
                },
            )
        ]

        self.assertEqual(
            assess_finalization_text(
                history,
                "已切换到会话 `sess_wrong`。",
            ),
            "retryable_degraded",
        )

    def test_assess_finalization_text_rejects_switched_wording_for_same_session_noop(
        self,
    ) -> None:
        history = [
            ToolExchange(
                tool_name="session",
                tool_payload={"action": "resume", "session_id": "sess_dcce8f9c"},
                tool_result={
                    "ok": True,
                    "action": "resume",
                    "transition": {
                        "mode": "noop_same_session",
                        "binding_changed": False,
                        "target_session_id": "sess_dcce8f9c",
                    },
                    "session": {
                        "session_id": "sess_dcce8f9c",
                    },
                },
            )
        ]

        self.assertEqual(
            assess_finalization_text(
                history,
                "已切换到会话 `sess_dcce8f9c`。",
            ),
            "retryable_degraded",
        )

    def test_assess_finalization_text_marks_unbacked_subagent_acceptance_unrecoverable(
        self,
    ) -> None:
        self.assertEqual(
            assess_finalization_text(
                [],
                "已受理，子 agent 正在后台执行，完成后会通知你结果。",
            ),
            "unrecoverable",
        )

    def test_assess_finalization_text_rejects_spawn_subagent_running_wording_for_queued_result(
        self,
    ) -> None:
        history = [
            ToolExchange(
                tool_name="spawn_subagent",
                tool_payload={"notify_on_finish": True},
                tool_result={
                    "ok": True,
                    "status": "accepted",
                    "queue_state": "queued",
                },
            )
        ]

        self.assertEqual(
            assess_finalization_text(
                history,
                "已受理，子 agent 正在后台执行，完成后会通知你结果。",
            ),
            "retryable_degraded",
        )

    def test_assess_finalization_text_rejects_spawn_subagent_notify_wording_when_notifications_disabled(
        self,
    ) -> None:
        history = [
            ToolExchange(
                tool_name="spawn_subagent",
                tool_payload={"notify_on_finish": False},
                tool_result={
                    "ok": True,
                    "status": "accepted",
                    "queue_state": "running",
                },
            )
        ]

        self.assertEqual(
            assess_finalization_text(
                history,
                "已受理，子 agent 正在后台执行，完成后会通知你结果。",
            ),
            "retryable_degraded",
        )

    def test_assess_finalization_text_accepts_spawn_subagent_queued_wording_with_matching_result(
        self,
    ) -> None:
        history = [
            ToolExchange(
                tool_name="spawn_subagent",
                tool_payload={"notify_on_finish": True},
                tool_result={
                    "ok": True,
                    "status": "accepted",
                    "queue_state": "queued",
                },
            )
        ]

        self.assertEqual(
            assess_finalization_text(
                history,
                "已受理，子 agent 已进入队列，开始后会通知你结果。",
            ),
            "accepted",
        )

    def test_assess_finalization_text_marks_empty_text_retryable_when_shared_evidence_rule_can_still_summarize(
        self,
    ) -> None:
        history = [
            ToolExchange(
                tool_name="mcp",
                tool_payload={"action": "call"},
                tool_result={"ok": True},
            )
        ]

        self.assertEqual(
            assess_finalization_text(history, ""),
            "retryable_degraded",
        )

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

    def test_recover_successful_tool_followup_text_prefers_combined_three_step_sequence(self) -> None:
        text = recover_successful_tool_followup_text(
            [
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "Asia/Shanghai"},
                    tool_result={"timezone": "Asia/Shanghai", "iso_time": "2026-04-20T12:30:00+08:00"},
                ),
                ToolExchange(
                    tool_name="runtime",
                    tool_payload={"action": "context_status"},
                    tool_result={
                        "ok": True,
                        "action": "context_status",
                        "summary": "当前估算占用 1200/184000 tokens（1%）。",
                        "current_run": {
                            "initial_input_tokens_estimate": 1200,
                            "peak_input_tokens_estimate": 1200,
                            "peak_stage": "initial_request",
                            "actual_cumulative_input_tokens": 0,
                            "actual_cumulative_output_tokens": 0,
                            "actual_cumulative_total_tokens": 0,
                            "actual_peak_input_tokens": None,
                            "actual_peak_output_tokens": None,
                            "actual_peak_total_tokens": None,
                            "actual_peak_stage": None,
                        },
                        "next_request_estimate": {
                            "input_tokens_estimate": 1200,
                            "effective_window_tokens": 184000,
                            "context_window_tokens": 200000,
                            "estimator_kind": "rough",
                            "degraded": True,
                        },
                        "effective_window": 184000,
                        "context_window": 200000,
                        "estimated_usage": 1200,
                        "usage_percent": 1,
                        "compaction_status": "none",
                        "latest_checkpoint": "none",
                        "estimate_source": "rough",
                        "last_actual_usage": None,
                        "last_completed_run": None,
                        "model_profile": "minimax_m25",
                    },
                ),
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "list"},
                    tool_result={
                        "action": "list",
                        "servers": [{"server_id": "github", "tool_count": 38, "state": "ready"}],
                    },
                ),
            ]
        )

        self.assertIn("当前上下文使用详情", text)
        self.assertIn("当前可用 MCP 服务共 1 个", text)

    def test_retryable_degraded_sequence_recovers_via_current_contract(self) -> None:
        history = [
            ToolExchange(
                tool_name="time",
                tool_payload={"timezone": "Asia/Shanghai"},
                tool_result={"timezone": "Asia/Shanghai", "iso_time": "2026-04-20T12:30:00+08:00"},
            ),
            ToolExchange(
                tool_name="runtime",
                tool_payload={"action": "context_status"},
                tool_result={
                    "ok": True,
                    "action": "context_status",
                    "summary": "当前估算占用 1200/184000 tokens（1%）。",
                    "current_run": {
                        "initial_input_tokens_estimate": 1200,
                        "peak_input_tokens_estimate": 1200,
                        "peak_stage": "initial_request",
                        "actual_cumulative_input_tokens": 0,
                        "actual_cumulative_output_tokens": 0,
                        "actual_cumulative_total_tokens": 0,
                        "actual_peak_input_tokens": None,
                        "actual_peak_output_tokens": None,
                        "actual_peak_total_tokens": None,
                        "actual_peak_stage": None,
                    },
                    "next_request_estimate": {
                        "input_tokens_estimate": 1200,
                        "effective_window_tokens": 184000,
                        "context_window_tokens": 200000,
                        "estimator_kind": "rough",
                        "degraded": True,
                    },
                    "effective_window": 184000,
                    "context_window": 200000,
                    "estimated_usage": 1200,
                    "usage_percent": 1,
                    "compaction_status": "none",
                    "latest_checkpoint": "none",
                    "estimate_source": "rough",
                    "last_actual_usage": None,
                    "last_completed_run": None,
                    "model_profile": "minimax_m25",
                },
            ),
            ToolExchange(
                tool_name="mcp",
                tool_payload={"action": "list"},
                tool_result={
                    "action": "list",
                    "servers": [{"server_id": "github", "tool_count": 38, "state": "discovered"}],
                },
            ),
        ]

        final_text = "当前可用 MCP 服务共 1 个。\n- 1. github（38 个工具，状态 discovered）"

        self.assertEqual(
            assess_finalization_text(history, final_text),
            "retryable_degraded",
        )
        text = recover_successful_tool_followup_text(history)

        self.assertIn("现在是北京时间", text)
        self.assertIn("当前上下文使用详情", text)

    def test_single_tool_recovery_does_not_append_loop_meta_noise(self) -> None:
        history = [
            ToolExchange(
                tool_name="time",
                tool_payload={"timezone": "UTC"},
                tool_result={"timezone": "UTC", "iso_time": "2026-04-20T12:30:00+00:00"},
            )
        ]

        text = recover_successful_tool_followup_text_with_meta(
            history,
            model_request_count=3,
        )

        self.assertIn("现在是UTC", text)
        self.assertNotIn("本次请求共发生", text)

    def test_accepted_freeform_text_does_not_enter_recovery_path(self) -> None:
        history = [
            ToolExchange(
                tool_name="time",
                tool_payload={"timezone": "Asia/Shanghai"},
                tool_result={"timezone": "Asia/Shanghai", "iso_time": "2026-04-20T12:30:00+08:00"},
            ),
            ToolExchange(
                tool_name="runtime",
                tool_payload={"action": "context_status"},
                tool_result={
                    "ok": True,
                    "action": "context_status",
                    "summary": "当前估算占用 1200/184000 tokens（1%）。",
                    "current_run": {"initial_input_tokens_estimate": 1200},
                    "next_request_estimate": {
                        "input_tokens_estimate": 1200,
                        "effective_window_tokens": 184000,
                        "context_window_tokens": 200000,
                        "estimator_kind": "rough",
                        "degraded": True,
                    },
                    "effective_window": 184000,
                    "context_window": 200000,
                    "estimated_usage": 1200,
                    "usage_percent": 1,
                    "compaction_status": "none",
                    "latest_checkpoint": "none",
                    "estimate_source": "rough",
                    "last_actual_usage": None,
                    "last_completed_run": None,
                    "model_profile": "minimax_m25",
                },
            ),
            ToolExchange(
                tool_name="mcp",
                tool_payload={"action": "list"},
                tool_result={
                    "action": "list",
                    "servers": [{"server_id": "github", "tool_count": 38, "state": "discovered"}],
                },
            ),
        ]

        self.assertEqual(
            assess_finalization_text(
                history,
                "三步链路已经执行完成，time、runtime、mcp 的结果都拿到了。",
            ),
            "accepted",
        )

    def test_recover_tool_result_text_returns_empty_for_missing_history(self) -> None:
        self.assertEqual(recover_tool_result_text([]), "")


if __name__ == "__main__":
    unittest.main()
