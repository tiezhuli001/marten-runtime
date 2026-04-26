import unittest

from marten_runtime.runtime.context import assemble_runtime_context
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.tools.registry import ToolSnapshot


class RuntimeContextTests(unittest.TestCase):
    def test_assembler_replays_durable_feishu_detail_from_assistant_history(self) -> None:
        history = [
            SessionMessage.user("请汇总检查结果"),
            SessionMessage.assistant("检查完成。\n\n共 2 项\n\n- builtin 正常\n- mcp 正常"),
            SessionMessage.user("刚才 mcp 的结果是什么？"),
        ]

        context = assemble_runtime_context(
            session_id="sess_feishu_durable",
            current_message="刚才 mcp 的结果是什么？",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
        )

        self.assertEqual(
            [item.content for item in context.conversation_messages],
            ["请汇总检查结果", "检查完成。\n\n共 2 项\n\n- builtin 正常\n- mcp 正常"],
        )
        self.assertIn("mcp 正常", context.conversation_messages[-1].content)

    def test_assembler_replays_recent_session_messages_without_current_user_message(self) -> None:
        history = [
            SessionMessage.system("created"),
            SessionMessage.user("first question"),
            SessionMessage.assistant("first answer"),
            SessionMessage.user("current question"),
        ]

        context = assemble_runtime_context(
            session_id="sess_1",
            current_message="current question",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            skill_snapshot=SkillSnapshot(skill_snapshot_id="skill_1"),
            activated_skill_ids=["skill_a"],
        )

        self.assertEqual([item.role for item in context.conversation_messages], ["user", "assistant"])
        self.assertEqual([item.content for item in context.conversation_messages], ["first question", "first answer"])
        self.assertEqual(context.working_context["active_goal"], "current question")
        self.assertEqual(context.context_snapshot_id, "ctx_sess_1")
        self.assertEqual(context.skill_snapshot.skill_snapshot_id, "skill_1")
        self.assertEqual(context.activated_skill_ids, ["skill_a"])

    def test_assembler_limits_replay_to_recent_user_turns(self) -> None:
        history = [
            SessionMessage.user("u1"),
            SessionMessage.assistant("a1"),
            SessionMessage.user("u2"),
            SessionMessage.assistant("a2"),
            SessionMessage.user("u3"),
            SessionMessage.assistant("a3"),
            SessionMessage.user("u4"),
        ]

        context = assemble_runtime_context(
            session_id="sess_2",
            current_message="u4",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=2,
        )

        self.assertEqual(
            [item.content for item in context.conversation_messages],
            ["u2", "a2", "u3", "a3"],
        )
        self.assertIn("continuation_hint", context.working_context)

    def test_assembler_preserves_earlier_user_constraints_in_working_context(self) -> None:
        history = [
            SessionMessage.user("请始终用中文回复，并且不要改 README。"),
            SessionMessage.assistant("收到，我会用中文并避免改 README。"),
            SessionMessage.user("先检查 runtime loop。"),
            SessionMessage.assistant("我先看 runtime loop 和 context assembly。"),
            SessionMessage.user("现在继续修复 agent routing"),
        ]

        context = assemble_runtime_context(
            session_id="sess_constraints",
            current_message="现在继续修复 agent routing",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
        )

        self.assertIn("请始终用中文回复", "\n".join(context.working_context.get("user_constraints", [])))
        self.assertIn("不要改 README", "\n".join(context.working_context.get("user_constraints", [])))
        self.assertIn("用户约束", context.working_context_text or "")

    def test_assembler_drops_orphaned_user_turn_when_noisy_assistant_reply_is_trimmed(self) -> None:
        noisy_reply = "工具执行日志：" + "步骤;" * 40 + " 结论：上一轮误把请求路由到了 GitHub 热榜。"
        history = [
            SessionMessage.user("排查上一轮为什么会误查 GitHub 热榜"),
            SessionMessage.assistant(noisy_reply),
            SessionMessage.user("当前上下文窗口多大？"),
        ]

        context = assemble_runtime_context(
            session_id="sess_orphan",
            current_message="当前上下文窗口多大？",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=1,
        )

        self.assertEqual(context.conversation_messages, [])
        self.assertEqual(context.working_context["active_goal"], "当前上下文窗口多大？")

    def test_assembler_prefers_compacted_result_over_noisy_assistant_transcript(self) -> None:
        noisy_result = (
            "工具执行日志：" + "步骤;" * 80 + " 结论: 已定位问题在 bootstrap_handlers requested_agent_id 入站链路缺失。"
        )
        history = [
            SessionMessage.user("帮我排查 agent routing 问题"),
            SessionMessage.assistant(noisy_result),
            SessionMessage.user("记住刚才定位到的问题，继续修复"),
        ]

        context = assemble_runtime_context(
            session_id="sess_noise",
            current_message="记住刚才定位到的问题，继续修复",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=4,
        )

        self.assertNotIn(noisy_result, [item.content for item in context.conversation_messages])
        self.assertIn("bootstrap_handlers", "\n".join(context.working_context.get("recent_results", [])))
        self.assertIn("关键结果", context.working_context_text or "")

    def test_assembler_renders_structured_working_context_text(self) -> None:
        history = [
            SessionMessage.user("请始终用中文回复"),
            SessionMessage.assistant("好的。"),
            SessionMessage.user("当前目标：完成 A/B 两个阶段"),
        ]

        context = assemble_runtime_context(
            session_id="sess_render",
            current_message="当前目标：完成 A/B 两个阶段",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
        )

        self.assertNotIn("- active_goal:", context.working_context_text or "")
        self.assertIn("当前目标", context.working_context_text or "")
        self.assertIn("用户约束", context.working_context_text or "")

    def test_assembler_defaults_to_eight_recent_user_turns(self) -> None:
        history: list[SessionMessage] = []
        for turn in range(1, 11):
            history.append(SessionMessage.user(f"u{turn}"))
            if turn < 10:
                history.append(SessionMessage.assistant(f"a{turn}"))

        context = assemble_runtime_context(
            session_id="sess_default_turn_budget",
            current_message="u10",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
        )

        self.assertEqual(
            [item.content for item in context.conversation_messages],
            [
                "u2",
                "a2",
                "u3",
                "a3",
                "u4",
                "a4",
                "u5",
                "a5",
                "u6",
                "a6",
                "u7",
                "a7",
                "u8",
                "a8",
                "u9",
                "a9",
            ],
        )

    def test_assembler_uses_compact_summary_plus_recent_tail(self) -> None:
        history = [
            SessionMessage.user("第 1 轮：先检查 runtime loop"),
            SessionMessage.assistant("第 1 轮完成：检查了 runtime loop"),
            SessionMessage.user("第 2 轮：再看 bootstrap handlers"),
            SessionMessage.assistant("第 2 轮完成：检查了 bootstrap handlers"),
            SessionMessage.user("第 3 轮：保留最近尾部"),
            SessionMessage.assistant("第 3 轮完成：准备继续"),
            SessionMessage.user("当前问题"),
        ]

        compacted = CompactedContext(
            compact_id="cmp_1",
            session_id="sess_compact",
            summary_text="当前进展：已检查 runtime loop 与 bootstrap handlers。",
            source_message_range=[0, 4],
            preserved_tail_user_turns=2,
        )

        context = assemble_runtime_context(
            session_id="sess_compact",
            current_message="当前问题",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=2,
            compacted_context=compacted,
        )

        self.assertIn("当前进展", context.compact_summary_text or "")
        self.assertEqual(
            [item.content for item in context.conversation_messages],
            ["第 3 轮：保留最近尾部", "第 3 轮完成：准备继续"],
        )
        self.assertNotIn("第 1 轮：先检查 runtime loop", [item.content for item in context.conversation_messages])


    def test_assembler_post_compact_does_not_rederive_old_prefix_into_working_context(self) -> None:
        history = [
            SessionMessage.user("旧约束：不要改 system prompt"),
            SessionMessage.assistant("结果: 旧阶段已经完成，并且定位到了历史问题。"),
            SessionMessage.user("最近消息：保留尾部"),
            SessionMessage.assistant("最近结果：继续处理尾部任务"),
            SessionMessage.user("继续"),
        ]

        compacted = CompactedContext(
            compact_id="cmp_3",
            session_id="sess_compact_3",
            summary_text="当前进展：旧阶段已经完成；约束：不要改 system prompt。",
            source_message_range=[0, 2],
            preserved_tail_user_turns=2,
        )

        context = assemble_runtime_context(
            session_id="sess_compact_3",
            current_message="继续",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=2,
            compacted_context=compacted,
        )

        self.assertIn("当前进展", context.compact_summary_text or "")
        self.assertNotIn("旧阶段已经完成", context.working_context_text or "")
        self.assertIn("最近结果", context.working_context_text or "")

    def test_assembler_does_not_replay_compacted_prefix_verbatim(self) -> None:
        history = [
            SessionMessage.user("旧前缀 1"),
            SessionMessage.assistant("旧前缀 1 完成"),
            SessionMessage.user("旧前缀 2"),
            SessionMessage.assistant("旧前缀 2 完成"),
            SessionMessage.user("最近消息"),
            SessionMessage.assistant("最近回复"),
            SessionMessage.user("继续"),
        ]

        compacted = CompactedContext(
            compact_id="cmp_2",
            session_id="sess_compact_2",
            summary_text="关键摘要：前两轮已完成。",
            source_message_range=[0, 4],
            preserved_tail_user_turns=3,
        )

        context = assemble_runtime_context(
            session_id="sess_compact_2",
            current_message="继续",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=3,
            compacted_context=compacted,
        )

        replay_texts = [item.content for item in context.conversation_messages]
        self.assertNotIn("旧前缀 1", replay_texts)
        self.assertNotIn("旧前缀 2", replay_texts)
        self.assertIn("最近消息", replay_texts)
        self.assertIn("最近回复", replay_texts)

    def test_assembler_preserves_assistant_reply_for_selected_user_turn_window(self) -> None:
        history = [
            SessionMessage.user("u1"),
            SessionMessage.assistant("a1"),
            SessionMessage.user("u2"),
            SessionMessage.assistant("a2"),
            SessionMessage.user("u3"),
            SessionMessage.assistant("a3"),
            SessionMessage.user("u4"),
            SessionMessage.assistant("a4"),
            SessionMessage.user("u5"),
        ]

        context = assemble_runtime_context(
            session_id="sess_turn_window",
            current_message="u5",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=3,
        )

        self.assertEqual(
            [item.content for item in context.conversation_messages],
            ["u2", "a2", "u3", "a3", "u4", "a4"],
        )

    def test_assembler_uses_replay_default_when_compacted_tail_width_is_absent(self) -> None:
        history = [
            SessionMessage.user("旧前缀"),
            SessionMessage.assistant("旧前缀完成"),
            SessionMessage.user("最近 1"),
            SessionMessage.assistant("最近 1 完成"),
            SessionMessage.user("最近 2"),
            SessionMessage.assistant("最近 2 完成"),
            SessionMessage.user("继续"),
        ]

        compacted = CompactedContext(
            compact_id="cmp_default_tail",
            session_id="sess_default_tail",
            summary_text="当前进展：旧前缀已压缩。",
            source_message_range=[0, 2],
        )

        context = assemble_runtime_context(
            session_id="sess_default_tail",
            current_message="继续",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=1,
            compacted_context=compacted,
        )

        self.assertEqual(
            [item.content for item in context.conversation_messages],
            ["最近 2", "最近 2 完成"],
        )

    def test_assembler_expands_modern_replay_window_beyond_checkpoint_tail_when_config_increases(self) -> None:
        history = [
            SessionMessage.user("u1"),
            SessionMessage.assistant("a1"),
            SessionMessage.user("u2"),
            SessionMessage.assistant("a2"),
            SessionMessage.user("u3"),
            SessionMessage.assistant("a3"),
            SessionMessage.user("u4"),
            SessionMessage.assistant("a4"),
            SessionMessage.user("继续"),
        ]

        compacted = CompactedContext(
            compact_id="cmp_modern_expand",
            session_id="sess_modern_expand",
            summary_text="当前进展：旧历史已压缩。",
            source_message_range=[0, 6],
            preserved_tail_user_turns=1,
        )

        context = assemble_runtime_context(
            session_id="sess_modern_expand",
            current_message="继续",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=3,
            compacted_context=compacted,
        )

        self.assertEqual(
            [item.content for item in context.conversation_messages],
            ["u2", "a2", "u3", "a3", "u4", "a4"],
        )

    def test_assembler_rebases_compact_summary_when_replay_window_expands_beyond_checkpoint_tail(
        self,
    ) -> None:
        history = [
            SessionMessage.user("u1"),
            SessionMessage.assistant("a1"),
            SessionMessage.user("u2"),
            SessionMessage.assistant("a2"),
            SessionMessage.user("u3"),
            SessionMessage.assistant("a3"),
            SessionMessage.user("u4"),
            SessionMessage.assistant("a4"),
            SessionMessage.user("继续"),
        ]

        compacted = CompactedContext(
            compact_id="cmp_overlap_guard",
            session_id="sess_overlap_guard",
            summary_text="当前进展：旧历史已压缩。",
            source_message_range=[0, 6],
            preserved_tail_user_turns=1,
        )

        context = assemble_runtime_context(
            session_id="sess_overlap_guard",
            current_message="继续",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=3,
            compacted_context=compacted,
        )

        self.assertEqual(
            [item.content for item in context.conversation_messages],
            ["u2", "a2", "u3", "a3", "u4", "a4"],
        )
        self.assertIn("当前进展：旧历史已压缩。", context.compact_summary_text or "")
        self.assertIn("u1", context.compact_summary_text or "")
        self.assertIn("a1", context.compact_summary_text or "")
        self.assertNotIn("u2", context.compact_summary_text or "")
        self.assertIn("当前这条用户消息优先级最高", context.compact_summary_text or "")
        self.assertIn("补充说明", context.compact_summary_text or "")
        self.assertIn("更早的用户轮次", context.compact_summary_text or "")
        self.assertIn("更早的助手进展", context.compact_summary_text or "")

    def test_runtime_context_injects_tool_outcome_summary_text_without_replaying_tool_transcript(self) -> None:
        history = [
            SessionMessage.user("先查一下 repo"),
            SessionMessage.assistant("已经查了 repo。"),
            SessionMessage.user("继续基于刚才的工具结果往下做"),
        ]

        context = assemble_runtime_context(
            session_id="sess_tool_summary",
            current_message="继续基于刚才的工具结果往下做",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            recent_tool_outcome_summaries=[
                {
                    "source_kind": "mcp",
                    "summary_text": "上一轮通过 github MCP 查询了 repo=openai/codex，branch=main，issue_count=12。",
                    "keep_next_turn": True,
                }
            ],
        )

        self.assertIn("只有当前消息明确承接上一轮结果时才参考", context.tool_outcome_summary_text or "")
        self.assertIn("repo=openai/codex", context.tool_outcome_summary_text or "")
        self.assertEqual(
            [item.content for item in context.conversation_messages],
            ["先查一下 repo", "已经查了 repo。"],
        )

    def test_assembler_keeps_legitimate_long_assistant_reply_for_explicit_followup(self) -> None:
        long_reply = (
            "定位结果如下：\n"
            "1. session.list 的 finalize_response 依赖模型显式声明。\n"
            "2. 当前会话列表丢失来自最终答复没有走 direct render 合同。\n"
            "```python\nprint('keep this context')\n```\n"
            "下一步应收紧 prompt。"
        )
        history = [
            SessionMessage.user("先分析会话列表为什么没出来"),
            SessionMessage.assistant(long_reply),
            SessionMessage.user("基于刚才第二点继续修"),
        ]

        context = assemble_runtime_context(
            session_id="sess_long_followup",
            current_message="基于刚才第二点继续修",
            system_prompt="You are marten-runtime.",
            session_messages=history,
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            replay_user_turns=1,
        )

        self.assertEqual(
            [item.content for item in context.conversation_messages],
            ["先分析会话列表为什么没出来", long_reply],
        )

    def test_runtime_context_injects_capped_memory_text(self) -> None:
        context = assemble_runtime_context(
            session_id="sess_memory",
            current_message="继续当前任务",
            system_prompt="You are marten-runtime.",
            session_messages=[SessionMessage.user("继续当前任务")],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            memory_text="User memory:\n# MEMORY\n## preferences\n- Prefer concise answers.",
        )

        self.assertIn("User memory:", context.memory_text or "")
        self.assertIn("preferences", context.memory_text or "")


if __name__ == "__main__":
    unittest.main()
