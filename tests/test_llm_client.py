import unittest

from marten_runtime.runtime.finalization_contract_prompt import (
    render_finalization_contract_block,
    render_finalization_contract_instruction,
)
from marten_runtime.runtime.llm_client import (
    DemoLLMClient,
    FinalizationEvidenceItem,
    FinalizationEvidenceLedger,
    LLMReply,
    LLMRequest,
    ScriptedLLMClient,
)
from marten_runtime.runtime.llm_message_support import build_openai_chat_payload
from marten_runtime.runtime.llm_request_instructions import (
    request_specific_instruction as _request_specific_instruction,
    tool_followup_instruction as _tool_followup_instruction,
)
from marten_runtime.runtime.recovery_flow import assess_finalization_text
from marten_runtime.tools.registry import ToolSnapshot
from marten_runtime.runtime.capabilities import get_capability_declarations


class LLMClientInstructionTests(unittest.TestCase):
    def _build_request(self, **updates) -> LLMRequest:
        base = LLMRequest(
            session_id="sess_test",
            trace_id="trace_test",
            message="hello",
            agent_id="main",
            available_tools=[],
        )
        return base.model_copy(update=updates)


    def test_memory_tool_provider_schema_uses_basic_required_shape(self) -> None:
        declarations = get_capability_declarations()
        memory_schema = declarations["memory"].parameters_schema
        request = self._build_request(
            available_tools=["memory"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_memory",
                builtin_tools=["memory"],
                tool_metadata={"memory": {"parameters_schema": memory_schema}},
            ),
        )

        payload = build_openai_chat_payload("gpt-test", request)
        provider_schema = payload["tools"][0]["function"]["parameters"]

        self.assertEqual(provider_schema["required"], ["action"])
        self.assertNotIn("allOf", provider_schema)
        self.assertNotIn("if", provider_schema)
        self.assertNotIn("then", provider_schema)


    def test_provider_schema_preserves_non_memory_composition_keywords(self) -> None:
        custom_schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["one"]},
                "target": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            },
            "required": ["action"],
            "oneOf": [
                {"required": ["target"]},
                {"required": ["action"]},
            ],
        }
        request = self._build_request(
            available_tools=["custom"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_custom",
                builtin_tools=["custom"],
                tool_metadata={"custom": {"parameters_schema": custom_schema}},
            ),
        )

        payload = build_openai_chat_payload("gpt-test", request)
        provider_schema = payload["tools"][0]["function"]["parameters"]

        self.assertIn("oneOf", provider_schema)
        self.assertIn("oneOf", provider_schema["properties"]["target"])

    def test_request_specific_instruction_does_not_add_github_commit_specific_steering(
        self,
    ) -> None:
        request = self._build_request(
            message="请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库最近一次提交是什么时候？",
            available_tools=["mcp"],
        )

        instruction = _request_specific_instruction(request)

        self.assertIn("finalize_response=true", instruction or "")
        self.assertNotIn("list_commits", instruction or "")
        self.assertNotIn("search_repositories", instruction or "")

    def test_request_specific_instruction_does_not_add_github_metadata_specific_steering(
        self,
    ) -> None:
        request = self._build_request(
            message="请用 github mcp 看一下 https://github.com/CloudWide851/easy-agent 这个仓库的默认分支、描述和语言",
            available_tools=["mcp"],
        )

        instruction = _request_specific_instruction(request)

        self.assertIn("finalize_response=true", instruction or "")
        self.assertNotIn("default_branch", instruction or "")
        self.assertNotIn("search_repositories", instruction or "")

    def test_request_specific_instruction_does_not_reintroduce_runtime_or_time_specific_hardening(
        self,
    ) -> None:
        runtime_request = self._build_request(
            message="当前上下文的具体使用详情是什么？",
            available_tools=["runtime"],
        )
        time_request = self._build_request(
            message="请告诉我现在几点了？",
            available_tools=["time"],
        )

        runtime_instruction = _request_specific_instruction(runtime_request) or ""
        time_instruction = _request_specific_instruction(time_request) or ""

        self.assertIn("finalize_response=true", runtime_instruction)
        self.assertIn("finalize_response=true", time_instruction)
        self.assertIn("当前用户最新一条消息定义本轮任务边界", runtime_instruction)
        self.assertIn("未来任务锚点", runtime_instruction)
        self.assertIn("不要声称没有任务上下文", runtime_instruction)
        self.assertIn("只有当前消息再次明确要求会话目录时，才调用 session.list", runtime_instruction)
        self.assertIn("当前时间/日期/datetime", time_instruction)
        self.assertIn("只有拿到本轮 time 工具结果后", time_instruction)
        self.assertIn("当前时间问题仍然需要本轮 time 工具结果", time_instruction)
        self.assertIn("time 工具结果", time_instruction)
        self.assertIn("当前上下文窗口/token/压缩状态", runtime_instruction)
        self.assertIn("只有拿到本轮 runtime 工具结果后", runtime_instruction)
        self.assertIn("当前上下文窗口问题仍然需要本轮 runtime 工具结果", runtime_instruction)
        self.assertIn("runtime 工具结果", runtime_instruction)
        self.assertIn("记住/写入记忆/保存到记忆", runtime_instruction)
        self.assertIn("只有拿到本轮 memory 工具成功结果后", runtime_instruction)
        self.assertIn("显式 记住 / 更新记忆 / 修改记忆 仍然需要本轮 memory 工具成功结果", runtime_instruction)
        self.assertIn("memory.replace(section=preferences)", runtime_instruction)
        self.assertIn("source_excerpt", runtime_instruction)
        self.assertIn("scope、type、section 与 content", runtime_instruction)
        self.assertIn("type 由模型根据当前用户意图选择", runtime_instruction)
        self.assertIn("主机只校验字段和持久化", runtime_instruction)
        self.assertIn("读取当前偏好 / 查看当前偏好 / 读取刚才记住的偏好", runtime_instruction)
        self.assertIn("说明你记住了什么 / 复述刚才记住的内容", runtime_instruction)
        self.assertIn("不要写成 当前记忆已更新 / 已保存 / 已写入", runtime_instruction)
        self.assertIn("不要再次调用 memory", runtime_instruction)
        self.assertIn("同一条长期偏好已经被 replace 更新时", runtime_instruction)
        self.assertIn("不要把旧偏好的措辞、顺序要求或限制混回最终输出", runtime_instruction)
        self.assertIn("子任务完成了吗 / 后台任务进展 / 给我一句摘要 / 它梳理了什么", runtime_instruction)
        self.assertIn("读取现成的后台任务状态", runtime_instruction)
        self.assertIn("不要再次调用 spawn_subagent", runtime_instruction)
        self.assertIn("父会话最终答复要保留摘要里的对象词与关键覆盖名词", runtime_instruction)
        self.assertIn("优先沿用子任务摘要里已经出现的任务对象、文档/模块名称、结构层级、覆盖范围与结论短语", runtime_instruction)
        self.assertIn("让答复继续停留在同一语义层级", runtime_instruction)
        self.assertIn("不要只改写成更抽象的泛化概括", runtime_instruction)
        self.assertNotIn("仓库结构 / README 结构 / 顶层目录 / 主要模块 / 关键配置 / 测试与文档 / 快速开始", runtime_instruction)
        self.assertIn("再开一个子代理", runtime_instruction)
        self.assertIn("收到的话只回两个字", runtime_instruction)
        self.assertIn("不要调用 memory", runtime_instruction)
        self.assertIn("完成新会话切换或恢复旧会话之后", runtime_instruction)
        self.assertIn("当前 turn 只有这种 continuation cue", runtime_instruction)
        self.assertIn("优先输出任务 continuation 或简短继续确认", runtime_instruction)
        self.assertIn("最终答复首句保留同一标签词", runtime_instruction)
        self.assertIn("不要只写泛化的“已准备好继续”“继续当前任务”", runtime_instruction)
        self.assertIn("这类 continuation turn 默认不再调用 session.new / session.resume / session.show / session.list", runtime_instruction)
        self.assertIn("不要改写成当前会话标题、消息数、session_id", runtime_instruction)
        self.assertIn("当已绑定会话里暂时没有足够任务锚点时", runtime_instruction)
        self.assertIn("不要切到 session.show/list，也不要切到 runtime.context_status", runtime_instruction)
        self.assertIn("不要为了判断 resumed session 里有没有足够任务细节而再次调用 session.show/list", runtime_instruction)
        self.assertIn("不要把这类场景重新判成“缺少任务锚点”", runtime_instruction)
        self.assertIn("不要因为历史条数少、摘要短、或只有 1-2 条旧消息", runtime_instruction)
        self.assertIn("不要改去别的工具族", runtime_instruction)
        self.assertIn("先调用 runtime，再回答", runtime_instruction)
        self.assertIn("新开一个会话 这类单一切换请求", runtime_instruction)
        self.assertIn("session.new(finalize_response=true)", runtime_instruction)
        self.assertNotIn("先调用 `runtime`", runtime_instruction)
        self.assertNotIn("先调用 `time`", time_instruction)

    def test_subagent_instruction_requires_first_final_contract_without_case_specific_steering(self) -> None:
        request = self._build_request(
            request_kind="subagent",
            message="梳理这个仓库的模块职责",
            available_tools=["mcp"],
        )

        instruction = _request_specific_instruction(request) or ""

        self.assertIn("Child final replies should stay concise", instruction)
        self.assertIn("End the child final reply with the same finalization_contract block", instruction)
        self.assertIn("exact empty finalization_contract shape", instruction)
        self.assertIn("include the contract in the first final child reply", instruction)
        self.assertIn("one short paragraph or at most 3 bullets", instruction)
        self.assertNotIn("eval", instruction.lower())
        self.assertNotIn("golden", instruction.lower())

    def test_request_specific_instruction_keeps_compaction_continuation_on_task_anchor(self) -> None:
        request = self._build_request(
            message="在压缩后的上下文里继续执行。",
            compact_summary_text=(
                "当前任务：日报同步告警排查。\n"
                "当前未完成事项：补失败摘要、核对卡片渲染差异、写出下一步动作。"
            ),
            available_tools=["session", "runtime", "skill"],
        )

        instruction = _request_specific_instruction(request) or ""

        self.assertIn("在压缩后的上下文里继续执行 / 压缩后继续 / 继续这个长线程任务", instruction)
        self.assertIn("把“上下文 / 长线程 / 当前会话”理解成 continuation cue", instruction)
        self.assertIn("不要把整条长线程改写成“只有压缩/上下文元讨论、实际任务从未执行”", instruction)
        self.assertIn("继续日报同步告警排查", instruction)
        self.assertIn("不要把它误判成 session 元数据查询、runtime 数值查询、或 skill 装载请求", instruction)
        self.assertIn("不要为了确认压缩摘要里的任务锚点而先做工具盘点", instruction)
        self.assertIn("只能使用 Visible skills 里已经出现的精确 skill_id", instruction)
        self.assertIn("只有用户明确要求会话详情、当前会话 id、会话列表、上下文窗口数值或某个 skill 正文时", instruction)

    def test_mcp_followup_instruction_advances_from_discovery_to_visible_call(self) -> None:
        instruction = _tool_followup_instruction(
            "mcp",
            tool_history_count=2,
            has_evidence_ledger=True,
            required_evidence_count=1,
        ) or ""

        self.assertIn("mcp.list/detail is only capability discovery", instruction)
        self.assertIn("After mcp.list/detail exposes a directly relevant visible tool", instruction)
        self.assertIn("advance to a visible mcp.call", instruction)
        self.assertIn("do not repeat inventory as the answer", instruction)

    def test_request_specific_instruction_uses_channel_owned_feishu_guard_text(
        self,
    ) -> None:
        request = self._build_request(
            channel_protocol_instruction_text=(
                "当前回合需要遵守 Feishu 结构化回复协议。若最终答案不是单行直接回答，"
                "必须以且仅以一个尾部 fenced `feishu_card` block 结束；"
            ),
        )

        instruction = _request_specific_instruction(request)

        self.assertIn("Feishu 结构化回复协议", instruction or "")
        self.assertIn("feishu_card", instruction or "")

    def test_finalization_contract_instruction_includes_short_direct_reply_example(self) -> None:
        instruction = render_finalization_contract_instruction()

        self.assertIn("Completion rule:", instruction)
        self.assertIn("A reply without this block is incomplete", instruction)
        self.assertIn("Short direct answers still need the exact empty block", instruction)
        self.assertIn("greetings, acknowledgements, and self-introductions", instruction)
        self.assertIn("首轮直接回答", instruction)
        self.assertIn("自我介绍", instruction)
        self.assertIn("你好。", instruction)
        self.assertIn("我是 marten-runtime 中的主执行代理。", instruction)
        self.assertIn(render_finalization_contract_block(), instruction)

    def test_request_specific_instruction_repeats_finalization_contract_completion_rule_at_end(
        self,
    ) -> None:
        request = self._build_request(
            message="你好",
            available_tools=["session", "runtime", "memory", "time"],
        )

        instruction = _request_specific_instruction(request) or ""
        tail_index = instruction.rfind("Completion rule:")

        self.assertGreater(tail_index, -1)
        self.assertGreater(
            tail_index,
            instruction.rfind("当前用户最新一条消息定义本轮任务边界"),
        )
        self.assertIn("A reply without this block is incomplete", instruction[tail_index:])
        self.assertIn(render_finalization_contract_block(), instruction[tail_index:])

    def test_request_specific_instruction_adds_finalization_retry_guardrails(
        self,
    ) -> None:
        request = self._build_request(
            request_kind="finalization_retry",
            channel_protocol_instruction_text="保持 Feishu 最终回复结构稳定。",
            invalid_final_text="已查看 README 结构，主要章节包括快速开始、离线评测、仓库结构。",
            finalization_evidence_ledger=FinalizationEvidenceLedger(
                user_message="继续整理刚刚的结果",
                tool_call_count=2,
                model_request_count=3,
                requires_result_coverage=True,
                items=[
                    FinalizationEvidenceItem(
                        ordinal=1,
                        tool_name="time",
                        result_summary="现在是 UTC 2026-04-25 10:00",
                        required_for_user_request=True,
                    )
                ],
            ),
        )

        instruction = _request_specific_instruction(request) or ""

        self.assertIn("保持 Feishu 最终回复结构稳定。", instruction)
        self.assertIn("所需的工具结果已经全部提供", instruction)
        self.assertIn("直接基于现有结果生成最终答复", instruction)
        self.assertIn("不要再调用任何工具", instruction)
        self.assertIn("上一条无效回复", instruction)
        self.assertIn("README 结构", instruction)
        self.assertIn("补齐 finalization_contract", instruction)
        self.assertIn("优先沿用这些现成锚点与事实完成答复", instruction)
        self.assertIn("不要把这些探索过程本身写成最终结果", instruction)
        self.assertIn("current-turn evidence ledger", instruction.lower())
        self.assertIn("required evidence", instruction.lower())
        self.assertGreater(
            instruction.rfind("Completion rule:"),
            instruction.rfind("如果这条回复已经包含正确的语义内容"),
        )

    def test_request_specific_instruction_adds_lean_bazi_output_repair(self) -> None:
        request = self._build_request(
            agent_id="bazi",
            request_kind="bazi_output_repair",
            invalid_final_text=(
                "违规项：过三关包含栏目名称，缺少可核验的具体事件。\n"
                "原回复：完整八字分析。"
            ),
            available_tools=[],
        )

        instruction = _request_specific_instruction(request) or ""

        self.assertIn("只修正列出的违规项", instruction)
        self.assertIn("保留其余结论", instruction)
        self.assertIn("不要调用工具", instruction)
        self.assertIn("只输出原回复中待修复的栏目", instruction)
        self.assertIn("过三关包含栏目名称", instruction)

    def test_request_specific_instruction_adds_contract_repair_guardrails(self) -> None:
        request = self._build_request(
            request_kind="contract_repair",
            invalid_final_text="已受理，子 agent 正在后台执行，完成后会通知你结果。",
            available_tools=["spawn_subagent"],
        )

        instruction = _request_specific_instruction(request) or ""

        self.assertIn("上一条回复已经直接结束，但这轮仍未满足运行时合同", instruction)
        self.assertIn("保持用户明确要求的执行模式", instruction)
        self.assertIn("优先直接利用这些现成证据修复答复", instruction)
        self.assertIn("不要把读取说成写入", instruction)
        self.assertIn("不要忽略摘要里的任务锚点", instruction)
        self.assertIn("需要工具时，直接发起当前最合适的工具调用", instruction)
        self.assertIn("不要重复上一条无效回复", instruction)
        self.assertIn("上一条无效回复", instruction)
        self.assertNotIn("list_commits", instruction)

    def test_contract_repair_instruction_repeats_finalization_tail_after_invalid_reply(
        self,
    ) -> None:
        request = self._build_request(
            request_kind="contract_repair",
            invalid_final_text="收到，已记住部署告警排查任务。请提供告警内容或相关日志。",
        )

        instruction = _request_specific_instruction(request) or ""
        invalid_index = instruction.rfind("上一条无效回复")
        tail_index = instruction.rfind("Completion rule:")

        self.assertGreater(invalid_index, -1)
        self.assertGreater(tail_index, invalid_index)
        self.assertIn("A reply without this block is incomplete", instruction[tail_index:])
        self.assertIn(render_finalization_contract_block(), instruction[tail_index:])

    def test_request_specific_instruction_does_not_infer_feishu_guard_from_skill_ids_alone(
        self,
    ) -> None:
        request = self._build_request(
            activated_skill_ids=["feishu_channel_formatting"],
            requested_tool_name="skill",
            requested_tool_payload={"skill_id": "feishu_channel_formatting"},
            tool_result={"skill_id": "feishu_channel_formatting"},
        )

        self.assertNotIn("feishu_card", _request_specific_instruction(request) or "")

    def test_request_specific_instruction_prefers_session_for_active_list_queries(self) -> None:
        request = self._build_request(
            message="当前有哪些活跃列表？",
            available_tools=["session", "automation"],
        )

        instruction = _request_specific_instruction(request) or ""
        self.assertIn("finalize_response=true", instruction)
        self.assertNotIn("automation.list", instruction)

    def test_request_specific_instruction_prefers_automation_for_cron_queries(self) -> None:
        request = self._build_request(
            message="当前有哪些定时任务？",
            available_tools=["session", "automation"],
        )

        instruction = _request_specific_instruction(request) or ""
        self.assertIn("finalize_response=true", instruction)
        self.assertNotIn("automation.list", instruction)

    def test_request_specific_instruction_maps_new_session_switch_wording_to_session_new(
        self,
    ) -> None:
        request = self._build_request(
            message="切换到新会话",
            available_tools=["session", "automation"],
        )

        instruction = _request_specific_instruction(request) or ""
        self.assertIn("finalize_response=true", instruction)
        self.assertNotIn("切换到新会话 -> session.new", instruction)

    def test_request_specific_instruction_maps_resume_wording_to_session_resume(
        self,
    ) -> None:
        request = self._build_request(
            message="恢复之前的会话",
            available_tools=["session"],
        )

        instruction = _request_specific_instruction(request) or ""
        self.assertIn("finalize_response=true", instruction)
        self.assertNotIn("恢复之前的会话 -> session.resume", instruction)

    def test_request_specific_instruction_leaves_explicit_session_resume_to_model(
        self,
    ) -> None:
        request = self._build_request(
            message="切换到sess_dcce8f9c",
            available_tools=["session", "automation"],
        )

        instruction = _request_specific_instruction(request) or ""
        self.assertIn("finalize_response=true", instruction)
        self.assertNotIn("sess_dcce8f9c", instruction)

    def test_request_specific_instruction_leaves_explicit_subagent_request_to_model(
        self,
    ) -> None:
        request = self._build_request(
            message="开启子代理查询 https://github.com/CloudWide851/easy-agent 最近一次提交是什么时候？",
            available_tools=["spawn_subagent", "mcp"],
        )

        instruction = _request_specific_instruction(request) or ""
        self.assertIn("finalize_response=true", instruction)
        self.assertNotIn("https://github.com/CloudWide851/easy-agent", instruction)
        self.assertNotIn("最近一次提交是什么时候", instruction)

    def test_request_specific_instruction_subagent_contract_discourages_nested_dispatch_and_inventory_dump(
        self,
    ) -> None:
        request = self._build_request(
            message="分析这个仓库的 README 结构并给出摘要。",
            request_kind="subagent",
            available_tools=["mcp", "runtime", "time"],
            repository_context_text=(
                "当前运行仓库上下文：\n"
                "- 仓库标识：tiezhuli001/marten-runtime\n"
                "- 仓库地址：https://github.com/tiezhuli001/marten-runtime"
            ),
        )

        instruction = _request_specific_instruction(request) or ""

        self.assertIn("Do not open nested child agents", instruction)
        self.assertIn("current repository context is already attached", instruction)
        self.assertIn("Do not ask the user to repeat owner/repo", instruction)
        self.assertIn("Do not recursively enumerate every directory", instruction)
        self.assertIn("Do not invent MCP tool names", instruction)

    def test_request_specific_instruction_adds_generic_tool_finalization_contract(
        self,
    ) -> None:
        request = self._build_request(
            message="查询会话列表",
            available_tools=["session", "runtime", "mcp"],
        )

        instruction = _request_specific_instruction(request) or ""

        self.assertIn("single-tool terminal turns", instruction)
        self.assertIn("fully satisfy the current turn", instruction)
        self.assertIn("finalize_response=true", instruction)
        self.assertIn("deterministic", instruction)
        self.assertIn("Leave it omitted", instruction)
        self.assertIn("现在有哪些会话列表", instruction)
        self.assertIn("告诉我当前北京时间", instruction)
        self.assertIn("当前上下文窗口和 token 使用详情", instruction)
        self.assertIn("先告诉我当前时间，再查 GitHub 最近提交", instruction)
        self.assertIn("先列出会话列表，再切换到 sess_xxx", instruction)
        self.assertNotIn("先调用 `session`", instruction)

    def test_tool_followup_instruction_keeps_mcp_on_exact_server_and_tool_surface(self) -> None:
        instruction = _tool_followup_instruction(
            "mcp",
            has_evidence_ledger=True,
            required_evidence_count=2,
        ) or ""

        self.assertIn("覆盖用户当前这句消息里的全部直接要求", instruction)
        self.assertIn("精确 server_id", instruction)
        self.assertIn("精确 tool_name", instruction)
        self.assertIn("arguments", instruction)
        self.assertIn("不要自造别名", instruction)
        self.assertIn("直接给出答案并结束", instruction)
        self.assertIn("不要在结尾追加", instruction)
        self.assertIn("current-turn evidence ledger", instruction.lower())
        self.assertIn("required evidence", instruction.lower())

    def test_tool_followup_instruction_for_runtime_stays_grounded_in_current_request(
        self,
    ) -> None:
        instruction = _tool_followup_instruction("runtime") or ""

        self.assertIn("以刚刚返回的 runtime 工具结果为主完成用户当前这句请求", instruction)
        self.assertIn("覆盖用户当前这句消息里的全部直接要求", instruction)
        self.assertIn("如果当前请求还引用了本会话里刚刚得到、且与当前问题直接相关的事实，可以一并回答", instruction)
        self.assertIn("不要额外展开无关的旧任务结果", instruction)
        self.assertIn("不要补做用户当前没有要求的工具查询", instruction)
        self.assertIn("不要在结尾追加", instruction)

    def test_tool_followup_instruction_for_skill_prevents_reloading_same_skill_body(
        self,
    ) -> None:
        instruction = _tool_followup_instruction("skill") or ""

        self.assertIn("已经加载了刚刚那个 skill 正文", instruction)
        self.assertIn("不要重复调用 skill 去再次加载同一个 skill", instruction)
        self.assertIn("最终答复必须服务于用户当前问题", instruction)
        self.assertIn("省略字段名和原始正文包装", instruction)
        self.assertIn("action=...", instruction)
        self.assertIn("body=...", instruction)

    def test_tool_followup_instruction_for_spawn_subagent_blocks_duplicate_acceptance_calls(
        self,
    ) -> None:
        instruction = _tool_followup_instruction("spawn_subagent") or ""

        self.assertIn("已经拿到了刚刚这次 spawn_subagent 的接受结果", instruction)
        self.assertIn("不要再次调用 spawn_subagent 只为了补 finalize_response", instruction)
        self.assertIn("多个不同后台任务", instruction)
        self.assertIn("继续为剩余未派发的任务调用 spawn_subagent", instruction)
        self.assertIn("直接基于这次 accepted/queued/running 结果写最终答复", instruction)

    def test_tool_followup_instruction_requires_continuing_when_tool_result_only_covers_part_of_request(
        self,
    ) -> None:
        instruction = _tool_followup_instruction("session") or ""

        self.assertIn("只覆盖当前请求的一部分", instruction)
        self.assertIn("继续调用仍然需要的工具", instruction)
        self.assertIn("不要把无关或只部分相关的工具结果当成最终答案", instruction)

    def test_tool_followup_instruction_for_multi_step_sequence_forces_round_trip_wording_to_match_history(
        self,
    ) -> None:
        instruction = _tool_followup_instruction("mcp", tool_history_count=3) or ""

        self.assertIn("已经发生多次模型/工具往返", instruction)
        self.assertIn("不要写成单次", instruction)
        self.assertIn("不要写成未发生多次", instruction)

    def test_tool_followup_instruction_for_multi_step_sequence_distinguishes_tool_calls_from_model_requests(
        self,
    ) -> None:
        instruction = _tool_followup_instruction("mcp", tool_history_count=3) or ""

        self.assertIn("当前已发生 3 次工具调用", instruction)
        self.assertIn("你现在正在第 4 次模型请求", instruction)
        self.assertIn("不要把工具调用次数和模型请求次数写成同一个数字概念", instruction)


