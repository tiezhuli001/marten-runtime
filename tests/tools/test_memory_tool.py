import unittest
from tempfile import TemporaryDirectory

from marten_runtime.memory.service import ThinMemoryService
from marten_runtime.tools.builtins.memory_tool import run_memory_tool


class MemoryToolTests(unittest.TestCase):
    def test_memory_tool_get_append_replace_delete_with_explicit_user_intent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            appended = run_memory_tool(
                {"action": "append", "section": "preferences", "content": "Always answer in Chinese."},
                memory_service=service,
                tool_context={"user_id": "demo", "message": "Remember this and save this to memory."},
            )
            replaced = run_memory_tool(
                {"action": "replace", "section": "preferences", "content": "Prefer concise answers."},
                memory_service=service,
                tool_context={"user_id": "demo", "message": "Update memory with this preference."},
            )
            fetched = run_memory_tool(
                {"action": "get"},
                memory_service=service,
                tool_context={"user_id": "demo"},
            )
            deleted = run_memory_tool(
                {"action": "delete", "section": "preferences"},
                memory_service=service,
                tool_context={"user_id": "demo", "message": "Delete this memory."},
            )

        self.assertTrue(appended["available"])
        self.assertIn("Always answer in Chinese.", appended["memory_text"])
        self.assertIn("Prefer concise answers.", replaced["memory_text"])
        self.assertIn("Prefer concise answers.", fetched["memory_text"])
        self.assertEqual(deleted["memory_text"], "")

    def test_memory_tool_rejects_write_without_explicit_user_intent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            with self.assertRaisesRegex(ValueError, "explicit user memory intent"):
                run_memory_tool(
                    {"action": "append", "section": "preferences", "content": "Always answer in Chinese."},
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "Please answer this question."},
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
