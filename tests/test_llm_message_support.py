import unittest

from marten_runtime.runtime.llm_client import (
    FinalizationEvidenceItem,
    FinalizationEvidenceLedger,
    LLMRequest,
    ToolExchange,
)
from marten_runtime.runtime.llm_message_support import (
    build_openai_chat_payload,
    build_openai_messages,
)


class LLMMessageSupportTests(unittest.TestCase):
    def _extract_ledger_blocks(self, messages: list[dict[str, object]]) -> list[str]:
        blocks: list[str] = []
        for item in messages:
            if item.get("role") != "system":
                continue
            content = str(item.get("content") or "")
            if "Current-turn evidence ledger:" not in content:
                continue
            suffix = content.split("Current-turn evidence ledger:", 1)[1]
            block = "Current-turn evidence ledger:" + suffix.split("\n\n", 1)[0]
            blocks.append(block)
        return blocks

    def test_llm_request_can_carry_finalization_evidence_ledger(self) -> None:
        ledger = FinalizationEvidenceLedger(
            user_message="请按顺序总结本轮结果",
            tool_call_count=1,
            model_request_count=2,
            requires_result_coverage=True,
            items=[
                FinalizationEvidenceItem(
                    ordinal=1,
                    tool_name="time",
                    result_summary="当前时间是 2026-04-25T10:00:00Z",
                )
            ],
        )

        request = LLMRequest(
            session_id="sess_ledger_request",
            trace_id="trace_ledger_request",
            message="请按顺序总结本轮结果",
            agent_id="main",
            app_id="main_agent",
            finalization_evidence_ledger=ledger,
        )

        self.assertIs(request.finalization_evidence_ledger, ledger)
        self.assertEqual(request.finalization_evidence_ledger.items[0].tool_name, "time")

    def test_zero_tool_request_omits_ledger_cleanly_from_provider_payload(self) -> None:
        request = LLMRequest(
            session_id="sess_zero_tool_ledger",
            trace_id="trace_zero_tool_ledger",
            message="你好",
            agent_id="main",
            app_id="main_agent",
        )

        payload = build_openai_chat_payload("gpt-4.1", request)

        self.assertIn("messages", payload)
        self.assertNotIn("tools", payload)
        serialized = str(payload)
        self.assertNotIn("finalization_evidence_ledger", serialized)
        self.assertNotIn("requires_result_coverage", serialized)

    def test_provider_transcript_shape_stays_canonical_when_ledger_is_present(self) -> None:
        request = LLMRequest(
            session_id="sess_ledger_transcript",
            trace_id="trace_ledger_transcript",
            message="继续整理刚刚的结果",
            agent_id="main",
            app_id="main_agent",
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "UTC"},
                    tool_result={"iso_time": "2026-04-25T10:00:00Z"},
                )
            ],
            finalization_evidence_ledger=FinalizationEvidenceLedger(
                user_message="继续整理刚刚的结果",
                tool_call_count=1,
                model_request_count=2,
                requires_result_coverage=True,
                items=[
                    FinalizationEvidenceItem(
                        ordinal=1,
                        tool_name="time",
                        payload_summary="timezone=UTC",
                        result_summary="北京时间 18:00",
                    )
                ],
            ),
        )

        messages = build_openai_messages(request)
        payload = build_openai_chat_payload("gpt-4.1", request)

        assistant_calls = [
            item for item in messages if item.get("role") == "assistant" and item.get("tool_calls")
        ]
        tool_results = [item for item in messages if item.get("role") == "tool"]
        self.assertEqual(len(assistant_calls), 1)
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(
            tool_results[0]["content"],
            '{"iso_time": "2026-04-25T10:00:00Z"}',
        )
        self.assertEqual(len(self._extract_ledger_blocks(messages)), 1)
        self.assertNotIn("finalization_evidence_ledger", str(payload))

    def test_normal_conversation_request_does_not_include_ledger_block(self) -> None:
        request = LLMRequest(
            session_id="sess_no_ledger_block",
            trace_id="trace_no_ledger_block",
            message="你好",
            agent_id="main",
            app_id="main_agent",
            finalization_evidence_ledger=FinalizationEvidenceLedger(
                user_message="你好",
                tool_call_count=0,
            ),
        )

        messages = build_openai_messages(request)

        self.assertEqual(self._extract_ledger_blocks(messages), [])

    def test_subagent_request_includes_child_task_contract(self) -> None:
        request = LLMRequest(
            session_id="sess_subagent_child_contract",
            trace_id="trace_subagent_child_contract",
            message=(
                "使用 GitHub MCP 查询仓库最近一次提交时间，"
                "主线程只需先确认已受理。"
            ),
            agent_id="main",
            app_id="main_agent",
            request_kind="subagent",
            available_tools=["mcp", "runtime", "time"],
        )

        messages = build_openai_messages(request)
        joined = "\n".join(str(item.get("content") or "") for item in messages)

        self.assertIn("Subagent task contract", joined)
        self.assertIn("Complete the child work", joined)
        self.assertIn("parent-thread acknowledgement", joined)
        self.assertIn("call the available tools needed", joined)

    def test_tool_followup_request_includes_compact_ledger_block(self) -> None:
        request = LLMRequest(
            session_id="sess_tool_followup_ledger",
            trace_id="trace_tool_followup_ledger",
            message="请按顺序总结本轮结果",
            agent_id="main",
            app_id="main_agent",
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "UTC"},
                    tool_result={"iso_time": "2026-04-25T10:00:00Z"},
                )
            ],
            finalization_evidence_ledger=FinalizationEvidenceLedger(
                user_message="请按顺序总结本轮结果",
                tool_call_count=1,
                model_request_count=2,
                requires_result_coverage=True,
                items=[
                    FinalizationEvidenceItem(
                        ordinal=1,
                        tool_name="time",
                        payload_summary="timezone=UTC",
                        result_summary="现在是 UTC 2026-04-25 10:00",
                        required_for_user_request=True,
                    )
                ],
            ),
        )

        messages = build_openai_messages(request)
        blocks = self._extract_ledger_blocks(messages)

        self.assertEqual(len(blocks), 1)
        self.assertIn("requires_result_coverage=yes", blocks[0])
        self.assertIn("1. tool=time", blocks[0])
        self.assertIn("result=现在是 UTC 2026-04-25 10:00", blocks[0])
        self.assertNotIn('{"iso_time": "2026-04-25T10:00:00Z"}', blocks[0])
        self.assertLess(len(blocks[0]), 500)

    def test_three_tool_followup_ledger_block_stays_bounded(self) -> None:
        request = LLMRequest(
            session_id="sess_three_tool_ledger",
            trace_id="trace_three_tool_ledger",
            message="请按顺序总结本轮结果并说明往返次数",
            agent_id="main",
            app_id="main_agent",
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "UTC"},
                    tool_result={"iso_time": "2026-04-25T10:00:00Z"},
                ),
                ToolExchange(
                    tool_name="runtime",
                    tool_payload={"action": "context_status"},
                    tool_result={"summary": "当前估算占用 100/184000 tokens（0%）。"},
                ),
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "list"},
                    tool_result={"action": "list", "servers": [{"server_id": "github", "tool_count": 12}]},
                ),
            ],
            finalization_evidence_ledger=FinalizationEvidenceLedger(
                user_message="请按顺序总结本轮结果并说明往返次数",
                tool_call_count=3,
                model_request_count=4,
                requires_result_coverage=True,
                requires_round_trip_report=True,
                items=[
                    FinalizationEvidenceItem(ordinal=1, tool_name="time", result_summary="现在是 UTC 2026-04-25 10:00"),
                    FinalizationEvidenceItem(ordinal=2, tool_name="runtime", result_summary="当前估算占用 100/184000 tokens（0%）。"),
                    FinalizationEvidenceItem(ordinal=3, tool_name="mcp", result_summary="当前可用 MCP 服务共 1 个。"),
                    FinalizationEvidenceItem(
                        ordinal=4,
                        tool_name="runtime_loop",
                        result_summary="本轮共发生 4 次模型请求，执行了 3 次工具调用。",
                        evidence_source="loop_meta",
                    ),
                ],
            ),
        )

        blocks = self._extract_ledger_blocks(build_openai_messages(request))

        self.assertEqual(len(blocks), 1)
        self.assertIn("4. tool=runtime_loop", blocks[0])
        self.assertLess(len(blocks[0]), 900)

    def test_finalization_retry_request_includes_ledger_block_and_no_callable_tools(self) -> None:
        request = LLMRequest(
            session_id="sess_finalization_retry_ledger",
            trace_id="trace_finalization_retry_ledger",
            message="继续整理刚刚的结果",
            agent_id="main",
            app_id="main_agent",
            request_kind="finalization_retry",
            available_tools=["time"],
            tool_history=[
                ToolExchange(
                    tool_name="time",
                    tool_payload={"timezone": "UTC"},
                    tool_result={"iso_time": "2026-04-25T10:00:00Z"},
                )
            ],
            finalization_evidence_ledger=FinalizationEvidenceLedger(
                user_message="继续整理刚刚的结果",
                tool_call_count=1,
                model_request_count=3,
                requires_result_coverage=True,
                items=[
                    FinalizationEvidenceItem(
                        ordinal=1,
                        tool_name="time",
                        result_summary="现在是 UTC 2026-04-25 10:00",
                    )
                ],
            ),
        )

        messages = build_openai_messages(request)
        payload = build_openai_chat_payload("gpt-4.1", request)
        blocks = self._extract_ledger_blocks(messages)

        self.assertEqual(len(blocks), 1)
        self.assertIn("Current-turn evidence ledger:", blocks[0])
        self.assertNotIn("tools", payload)
        self.assertLess(len(blocks[0]), 500)


if __name__ == "__main__":
    unittest.main()