class ScriptedLLMClientContractNormalizationTests(unittest.TestCase):
    def test_scripted_client_plain_text_keeps_empty_contract_draft(self) -> None:
        request = LLMRequest(
            session_id="sess_test",
            trace_id="trace_test",
            message="what is my session id?",
            agent_id="main",
            available_tools=["session"],
        )
        reply = ScriptedLLMClient(
            [LLMReply(final_text="Current session id: sess_demo123")]
        ).complete(request)

        self.assertEqual(reply.final_text, "Current session id: sess_demo123")
        self.assertIsNone(reply.finalization_contract_draft)
        self.assertEqual(
            assess_finalization_text(
                [],
                reply.final_text or "",
                finalization_contract_draft=reply.finalization_contract_draft,
                enforce_structured_contract=True,
            ),
            "unrecoverable",
        )

    def test_demo_client_plain_echo_keeps_contract_empty_by_default(self) -> None:
        request = LLMRequest(
            session_id="sess_test",
            trace_id="trace_test",
            message="现在几点？",
            agent_id="main",
            available_tools=["time"],
            tool_result={"tool_name": "time", "result_text": "现在是北京时间 2026-05-03 21:37", "iso_time": "2026-05-03T21:37:00+08:00"},
        )

        reply = DemoLLMClient().complete(request)

        self.assertEqual(reply.final_text, "time=2026-05-03T21:37:00+08:00")
        self.assertIsNone(reply.finalization_contract_draft)

    def test_demo_client_can_emit_explicit_empty_contract_when_opted_in(self) -> None:
        request = LLMRequest(
            session_id="sess_test",
            trace_id="trace_test",
            message="hello",
            agent_id="main",
        )

        reply = DemoLLMClient(emit_explicit_empty_contract=True).complete(request)

        self.assertEqual(reply.final_text, "hello")
        self.assertIsNotNone(reply.finalization_contract_draft)


if __name__ == "__main__":
    unittest.main()
