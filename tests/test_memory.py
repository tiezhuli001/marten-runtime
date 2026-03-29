import unittest

from marten_runtime.memory.export import export_entries
from marten_runtime.memory.models import MemoryEntry, Note, Persona
from marten_runtime.memory.promotion import promote_memory
from marten_runtime.memory.store import MemoryStore


class MemoryTests(unittest.TestCase):
    def test_store_keeps_notes_personas_and_entries_by_session(self) -> None:
        store = MemoryStore()
        store.save_note(Note(note_id="note_1", session_key="sess_1", content="remember this"))
        store.save_persona(Persona(persona_id="persona_1", summary="be concise"))
        store.save_entry(
            MemoryEntry(entry_id="mem_1", session_key="sess_1", memory_type="semantic", text="alpha fact")
        )

        self.assertEqual(store.list_entries("sess_1")[0].text, "alpha fact")
        self.assertEqual(store.get_note("note_1").content, "remember this")
        self.assertEqual(store.get_persona("persona_1").summary, "be concise")

    def test_export_and_promotion_keep_file_readable_memory(self) -> None:
        items = [
            MemoryEntry(entry_id="mem_1", session_key="sess_1", memory_type="semantic", text="alpha fact"),
            MemoryEntry(entry_id="mem_2", session_key="sess_1", memory_type="procedural", text="run tests"),
        ]

        exported = export_entries(items)
        promoted = promote_memory(items)

        self.assertIn("alpha fact", exported)
        self.assertEqual(promoted["semantic"], ["alpha fact"])
        self.assertEqual(promoted["procedural"], ["run tests"])


if __name__ == "__main__":
    unittest.main()
