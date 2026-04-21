import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.memory.service import ThinMemoryService


class ThinMemoryServiceTests(unittest.TestCase):
    def test_memory_path_resolves_from_stable_user_id(self) -> None:
        service = ThinMemoryService("/tmp/memory-root")

        self.assertEqual(
            service.memory_path("demo-user"),
            Path("/tmp/memory-root/users/demo-user/MEMORY.md"),
        )

    def test_distinct_user_ids_with_legacy_sanitize_collision_get_distinct_memory_files(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            first = service.append("a:b", section="facts", content="first user fact")
            second = service.append("a/b", section="facts", content="second user fact")

            first_loaded = service.load("a:b")
            second_loaded = service.load("a/b")

        self.assertNotEqual(first.path, second.path)
        self.assertIn("first user fact", first_loaded.text)
        self.assertNotIn("second user fact", first_loaded.text)
        self.assertIn("second user fact", second_loaded.text)
        self.assertNotIn("first user fact", second_loaded.text)

    def test_missing_memory_file_loads_as_empty(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            document = service.load("demo")

        self.assertTrue(document.available)
        self.assertEqual(document.text, "")
        self.assertEqual(document.sections, {})
        self.assertIsNone(service.render_prompt_memory(""))

    def test_append_replace_delete_and_render_memory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir, prompt_char_limit=80)
            service.append("demo", section="preferences", content="Always reply in Chinese.")
            service.append("demo", section="facts", content="Owns marten-runtime.")
            service.replace("demo", section="preferences", content="Prefer concise answers.")
            document = service.delete("demo", section="facts", content="Owns marten-runtime.")
            rendered = service.render_prompt_memory("demo")

        self.assertIn("## preferences", document.text)
        self.assertNotIn("## facts", document.text)
        self.assertEqual(document.sections["preferences"], ["Prefer concise answers."])
        self.assertIn("User memory:", rendered or "")

    def test_oversized_write_is_rejected(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir, max_write_chars=10)

            with self.assertRaises(ValueError):
                service.append("demo", section="preferences", content="this content is too large")


if __name__ == "__main__":
    unittest.main()
