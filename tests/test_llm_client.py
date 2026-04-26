import unittest

from marten_runtime.runtime.llm_client import (
    FinalizationEvidenceItem,
    FinalizationEvidenceLedger,
    LLMRequest,
)
from marten_runtime.runtime.llm_request_instructions import (
    request_specific_instruction as _request_specific_instruction,
    tool_followup_instruction as _tool_followup_instruction,
)


class LLMClientInstructionTests(unittest.TestCase):
    def _build_request(self, **updates) -> LLMRequest:
        base = LLMRequest(
            session_id="sess_test",
            trace_id="trace_test",
            message="hello",
            agent_id="main",
            app_id="main_agent",
            available_tools=[],
        )
        return base.model_copy(update=updates)

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
        self.assertIn("只有当前消息再次明确要求会话目录时，才调用 session.list", runtime_instruction)
        self.assertNotIn("先调用 `runtime`", runtime_instruction)
        self.assertNotIn("先调用 `time`", time_instruction)

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

    def test_request_specific_instruction_adds_finalization_retry_guardrails(
        self,
    ) -> None:
        request = self._build_request(
            request_kind="finalization_retry",
            channel_protocol_instruction_text="保持 Feishu 最终回复结构稳定。",
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
        self.assertIn("current-turn evidence ledger", instruction.lower())
        self.assertIn("required evidence", instruction.lower())

    def test_request_specific_instruction_adds_contract_repair_guardrails(self) -> None:
        request = self._build_request(
            request_kind="contract_repair",
            invalid_final_text="已受理，子 agent 正在后台执行，完成后会通知你结果。",
            available_tools=["spawn_subagent"],
        )

        instruction = _request_specific_instruction(request) or ""

        self.assertIn("上一条回复已经直接结束，但这轮仍未满足运行时合同", instruction)
        self.assertIn("保持用户明确要求的执行模式", instruction)
        self.assertIn("需要工具时，直接发起当前最合适的工具调用", instruction)
        self.assertIn("不要重复上一条无效回复", instruction)
        self.assertIn("上一条无效回复", instruction)
        self.assertNotIn("list_commits", instruction)

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
        self.assertNotIn("session.new", instruction)

    def test_request_specific_instruction_maps_resume_wording_to_session_resume(
        self,
    ) -> None:
        request = self._build_request(
            message="恢复之前的会话",
            available_tools=["session"],
        )

        instruction = _request_specific_instruction(request) or ""
        self.assertIn("finalize_response=true", instruction)
        self.assertNotIn("session.resume", instruction)

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
        self.assertNotIn("spawn_subagent", instruction)

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

    def test_tool_followup_instruction_for_spawn_subagent_blocks_duplicate_acceptance_calls(
        self,
    ) -> None:
        instruction = _tool_followup_instruction("spawn_subagent") or ""

        self.assertIn("已经拿到了刚刚这次 spawn_subagent 的接受结果", instruction)
        self.assertIn("不要再次调用 spawn_subagent 只为了补 finalize_response", instruction)
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


if __name__ == "__main__":
    unittest.main()
