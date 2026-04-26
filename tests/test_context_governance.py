import unittest

from marten_runtime.runtime.context import assemble_runtime_context
from marten_runtime.session.models import SessionMessage
from marten_runtime.tools.registry import ToolSnapshot


class ContextGovernanceRegressionTests(unittest.TestCase):
    def test_long_dialogue_keeps_constraints_results_and_next_steps(self) -> None:
        noisy_result = (
            "工具执行日志：" + "步骤;" * 60 + " 结论: 已定位问题在 bootstrap_handlers requested_agent_id 入站链路缺失。"
        )
        history = [
            SessionMessage.user("请始终用中文回复，不要修改 README。"),
            SessionMessage.assistant("收到。"),
            SessionMessage.user("先排查多 agent routing。"),
            SessionMessage.assistant(noisy_result),
            SessionMessage.user("下一步：补 gateway 测试并打通 requested_agent_id。"),
            SessionMessage.assistant("最近决策：先补 gateway 测试，再改入站模型。"),
            SessionMessage.user("注意风险：不要把项目做成 orchestration 平台。"),
            SessionMessage.assistant("我会保持 harness-thin。"),
            SessionMessage.user("现在继续修复 A/B MVP。"),
        ]

        context = assemble_runtime_context(
            session_id="sess_long_governance",
            current_message="现在继续修复 A/B MVP。",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=4,
        )

        replay_texts = [item.content for item in context.conversation_messages]
        self.assertEqual(
            replay_texts,
            [
                "请始终用中文回复，不要修改 README。",
                "收到。",
                "先排查多 agent routing。",
                "下一步：补 gateway 测试并打通 requested_agent_id。",
                "最近决策：先补 gateway 测试，再改入站模型。",
                "注意风险：不要把项目做成 orchestration 平台。",
                "我会保持 harness-thin。",
            ],
        )
        self.assertNotIn(noisy_result, replay_texts)
        self.assertIn("不要修改 README", "\n".join(context.working_context.get("user_constraints", [])))
        self.assertIn("bootstrap_handlers", "\n".join(context.working_context.get("recent_results", [])))
        self.assertIn("下一步", "\n".join(context.working_context.get("open_todos", [])))
        self.assertIn("orchestration 平台", "\n".join(context.working_context.get("pending_risks", [])))
        self.assertIn("关键结果", context.working_context_text or "")
        self.assertIn("风险/注意点", context.working_context_text or "")


if __name__ == "__main__":
    unittest.main()
