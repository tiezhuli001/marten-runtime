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

    def test_missing_memory_loads_as_empty_and_unstable_user_has_no_prompt_memory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            document = service.load("demo")

        self.assertTrue(document.available)
        self.assertEqual(document.text, "")
        self.assertEqual(document.sections, {})
        self.assertIsNone(service.render_prompt_memory(""))

    def test_append_replace_delete_export_and_render_memory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir, prompt_char_limit=200)
            service.append("demo", section="preferences", content="Always reply in Chinese.", type="preference")
            service.append("demo", section="facts", content="Owns marten-runtime.", type="fact")
            service.replace("demo", section="preferences", content="Prefer concise answers.", type="preference")
            document = service.delete("demo", section="facts", content="Owns marten-runtime.")
            rendered = service.render_prompt_memory("demo", current_message="concise")
            exported = service.memory_path("demo").read_text(encoding="utf-8")

        self.assertIn("## global / preferences", document.text)
        self.assertNotIn("## global / facts", document.text)
        self.assertEqual(document.sections["preferences"], ["Prefer concise answers."])
        self.assertIn("User memory:", rendered or "")
        self.assertIn("Prefer concise answers.", exported)

    def test_agent_memory_only_renders_for_matching_agent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir, prompt_char_limit=300)
            service.append("demo", section="runtime", content="main only", scope="agent", agent_id="main", type="constraint")
            service.append("demo", section="runtime", content="coding only", scope="agent", agent_id="coding", type="constraint")

            main_rendered = service.render_prompt_memory("demo", agent_id="main")
            coding_rendered = service.render_prompt_memory("demo", agent_id="coding")

        self.assertIn("main only", main_rendered or "")
        self.assertNotIn("coding only", main_rendered or "")
        self.assertIn("coding only", coding_rendered or "")
        self.assertNotIn("main only", coding_rendered or "")

    def test_oversized_write_is_rejected(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir, max_write_chars=10)

            with self.assertRaises(ValueError):
                service.append("demo", section="preferences", content="this content is too large")


if __name__ == "__main__":
    unittest.main()
