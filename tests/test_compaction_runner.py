import unittest

from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.session.compaction_prompt import build_compaction_prompt, render_compact_summary_block
from marten_runtime.session.compaction_runner import run_compaction
from marten_runtime.session.models import SessionMessage


class CompactionRunnerTests(unittest.TestCase):
    def test_compaction_prompt_preserves_user_checkpoint_contract(self) -> None:
        prompt = build_compaction_prompt()

        self.assertIn("上下文检查点压缩", prompt)
        self.assertIn("当前进展以及已做出的关键决策", prompt)
        self.assertIn("帮助后续模型无缝继续当前任务", prompt)

    def test_compaction_prompt_adds_runtime_boundary_guardrails(self) -> None:
        prompt = build_compaction_prompt()

        self.assertIn("不是用来替换 system prompt、skill 描述、MCP 工具描述或 app/bootstrap 提示词", prompt)

    def test_rendered_compact_summary_block_is_stable_and_concise(self) -> None:
        rendered = render_compact_summary_block("当前进展：已完成 A。")

        self.assertIn("Earlier conversation was compacted", rendered)
        self.assertIn("当前进展：已完成 A。", rendered)

    def test_compaction_runner_returns_compacted_context_from_summary_text(self) -> None:
        llm = ScriptedLLMClient([LLMReply(final_text="当前进展：已完成 A。\n明确下一步：继续 B。")])

        compacted = run_compaction(
            llm=llm,
            session_id="sess_1",
            current_message="继续 B",
            session_messages=[
                SessionMessage.user("任务 A"),
                SessionMessage.assistant("A 完成"),
                SessionMessage.user("任务 A2"),
                SessionMessage.assistant("A2 完成"),
                SessionMessage.user("继续 B"),
            ],
        )

        self.assertIsNotNone(compacted)
        assert compacted is not None
        self.assertIn("当前进展", compacted.summary_text)
        self.assertEqual(compacted.source_message_range, [0, 2])

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
