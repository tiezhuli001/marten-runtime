import unittest

from marten_runtime.runtime.context import assemble_runtime_context
from marten_runtime.session.models import SessionMessage
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.tools.registry import ToolSnapshot


class RuntimeContextTests(unittest.TestCase):
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

    def test_assembler_limits_replay_to_recent_messages(self) -> None:
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
            replay_limit=3,
        )

        self.assertEqual([item.content for item in context.conversation_messages], ["u2", "a2", "u3"])
        self.assertIn("continuation_hint", context.working_context)


if __name__ == "__main__":
    unittest.main()
