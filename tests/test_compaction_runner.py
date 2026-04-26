import unittest

from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.session.compaction_prompt import build_compaction_prompt, render_compact_summary_block
from marten_runtime.session.compaction_runner import run_compaction
from marten_runtime.session.models import SessionMessage


class CompactionRunnerTests(unittest.TestCase):
    def test_compaction_prompt_preserves_user_checkpoint_contract(self) -> None:
        prompt = build_compaction_prompt(prompt_mode="context_pressure")

        self.assertIn("上下文检查点压缩", prompt)
        self.assertIn("当前进展以及已做出的关键决策", prompt)
        self.assertIn("帮助后续模型无缝继续当前任务", prompt)

    def test_compaction_prompt_adds_runtime_boundary_guardrails(self) -> None:
        prompt = build_compaction_prompt(prompt_mode="context_pressure")

        self.assertIn("不是用来替换 system prompt、skill 描述、MCP 工具描述或 app/bootstrap 提示词", prompt)
        self.assertIn("不是下一轮行动菜单", prompt)
        self.assertIn("不要写“建议下一步 / 优先做 / 可以先做三件事”", prompt)

    def test_history_summary_compaction_prompt_uses_historical_summary_language(self) -> None:
        prompt = build_compaction_prompt(prompt_mode="history_summary")

        self.assertIn("历史摘要", prompt)
        self.assertIn("为未来恢复这个会话的 LLM 创建一份历史摘要", prompt)
        self.assertIn("不是因为上下文窗口压力触发的压缩", prompt)

    def test_rendered_compact_summary_block_is_stable_and_concise(self) -> None:
        rendered = render_compact_summary_block("当前进展：已完成 A。")

        self.assertIn("以下是更早历史的摘要", rendered)
        self.assertIn("当前这条用户消息优先级最高", rendered)
        self.assertIn("当前进展：已完成 A。", rendered)

    def test_compaction_runner_returns_compacted_context_from_summary_text(self) -> None:
        llm = ScriptedLLMClient([LLMReply(final_text="当前进展：已完成 A。\n明确下一步：继续 B。")])

        compacted = run_compaction(
            llm=llm,
            session_id="sess_1",
            current_message="继续 B",
            session_messages=[
                SessionMessage.system("created"),
                SessionMessage.user("任务 A"),
                SessionMessage.assistant("A 完成"),
                SessionMessage.user("任务 B"),
                SessionMessage.assistant("B 完成"),
                SessionMessage.user("任务 C"),
                SessionMessage.assistant("C 完成"),
                SessionMessage.user("任务 D"),
                SessionMessage.assistant("D 完成"),
                SessionMessage.user("任务 E"),
                SessionMessage.assistant("E 完成"),
                SessionMessage.user("任务 F"),
                SessionMessage.assistant("F 完成"),
                SessionMessage.user("任务 G"),
                SessionMessage.assistant("G 完成"),
                SessionMessage.user("任务 H"),
                SessionMessage.assistant("H 完成"),
                SessionMessage.user("任务 I"),
                SessionMessage.assistant("I 完成"),
                SessionMessage.user("继续 B"),
            ],
            preserved_tail_user_turns=8,
            prompt_mode="history_summary",
            trigger_kind=None,
        )

        self.assertIsNotNone(compacted)
        assert compacted is not None
        self.assertIn("当前进展", compacted.summary_text)
        self.assertEqual(compacted.source_message_range, [0, 3])
        self.assertEqual(compacted.preserved_tail_user_turns, 8)
        self.assertIsNone(compacted.trigger_kind)
        self.assertIn("历史摘要", llm.requests[0].system_prompt or "")
        self.assertEqual(
            [item.content for item in llm.requests[0].conversation_messages],
            ["任务 A", "A 完成"],
        )

    def test_compaction_runner_handles_compaction_failure_without_state_corruption(self) -> None:
        llm = ScriptedLLMClient([LLMReply(final_text="")])

        compacted = run_compaction(
            llm=llm,
            session_id="sess_2",
            current_message="继续",
            session_messages=[
                SessionMessage.user("历史 1"),
                SessionMessage.assistant("历史 1 完成"),
                SessionMessage.user("历史 2"),
                SessionMessage.assistant("历史 2 完成"),
                SessionMessage.user("继续"),
            ],
        )

        self.assertIsNone(compacted)

    def test_compaction_runner_skips_when_replayable_user_turns_fit_preserved_tail(self) -> None:
        llm = ScriptedLLMClient([LLMReply(final_text="should not compact")])

        compacted = run_compaction(
            llm=llm,
            session_id="sess_small",
            current_message="继续",
            session_messages=[
                SessionMessage.user("历史 1"),
                SessionMessage.assistant("历史 1 完成"),
                SessionMessage.user("历史 2"),
                SessionMessage.assistant("历史 2 完成"),
                SessionMessage.user("继续"),
            ],
            preserved_tail_user_turns=8,
        )

        self.assertIsNone(compacted)
        self.assertEqual(len(llm.requests), 0)
