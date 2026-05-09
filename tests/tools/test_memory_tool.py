import unittest
from tempfile import TemporaryDirectory

from marten_runtime.memory.intent import (
    MEMORY_DELETE_INTENT,
    MEMORY_INTENT_FIELD,
    MEMORY_SOURCE_EXCERPT_FIELD,
    MEMORY_WRITE_INTENT,
)
from marten_runtime.memory.service import ThinMemoryService
from marten_runtime.tools.builtins.memory_tool import run_memory_tool


class MemoryToolTests(unittest.TestCase):
    def test_memory_tool_get_append_replace_delete_with_structured_intent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            appended = run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住：以后始终用中文回复",
                    "section": "preferences",
                    "content": "Always answer in Chinese.",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "记住：以后始终用中文回复"},
            )
            replaced = run_memory_tool(
                {
                    "action": "replace",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "请把偏好改成以后回答尽量简洁",
                    "section": "preferences",
                    "content": "Prefer concise answers.",
                },
                memory_service=service,
                tool_context={
                    "user_id": "demo",
                    "message": "请把偏好改成以后回答尽量简洁",
                },
            )
            fetched = run_memory_tool(
                {"action": "get"},
                memory_service=service,
                tool_context={"user_id": "demo"},
            )
            deleted = run_memory_tool(
                {
                    "action": "delete",
                    MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "删除这个偏好",
                    "section": "preferences",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "删除这个偏好"},
            )

        self.assertTrue(appended["available"])
        self.assertIn("Always answer in Chinese.", appended["memory_text"])
        self.assertIn("Prefer concise answers.", replaced["memory_text"])
        self.assertIn("Prefer concise answers.", fetched["memory_text"])
        self.assertEqual(deleted["memory_text"], "")

    def test_memory_tool_rejects_write_without_structured_intent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            with self.assertRaisesRegex(ValueError, "explicit user memory intent"):
                run_memory_tool(
                    {
                        "action": "append",
                        "section": "preferences",
                        "content": "Always answer in Chinese.",
                    },
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "Remember this and save this to memory."},
                )

    def test_memory_tool_rejects_delete_without_structured_intent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住以后始终用中文回复",
                    "section": "preferences",
                    "content": "Always answer in Chinese.",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "记住以后始终用中文回复"},
            )
            with self.assertRaisesRegex(ValueError, "explicit user memory intent"):
                run_memory_tool(
                    {"action": "delete", "section": "preferences"},
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "Delete this memory."},
                )

    def test_memory_tool_rejects_intent_action_mismatch(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            with self.assertRaisesRegex(ValueError, "explicit user memory intent"):
                run_memory_tool(
                    {
                        "action": "append",
                        MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT,
                        MEMORY_SOURCE_EXCERPT_FIELD: "记住以后始终用中文回复",
                        "section": "preferences",
                        "content": "Always answer in Chinese.",
                    },
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "记住以后始终用中文回复"},
                )
            with self.assertRaisesRegex(ValueError, "explicit user memory intent"):
                run_memory_tool(
                    {
                        "action": "delete",
                        MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                        MEMORY_SOURCE_EXCERPT_FIELD: "删除这条记忆",
                        "section": "preferences",
                    },
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "删除这条记忆"},
                )

    def test_memory_tool_rejects_mutation_without_matching_source_excerpt(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            with self.assertRaisesRegex(ValueError, "source_excerpt"):
                run_memory_tool(
                    {
                        "action": "append",
                        MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                        MEMORY_SOURCE_EXCERPT_FIELD: "记住以后始终用英文回复",
                        "section": "preferences",
                        "content": "Always answer in English.",
                    },
                    memory_service=service,
                    tool_context={
                        "user_id": "demo",
                        "message": "记住以后始终用中文回复",
                    },
                )

    def test_memory_tool_degrades_cleanly_without_stable_user_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            result = run_memory_tool(
                {"action": "get"},
                memory_service=service,
                tool_context={"user_id": ""},
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["available"])
        self.assertEqual(result["memory_text"], "")


if __name__ == "__main__":
    unittest.main()
