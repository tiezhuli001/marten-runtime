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
            document = service.delete("demo", section="facts", content="Owns marten-runtime.", scope="global")
            rendered = service.render_prompt_memory("demo", current_message="concise")
            exported = service.memory_path("demo").read_text(encoding="utf-8")

        self.assertIn("## global / preference / preferences", document.text)
        self.assertNotIn("## global / facts", document.text)
        self.assertEqual(document.sections["preferences"], ["Prefer concise answers."])
        self.assertIn("User memory:", rendered or "")
        self.assertIn("Prefer concise answers.", exported)


    def test_replace_by_section_marks_previous_items_superseded(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            service.append("demo", section="preferences", content="Always reply in English.", type="preference")
            service.replace("demo", section="preferences", content="Always reply in Chinese.", type="preference")

            active = service.store.list_active("demo", scope="global", type="preference")
            rows = []
            with service.store._connect() as conn:  # type: ignore[attr-defined]
                rows = conn.execute(
                    "SELECT content, status FROM memory_items"
                ).fetchall()

        self.assertEqual([item.content for item in active], ["Always reply in Chinese."])
        statuses_by_content = {str(row["content"]): str(row["status"]) for row in rows}
        self.assertEqual(statuses_by_content["Always reply in English."], "superseded")
        self.assertEqual(statuses_by_content["Always reply in Chinese."], "active")


    def test_replace_by_memory_id_requires_same_user(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            service.append("alice", section="preferences", content="Alice only.", type="preference")
            alice_item = service.store.list_active("alice", scope="global", type="preference")[0]

            service.replace(
                "bob",
                section="preferences",
                content="Bob overwrite.",
                type="preference",
                memory_id=alice_item.memory_id,
            )

            alice_active = service.store.list_active("alice", scope="global", type="preference")
            bob_active = service.store.list_active("bob", scope="global", type="preference")

        self.assertEqual([item.content for item in alice_active], ["Alice only."])
        self.assertEqual([item.content for item in bob_active], ["Bob overwrite."])


    def test_delete_requires_explicit_scope_and_preserves_other_scopes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            service.append("demo", section="preferences", content="global preference", scope="global", type="preference")
            service.append(
                "demo",
                section="preferences",
                content="agent preference",
                scope="agent",
                agent_id="main",
                type="preference",
            )

            with self.assertRaisesRegex(ValueError, "scope is required"):
                service.delete("demo", section="preferences")

            global_active = service.store.list_active("demo", scope="global", type="preference")
            agent_active = service.store.list_active("demo", scope="agent", agent_id="main", type="preference")

        self.assertEqual([item.content for item in global_active], ["global preference"])
        self.assertEqual([item.content for item in agent_active], ["agent preference"])


    def test_delete_agent_scope_requires_agent_id_and_keeps_other_agents(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            service.append(
                "demo",
                section="preferences",
                content="main preference",
                scope="agent",
                agent_id="main",
                type="preference",
            )
            service.append(
                "demo",
                section="preferences",
                content="coding preference",
                scope="agent",
                agent_id="coding",
                type="preference",
            )

            with self.assertRaisesRegex(ValueError, "agent_id is required"):
                service.delete("demo", section="preferences", scope="agent")

            main_active = service.store.list_active("demo", scope="agent", agent_id="main", type="preference")
            coding_active = service.store.list_active("demo", scope="agent", agent_id="coding", type="preference")

        self.assertEqual([item.content for item in main_active], ["main preference"])
        self.assertEqual([item.content for item in coding_active], ["coding preference"])

    def test_delete_workspace_scope_requires_workspace_id_and_keeps_other_workspaces(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            service.append(
                "demo",
                section="project",
                content="first workspace",
                scope="workspace",
                workspace_id="/tmp/first",
                type="fact",
            )
            service.append(
                "demo",
                section="project",
                content="second workspace",
                scope="workspace",
                workspace_id="/tmp/second",
                type="fact",
            )

            with self.assertRaisesRegex(ValueError, "workspace_id is required"):
                service.delete("demo", section="project", scope="workspace")

            first_active = service.store.list_active("demo", scope="workspace", workspace_id="/tmp/first", type="fact")
            second_active = service.store.list_active("demo", scope="workspace", workspace_id="/tmp/second", type="fact")

        self.assertEqual([item.content for item in first_active], ["first workspace"])
        self.assertEqual([item.content for item in second_active], ["second workspace"])

    def test_delete_by_memory_id_requires_same_user(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            service.append("alice", section="preferences", content="Alice only.", type="preference")
            alice_item = service.store.list_active("alice", scope="global", type="preference")[0]

            service.delete("bob", section="preferences", scope="global", memory_id=alice_item.memory_id)

            alice_active = service.store.list_active("alice", scope="global", type="preference")

        self.assertEqual([item.content for item in alice_active], ["Alice only."])


    def test_delete_by_memory_id_uses_canonical_agent_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            service.append(
                "demo",
                section="preferences",
                content="assistant alias preference",
                scope="agent",
                agent_id="assistant",
                type="preference",
            )
            item = service.store.list_active("demo", scope="agent", agent_id="main", type="preference")[0]

            service.delete(
                "demo",
                section="preferences",
                scope="agent",
                agent_id="assistant",
                memory_id=item.memory_id,
            )

            active = service.store.list_active("demo", scope="agent", agent_id="main", type="preference")

        self.assertEqual(active, [])

    def test_replace_by_memory_id_uses_canonical_agent_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            service.append(
                "demo",
                section="preferences",
                content="old alias preference",
                scope="agent",
                agent_id="assistant",
                type="preference",
            )
            item = service.store.list_active("demo", scope="agent", agent_id="main", type="preference")[0]

            service.replace(
                "demo",
                section="preferences",
                content="new alias preference",
                scope="agent",
                agent_id="assistant",
                type="preference",
                memory_id=item.memory_id,
            )

            active = service.store.list_active("demo", scope="agent", agent_id="main", type="preference")

        self.assertEqual([item.content for item in active], ["new alias preference"])

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

    def test_export_preserves_explicit_section_for_round_trip(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            service.append("demo", section="output_style", content="默认先给结论。", type="preference")

            exported = service.memory_path("demo").read_text(encoding="utf-8")

        self.assertIn("## global / preference / output_style", exported)
        self.assertNotIn("## global / preference / preferences", exported)

    def test_delete_rejects_invalid_scope_and_preserves_memory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            service.append("demo", section="preferences", content="global preference", scope="global", type="preference")

            with self.assertRaisesRegex(ValueError, "unsupported memory scope"):
                service.delete("demo", section="preferences", scope="globla")

            active = service.store.list_active("demo", scope="global", type="preference")

        self.assertEqual([item.content for item in active], ["global preference"])


if __name__ == "__main__":
    unittest.main()
