import tempfile
import unittest
from pathlib import Path

from marten_runtime.knowledge.models import KnowledgeChunk, KnowledgeSource
from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore


class KnowledgeStoreTests(unittest.TestCase):
    def test_store_writes_and_reads_source_and_chunks_by_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            source = KnowledgeSource.new(namespace="fanqie", title="Book", kind="text", uri="local://book")
            chunk = KnowledgeChunk.new(
                namespace="fanqie",
                source_id=source.source_id,
                ordinal=0,
                text="主角第一次遇到师父",
                heading="第一章",
                metadata={"chapter": 1},
                token_estimate=10,
            )

            store.upsert_source(source)
            store.replace_chunks("fanqie", source.source_id, [chunk])

            self.assertEqual(store.get_source("fanqie", source.source_id).title, "Book")
            self.assertEqual(store.get_chunk("fanqie", chunk.chunk_id).text, "主角第一次遇到师父")
            self.assertIsNone(store.get_source("bazi", source.source_id))
            self.assertIsNone(store.get_chunk("bazi", chunk.chunk_id))

    def test_fts_search_is_namespace_scoped_and_excludes_deleted_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            fanqie = KnowledgeSource.new(namespace="fanqie", title="Novel", kind="text", uri="local://novel")
            bazi = KnowledgeSource.new(namespace="bazi", title="Bazi", kind="text", uri="local://bazi")
            store.upsert_source(fanqie)
            store.upsert_source(bazi)
            fanqie_chunk = KnowledgeChunk.new(namespace="fanqie", source_id=fanqie.source_id, ordinal=0, text="紫微星入命", heading="命格")
            bazi_chunk = KnowledgeChunk.new(namespace="bazi", source_id=bazi.source_id, ordinal=0, text="紫微星入命", heading="命格")
            store.replace_chunks("fanqie", fanqie.source_id, [fanqie_chunk])
            store.replace_chunks("bazi", bazi.source_id, [bazi_chunk])

            fanqie_results = store.search_fts("fanqie", "紫微星", limit=10)
            self.assertEqual([item.chunk_id for item in fanqie_results], [fanqie_chunk.chunk_id])

            deleted = store.delete_source("fanqie", fanqie.source_id)
            self.assertEqual(deleted.deleted_chunk_count, 1)
            self.assertEqual(store.search_fts("fanqie", "紫微星", limit=10), [])
            self.assertEqual([item.chunk_id for item in store.search_fts("bazi", "紫微星", limit=10)], [bazi_chunk.chunk_id])

    def test_fts_search_treats_special_characters_as_plain_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            source = KnowledgeSource.new(namespace="fanqie", title="Novel", kind="text", uri="local://novel")
            store.upsert_source(source)
            chunk = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=0, text='C++ A-B x:y * "quote"', heading="符号")
            store.replace_chunks("fanqie", source.source_id, [chunk])

            for query in ["C++", "A-B", "x:y", "*", '"quote"']:
                with self.subTest(query=query):
                    results = store.search_fts("fanqie", query, limit=10)
                    self.assertEqual([item.chunk_id for item in results], [chunk.chunk_id])


    def test_delete_source_removes_sqlite_vec_rows_from_active_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            source = KnowledgeSource.new(namespace="fanqie", title="Book", kind="text", uri="local://book")
            chunk = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=0, text="hello")
            store.upsert_source(source)
            store.replace_chunks("fanqie", source.source_id, [chunk])
            store.upsert_embedding(namespace="fanqie", chunk_id=chunk.chunk_id, model_id="m", dimension=512, embedding_config_hash="h", vector=[1.0] + [0.0] * 511)

            self.assertEqual(len(store.query_sqlite_vec("fanqie", "h", [1.0] + [0.0] * 511, top_k=1).items), 1)
            store.delete_source("fanqie", source.source_id)

            self.assertEqual(store.query_sqlite_vec("fanqie", "h", [1.0] + [0.0] * 511, top_k=1).items, [])

    def test_namespace_embedding_config_hash_can_be_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            self.assertIsNone(store.get_namespace_config_hash("fanqie"))

            store.set_namespace_config_hash("fanqie", "hash_a")
            self.assertEqual(store.get_namespace_config_hash("fanqie"), "hash_a")

            store.set_namespace_config_hash("fanqie", "hash_b")
            self.assertEqual(store.get_namespace_config_hash("fanqie"), "hash_b")

    def test_embeddings_are_filtered_by_config_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            source = KnowledgeSource.new(namespace="fanqie", title="Book", kind="text", uri="local://book")
            chunk = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=0, text="hello")
            store.upsert_source(source)
            store.replace_chunks("fanqie", source.source_id, [chunk])

            store.upsert_embedding(
                namespace="fanqie",
                chunk_id=chunk.chunk_id,
                model_id="m1",
                dimension=3,
                embedding_config_hash="hash_a",
                vector=[1.0, 0.0, 0.0],
            )

            self.assertEqual(len(store.list_embeddings("fanqie", "hash_a")), 1)
            self.assertEqual(store.list_embeddings("fanqie", "hash_b"), [])

    def test_ingest_job_round_trip_includes_recovery_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            store.upsert_ingest_job(
                namespace="bazi",
                job_id="job-1",
                source_title="Theory",
                status="failed",
                error="provider unavailable",
                error_code="KNOWLEDGE_EMBEDDING_UNAVAILABLE",
                retryable=True,
                staged_file_path="upload-1/theory.md",
            )

            job = store.get_ingest_job("bazi", "job-1")

            self.assertEqual(job["error_code"], "KNOWLEDGE_EMBEDDING_UNAVAILABLE")
            self.assertTrue(job["retryable"])
            self.assertEqual(job["staged_file_path"], "upload-1/theory.md")


if __name__ == "__main__":
    unittest.main()
