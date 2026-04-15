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

    def test_request_specific_instruction_keeps_runtime_and_time_guidance_live_but_not_payload_shaped(
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

        self.assertIn("实时上下文查询", runtime_instruction)
        self.assertIn("runtime", runtime_instruction)
        self.assertNotIn("action=context_status", runtime_instruction)
        self.assertNotIn("{", runtime_instruction)
        self.assertIn("实时当前时间查询", time_instruction)
        self.assertIn("当前时间", time_instruction)
        self.assertNotIn("{", time_instruction)

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

    def test_tool_followup_instruction_keeps_mcp_on_exact_server_and_tool_surface(self) -> None:
        instruction = _tool_followup_instruction("mcp") or ""

        self.assertIn("精确 server_id", instruction)
        self.assertIn("精确 tool_name", instruction)
        self.assertIn("arguments", instruction)
        self.assertIn("不要自造别名", instruction)


if __name__ == "__main__":
    unittest.main()
