import unittest

from marten_runtime.knowledge.chunking import chunk_text
from marten_runtime.knowledge.config import KnowledgeChunkingConfig


class KnowledgeChunkingTests(unittest.TestCase):
    def test_chunks_heading_and_paragraphs_with_metadata(self) -> None:
        config = KnowledgeChunkingConfig(target_chars=20, overlap_chars=5, max_chars=30, batch_size=4)
        chunks = chunk_text(
            namespace="fanqie",
            source_id="src1",
            text="# 第一章\n主角进入山门。\n\n师父出现并收徒。",
            config=config,
            metadata={"novel_id": "n1"},
        )

        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(chunks[0].heading, "第一章")
        self.assertEqual(chunks[0].metadata["novel_id"], "n1")
        self.assertEqual([chunk.ordinal for chunk in chunks], list(range(len(chunks))))

    def test_long_paragraph_respects_max_chars_and_overlap(self) -> None:
        config = KnowledgeChunkingConfig(target_chars=10, overlap_chars=3, max_chars=12, batch_size=4)
        chunks = chunk_text(
            namespace="fanqie",
            source_id="src1",
            text="abcdefghijklmnopqrstuvwx",
            config=config,
        )

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.text) <= 12 for chunk in chunks))
        self.assertTrue(chunks[1].text.startswith(chunks[0].text[-3:]))

    def test_empty_text_is_rejected(self) -> None:
        config = KnowledgeChunkingConfig(target_chars=10, overlap_chars=2, max_chars=12, batch_size=4)
        with self.assertRaises(ValueError):
            chunk_text(namespace="fanqie", source_id="src1", text="  ", config=config)

    def test_chunking_changes_when_target_chars_changes(self) -> None:
        text = "一" * 100
        small = KnowledgeChunkingConfig(target_chars=20, overlap_chars=5, max_chars=25, batch_size=4)
        large = KnowledgeChunkingConfig(target_chars=50, overlap_chars=5, max_chars=60, batch_size=4)

        small_chunks = chunk_text(namespace="fanqie", source_id="src1", text=text, config=small)
        large_chunks = chunk_text(namespace="fanqie", source_id="src1", text=text, config=large)

        self.assertGreater(len(small_chunks), len(large_chunks))


if __name__ == "__main__":
    unittest.main()
