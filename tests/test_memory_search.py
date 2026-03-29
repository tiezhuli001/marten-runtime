import unittest

from marten_runtime.memory.models import MemoryEntry
from marten_runtime.memory.recall import build_recall_context
from marten_runtime.memory.search import search_entries


class MemorySearchTests(unittest.TestCase):
    def test_search_and_recall_find_query_driven_matches(self) -> None:
        items = [
            MemoryEntry(entry_id="mem_1", session_key="sess_1", memory_type="semantic", text="release note alpha"),
            MemoryEntry(entry_id="mem_2", session_key="sess_1", memory_type="procedural", text="run release checklist"),
        ]

        matched = search_entries("release", items)
        recall = build_recall_context("release", items)

        self.assertEqual(len(matched), 2)
        self.assertIn("release note alpha", recall)


if __name__ == "__main__":
    unittest.main()
