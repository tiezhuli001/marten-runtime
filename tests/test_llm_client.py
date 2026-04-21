import unittest

from marten_runtime.runtime.llm_client import (
    LLMRequest,
    _request_specific_instruction,
    _tool_followup_instruction,
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

        self.assertIsNone(instruction)

    def test_request_specific_instruction_does_not_add_github_metadata_specific_steering(
        self,
    ) -> None:
        request = self._build_request(
            message="请用 github mcp 看一下 https://github.com/CloudWide851/easy-agent 这个仓库的默认分支、描述和语言",
            available_tools=["mcp"],
        )

        instruction = _request_specific_instruction(request)

        self.assertIsNone(instruction)

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

        self.assertIn("实时", runtime_instruction)
        self.assertIn("runtime", runtime_instruction)
        self.assertIn("当前时间", time_instruction)
        self.assertIn("请先", time_instruction)

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

        self.assertIn("会话目录/活跃会话查询", instruction)
        self.assertIn("优先使用 session family tool", instruction)
        self.assertIn("只有当用户明确提到定时任务", instruction)

    def test_request_specific_instruction_prefers_automation_for_cron_queries(self) -> None:
        request = self._build_request(
            message="当前有哪些定时任务？",
            available_tools=["session", "automation"],
        )

        instruction = _request_specific_instruction(request) or ""

        self.assertIn("定时任务/自动化查询", instruction)
        self.assertIn("优先使用 automation family tool", instruction)

    def test_request_specific_instruction_maps_new_session_switch_wording_to_session_new(
        self,
    ) -> None:
        request = self._build_request(
            message="切换到新会话",
            available_tools=["session", "automation"],
        )

        instruction = _request_specific_instruction(request) or ""

        self.assertIn("显式会话切换请求", instruction)
        self.assertIn("session", instruction)
        self.assertIn("new 或 resume", instruction)

    def test_request_specific_instruction_maps_resume_wording_to_session_resume(
        self,
    ) -> None:
        request = self._build_request(
            message="恢复之前的会话",
            available_tools=["session"],
        )

        instruction = _request_specific_instruction(request) or ""

        self.assertIn("显式会话切换请求", instruction)
        self.assertIn("session", instruction)
        self.assertIn("new 或 resume", instruction)

    def test_tool_followup_instruction_keeps_mcp_on_exact_server_and_tool_surface(self) -> None:
        instruction = _tool_followup_instruction("mcp") or ""

        self.assertIn("精确 server_id", instruction)
        self.assertIn("精确 tool_name", instruction)
        self.assertIn("arguments", instruction)
        self.assertIn("不要自造别名", instruction)

    def test_tool_followup_instruction_for_skill_prevents_reloading_same_skill_body(
        self,
    ) -> None:
        instruction = _tool_followup_instruction("skill") or ""

        self.assertIn("已经加载了刚刚那个 skill 正文", instruction)
        self.assertIn("不要重复调用 skill 去再次加载同一个 skill", instruction)

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
