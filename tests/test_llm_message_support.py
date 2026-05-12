import unittest

from marten_runtime.runtime.llm_client import (
    ConversationMessage,
    FinalizationEvidenceItem,
    FinalizationEvidenceLedger,
    LLMRequest,
    ToolExchange,
)
from marten_runtime.runtime.capabilities import (
    get_capability_declarations,
    render_capability_catalog,
)
from marten_runtime.runtime.llm_message_support import (
    build_openai_chat_payload,
    build_openai_messages,
)
from marten_runtime.runtime.llm_request_instructions import request_specific_instruction
from marten_runtime.runtime.loop import _build_contract_repair_request


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
            finalization_evidence_ledger=ledger,
        )

        self.assertIs(request.finalization_evidence_ledger, ledger)
        self.assertEqual(request.finalization_evidence_ledger.items[0].tool_name, "time")

    def test_session_summary_request_does_not_inherit_interactive_guardrails(self) -> None:
        request = LLMRequest(
            session_id="sess_summary_only",
            trace_id="trace_summary_only",
            message="Title: ... Preview: ...",
            summary_input_text="帮我给这个会话起标题",
            agent_id="main",
            request_kind="session_summary",
        )

        messages = build_openai_messages(request)

        self.assertEqual(messages, [{"role": "user", "content": "Title: ... Preview: ..."}])

    def test_zero_tool_request_omits_ledger_cleanly_from_provider_payload(self) -> None:
        request = LLMRequest(
            session_id="sess_zero_tool_ledger",
            trace_id="trace_zero_tool_ledger",
            message="你好",
            agent_id="main",
        )

        payload = build_openai_chat_payload("gpt-4.1", request)

        self.assertIn("messages", payload)
        self.assertNotIn("tools", payload)
        serialized = str(payload)
        self.assertNotIn("finalization_evidence_ledger", serialized)
        self.assertEqual(self._extract_ledger_blocks(payload["messages"]), [])

    def test_provider_transcript_shape_stays_canonical_when_ledger_is_present(self) -> None:
        request = LLMRequest(
            session_id="sess_ledger_transcript",
            trace_id="trace_ledger_transcript",
            message="继续整理刚刚的结果",
            agent_id="main",
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
            finalization_evidence_ledger=FinalizationEvidenceLedger(
                user_message="你好",
                tool_call_count=0,
            ),
        )

        messages = build_openai_messages(request)

        self.assertEqual(self._extract_ledger_blocks(messages), [])

    def test_large_capability_catalog_is_compacted_to_available_tool_surface(self) -> None:
        declarations = get_capability_declarations()
        request = LLMRequest(
            session_id="sess_compact_catalog",
            trace_id="trace_compact_catalog",
            message="帮我看下今天 github 热门仓库",
            agent_id="main",
            capability_catalog_text=render_capability_catalog(declarations),
            available_tools=["mcp", "time"],
        )

        messages = build_openai_messages(request)
        joined = "\n".join(
            str(item.get("content") or "")
            for item in messages
            if item.get("role") == "system"
        )

        self.assertIn("Capability catalog:", joined)
        self.assertIn("- mcp:", joined)
        self.assertIn("- time:", joined)
        self.assertNotIn("- session:", joined)
        self.assertNotIn("- memory:", joined)
        self.assertNotIn("- automation:", joined)

    def test_subagent_request_includes_child_task_contract(self) -> None:
        request = LLMRequest(
            session_id="sess_subagent_child_contract",
            trace_id="trace_subagent_child_contract",
            message=(
                "使用 GitHub MCP 查询仓库最近一次提交时间，"
                "主线程只需先确认已受理。"
            ),
            agent_id="main",
            request_kind="subagent",
            available_tools=["mcp", "runtime", "time"],
        )

        messages = build_openai_messages(request)
        joined = "\n".join(str(item.get("content") or "") for item in messages)

        self.assertIn("Subagent task contract", joined)
        self.assertIn("Complete the child work", joined)
        self.assertIn("parent-thread acknowledgement", joined)
        self.assertIn("call the available tools needed", joined)
        self.assertIn("Do not open nested child agents", joined)
        self.assertIn("current repository context is already attached", joined)
        self.assertIn("Do not ask the user to repeat owner/repo", joined)
        self.assertIn("Do not recursively enumerate every directory", joined)
        self.assertIn("Do not invent MCP tool names", joined)

    def test_contract_repair_request_uses_compact_repair_instruction_surface(self) -> None:
        request = LLMRequest(
            session_id="sess_contract_repair_surface",
            trace_id="trace_contract_repair_surface",
            message="你好",
            agent_id="main",
            available_tools=["session", "runtime", "memory", "time", "spawn_subagent"],
        )
        repair = _build_contract_repair_request(
            request,
            invalid_final_text="你好。有什么可以帮你的？",
        )

        interactive_instruction = request_specific_instruction(request) or ""
        repair_instruction = request_specific_instruction(repair) or ""

        self.assertIn("上一条回复已经直接结束", repair_instruction)
        self.assertIn("不要重复上一条无效回复", repair_instruction)
        self.assertNotIn("Tool finalization contract", repair_instruction)
        self.assertNotIn("当前时间/日期/datetime/时区时间", repair_instruction)
        self.assertLess(len(repair_instruction), len(interactive_instruction))


    def test_contract_repair_instruction_reads_attached_memory_without_tools(self) -> None:
        from marten_runtime.runtime.loop import _build_contract_repair_request

        base = LLMRequest(
            session_id="sess_memory_repair",
            trace_id="trace_memory_repair",
            message="继续当前任务，并说明你记住了什么。",
            agent_id="main",
            available_tools=["memory", "time", "runtime"],
            memory_text="User memory:\n# MEMORY\n\n## preferences\n- 以后始终用中文回复。",
        )
        repair = _build_contract_repair_request(
            base,
            invalid_final_text="我记住了：以后始终用中文回复。",
        )

        messages = build_openai_messages(repair)
        joined = "\n".join(str(item.get("content") or "") for item in messages)

        self.assertIn("读取已有 memory state 或已完成子任务摘要 -> 不调用工具，直接回答", joined)
        self.assertIn("User memory", joined)

    def test_contract_repair_request_omits_capability_catalog_block(self) -> None:
        declarations = get_capability_declarations()
        request = LLMRequest(
            session_id="sess_contract_repair_catalog",
            trace_id="trace_contract_repair_catalog",
            message="帮我看当前会话",
            agent_id="main",
            capability_catalog_text=render_capability_catalog(declarations),
            available_tools=["session", "runtime", "time"],
        )
        repair = _build_contract_repair_request(
            request,
            invalid_final_text="当前会话是 sess_fake123。",
        )

        messages = build_openai_messages(repair)
        joined = "\n".join(
            str(item.get("content") or "")
            for item in messages
            if item.get("role") == "system"
        )

        self.assertNotIn("Capability catalog:", joined)
        self.assertIn("最终答复必须以 ```finalization_contract``` JSON code block 结束", joined)

    def test_non_summary_request_can_carry_repository_context_text(self) -> None:
        request = LLMRequest(
            session_id="sess_repo_context_request",
            trace_id="trace_repo_context_request",
            message="后台看一下这个仓库最近提交都在改什么。",
            agent_id="main",
            repository_context_text=(
                "当前运行仓库上下文：\n"
                "- 仓库标识：tiezhuli001/marten-runtime\n"
                "- 仓库地址：https://github.com/tiezhuli001/marten-runtime"
            ),
        )

        messages = build_openai_messages(request)
        joined = "\n".join(str(item.get("content") or "") for item in messages)

        self.assertIn("当前运行仓库上下文", joined)
        self.assertIn("tiezhuli001/marten-runtime", joined)
        self.assertIn("https://github.com/tiezhuli001/marten-runtime", joined)


    def test_subagent_request_instruction_rejects_inventory_as_child_result(self) -> None:
        request = LLMRequest(
            session_id="sess_subagent_repo_structure",
            trace_id="trace_subagent_repo_structure",
            message="梳理这个仓库结构。",
            agent_id="main",
            request_kind="subagent",
            available_tools=["mcp"],
            repository_context_text="当前运行仓库上下文：\n- 仓库标识：tiezhuli001/marten-runtime",
        )

        messages = build_openai_messages(request)
        joined = "\n".join(str(item.get("content") or "") for item in messages)

        self.assertIn("plain MCP server inventory is discovery evidence", joined)
        self.assertIn("mcp.list already exposes the needed tool", joined)
        self.assertIn("README-like file content", joined)
        self.assertIn("path=README.md", joined)
        self.assertIn("Do not use mcp.detail for README tasks", joined)
        self.assertIn("Stop after enough evidence", joined)

    def test_subagent_completion_followup_instruction_preserves_child_anchor_terms(self) -> None:
        request = LLMRequest(
            session_id="sess_subagent_completion_followup",
            trace_id="trace_subagent_completion_followup",
            message="子任务完成了吗？直接给我一句中文摘要，明确它梳理的对象和结论。",
            agent_id="main",
            available_tools=["spawn_subagent"],
            conversation_messages=[
                ConversationMessage(
                    role="system",
                    content=(
                        "subagent task completed: 梳理当前仓库结构\n"
                        "summary: 仓库结构覆盖顶层目录、主要模块、关键配置、测试与文档。"
                    ),
                )
            ],
        )

        messages = build_openai_messages(request)
        joined = "\n".join(str(item.get("content") or "") for item in messages)

        self.assertIn("复制子任务完成记录里的连续对象短语", joined)
        self.assertIn("不要拆开、换序或改写这个对象短语", joined)
        self.assertIn("关键覆盖名词", joined)
        self.assertIn("不要把这些具体名词全部改写成抽象评价", joined)

    def test_non_summary_request_omits_working_context_text_from_system_messages(self) -> None:
        request = LLMRequest(
            session_id="sess_no_working_context_text",
            trace_id="trace_no_working_context_text",
            message="继续当前任务",
            agent_id="main",
            working_context={
                "active_goal": "继续当前任务",
                "recent_user_messages": ["约束：不要改 README"],
            },
            working_context_text=None,
        )

        messages = build_openai_messages(request)
        joined = "\n".join(str(item.get("content") or "") for item in messages if item.get("role") == "system")

        self.assertNotIn("近期用户消息", joined)
        self.assertNotIn("约束：不要改 README", joined)

    def test_tool_followup_request_includes_compact_ledger_block(self) -> None:
        request = LLMRequest(
            session_id="sess_tool_followup_ledger",
            trace_id="trace_tool_followup_ledger",
            message="请按顺序总结本轮结果",
            agent_id="main",
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

    def test_mcp_followup_for_compaction_continuation_can_return_to_summary_anchor(self) -> None:
        request = LLMRequest(
            session_id="sess_mcp_compaction_followup",
            trace_id="trace_mcp_compaction_followup",
            message="在压缩后的上下文里继续执行。",
            agent_id="main",
            available_tools=["mcp", "runtime", "session", "skill"],
            compact_summary_text=(
                "当前任务：日报同步告警排查。\n"
                "当前未完成事项：补失败摘要、核对卡片渲染差异、写出下一步动作。"
            ),
            requested_tool_name="mcp",
            requested_tool_payload={"action": "list"},
            tool_history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "list"},
                    tool_result={
                        "action": "list",
                        "servers": [{"server_id": "github", "tool_count": 38}],
                    },
                )
            ],
        )

        messages = build_openai_messages(request)
        joined = "\n".join(
            str(item.get("content") or "")
            for item in messages
            if item.get("role") == "system"
        )

        self.assertIn("continuation cue", joined)
        self.assertIn("compact summary", joined)
        self.assertIn("concrete task anchor and unfinished items", joined)
        self.assertIn("return to that task anchor and finish the answer directly", joined)
        self.assertIn("Do not stay in an MCP loop just because one MCP call already happened", joined)
        self.assertIn("tool_name=get_file_contents", joined)
        self.assertIn("do not stop at action=detail output", joined)

    def test_three_tool_followup_ledger_block_stays_bounded(self) -> None:
        request = LLMRequest(
            session_id="sess_three_tool_ledger",
            trace_id="trace_three_tool_ledger",
            message="请按顺序总结本轮结果并说明往返次数",
            agent_id="main",
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

    def test_github_file_content_tool_result_preserves_readme_structure_evidence(self) -> None:
        readme_text = (
            "# marten-runtime\n\n"
            "## 项目概览\n\n"
            "## 为什么做这个项目\n\n"
            "## 一眼看清\n\n"
            + "背景说明。" * 900
            + "\n\n## 快速开始\n\n"
            "这里是快速开始章节。\n"
        )
        request = LLMRequest(
            session_id="sess_readme_tool_result",
            trace_id="trace_readme_tool_result",
            message="梳理 README 结构",
            agent_id="main",
            tool_history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "get_file_contents",
                        "arguments": {
                            "owner": "tiezhuli001",
                            "repo": "marten-runtime",
                            "path": "README.md",
                        },
                    },
                    tool_result={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "get_file_contents",
                        "ok": True,
                        "is_error": False,
                        "result_text": readme_text,
                    },
                )
            ],
        )

        payload = build_openai_chat_payload("gpt-4.1", request)
        tool_messages = [item for item in payload["messages"] if item.get("role") == "tool"]
        self.assertEqual(len(tool_messages), 1)
        content = str(tool_messages[0]["content"])

        self.assertIn("\\u9879\\u76ee\\u6982\\u89c8", content)
        self.assertIn("\\u5feb\\u901f\\u5f00\\u59cb", content)
        self.assertNotIn("truncated", content.lower())

    def test_mcp_list_result_preserves_visible_tool_names_for_followup_selection(self) -> None:
        tool_names = [
            "add_comment_to_pending_review",
            "add_issue_comment",
            "get_file_contents",
            "list_commits",
            "search_code",
        ]
        request = LLMRequest(
            session_id="sess_mcp_tool_names",
            trace_id="trace_mcp_tool_names",
            message="梳理当前仓库结构。",
            agent_id="main",
            requested_tool_name="mcp",
            requested_tool_payload={"action": "list", "query": "github repository file read tools"},
            tool_history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "list", "query": "github repository file read tools"},
                    tool_result={
                        "action": "list",
                        "servers": [
                            {
                                "server_id": "github",
                                "state": "discovered",
                                "tool_count": len(tool_names),
                                "tool_names": tool_names,
                            }
                        ],
                    },
                )
            ],
        )

        messages = build_openai_messages(request)
        tool_content = "\n".join(
            str(item.get("content") or "") for item in messages if item.get("role") == "tool"
        )

        self.assertIn("get_file_contents", tool_content)
        self.assertIn("list_commits", tool_content)
        self.assertIn("search_code", tool_content)
        self.assertNotIn("tool_names_truncated_count", tool_content)

    def test_finalization_retry_for_compaction_rescue_omits_noisy_tool_history_messages(self) -> None:
        request = LLMRequest(
            session_id="sess_finalization_retry_compaction",
            trace_id="trace_finalization_retry_compaction",
            message="在压缩后的上下文里继续执行。",
            agent_id="main",
            request_kind="finalization_retry",
            compact_summary_text=(
                "以下是更早历史压缩出的上下文检查点，只用于理解旧背景。\n\n"
                "当前任务：日报同步告警排查。\n"
                "当前未完成事项：补失败摘要、核对卡片渲染差异、写出下一步动作。"
            ),
            tool_history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "call", "server_id": "github", "tool_name": "get_file_contents"},
                    tool_result={"action": "call", "ok": True, "result_text": "目录浏览结果"},
                )
            ],
            finalization_evidence_ledger=FinalizationEvidenceLedger(
                user_message="在压缩后的上下文里继续执行。",
                tool_call_count=1,
                model_request_count=3,
                requires_result_coverage=False,
                requires_round_trip_report=False,
                items=[
                    FinalizationEvidenceItem(
                        ordinal=1,
                        tool_name="mcp",
                        result_summary="目录浏览结果",
                        required_for_user_request=False,
                    )
                ],
            ),
        )

        messages = build_openai_messages(request)

        self.assertTrue(any(msg["role"] == "system" and "日报同步告警排查" in str(msg["content"]) for msg in messages))
        self.assertFalse(any(msg["role"] == "tool" for msg in messages))
        self.assertFalse(any(msg["role"] == "assistant" and "tool_calls" in msg for msg in messages))

    def test_tool_followup_large_mcp_result_is_trimmed_before_provider_transcript(self) -> None:
        huge_result_text = '{"items":[' + ('{"name":"x","path":"p"},' * 2000) + ']}'
        request = LLMRequest(
            session_id="sess_large_tool_result",
            trace_id="trace_large_tool_result",
            message="继续分析刚刚的 MCP 结果。",
            agent_id="main",
            requested_tool_name="mcp",
            requested_tool_payload={"action": "call", "server_id": "github", "tool_name": "search_code"},
            tool_history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "call", "server_id": "github", "tool_name": "search_code"},
                    tool_result={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "search_code",
                        "ok": True,
                        "result_text": huge_result_text,
                        "content": [{"type": "text", "text": huge_result_text}],
                    },
                )
            ],
        )

        messages = build_openai_messages(request)
        tool_messages = [item for item in messages if item.get("role") == "tool"]

        self.assertEqual(len(tool_messages), 1)
        tool_content = str(tool_messages[0]["content"])
        self.assertLess(len(tool_content), 5000)
        self.assertIn('"server_id": "github"', tool_content)
        self.assertIn('"tool_name": "search_code"', tool_content)
        self.assertIn('"result_text"', tool_content)
        self.assertIn("\\u2026", tool_content)


if __name__ == "__main__":
    unittest.main()
