import tempfile
import unittest
from pathlib import Path
from unittest import mock

from marten_runtime.knowledge.models import KnowledgeChunk, KnowledgeSource
from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore
from marten_runtime.knowledge.vector_store import VectorStatus, query_vectors


class KnowledgeVectorStoreTests(unittest.TestCase):
    def test_query_vectors_orders_by_similarity_and_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            source = KnowledgeSource.new(namespace="fanqie", title="Book", kind="text", uri="local://book")
            other = KnowledgeSource.new(namespace="bazi", title="Bazi", kind="text", uri="local://bazi")
            store.upsert_source(source)
            store.upsert_source(other)
            a = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=0, text="a")
            b = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=1, text="b")
            c = KnowledgeChunk.new(namespace="bazi", source_id=other.source_id, ordinal=0, text="c")
            store.replace_chunks("fanqie", source.source_id, [a, b])
            store.replace_chunks("bazi", other.source_id, [c])
            store.upsert_embedding(namespace="fanqie", chunk_id=a.chunk_id, model_id="m", dimension=2, embedding_config_hash="h", vector=[1.0, 0.0])
            store.upsert_embedding(namespace="fanqie", chunk_id=b.chunk_id, model_id="m", dimension=2, embedding_config_hash="h", vector=[0.0, 1.0])
            store.upsert_embedding(namespace="bazi", chunk_id=c.chunk_id, model_id="m", dimension=2, embedding_config_hash="h", vector=[1.0, 0.0])

            result = query_vectors(store, namespace="fanqie", embedding_config_hash="h", query_vector=[0.9, 0.1], top_k=2)

            self.assertEqual(result.status, VectorStatus.AVAILABLE)
            self.assertEqual([item.chunk_id for item in result.items], [a.chunk_id, b.chunk_id])

    def test_query_vectors_reports_config_mismatch_when_hash_has_no_vectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            result = query_vectors(store, namespace="fanqie", embedding_config_hash="missing", query_vector=[1.0], top_k=2)

            self.assertEqual(result.status, VectorStatus.CONFIG_MISMATCH)
            self.assertEqual(result.items, [])

    def test_query_vectors_reports_unavailable_query_vector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            result = query_vectors(store, namespace="fanqie", embedding_config_hash="h", query_vector=[], top_k=2)

            self.assertEqual(result.status, VectorStatus.QUERY_VECTOR_UNAVAILABLE)
            self.assertIn("Query embedding", result.message)

    def test_query_vectors_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            result = query_vectors(store, namespace="fanqie", embedding_config_hash="h", query_vector=[1.0], top_k=2, enabled=False)

            self.assertEqual(result.status, VectorStatus.DISABLED)

    def test_query_vectors_disables_sqlite_vec_backend_when_extension_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            with mock.patch.object(store, "sqlite_vec_available", return_value=False):
                result = query_vectors(
                    store,
                    namespace="fanqie",
                    embedding_config_hash="h",
                    query_vector=[1.0],
                    top_k=2,
                    backend="sqlite_vec",
                )

            self.assertEqual(result.status, VectorStatus.DISABLED)
            self.assertIn("sqlite-vec", result.message)

    def test_query_vectors_uses_sqlite_vec_backend_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            source = KnowledgeSource.new(namespace="fanqie", title="Book", kind="text", uri="local://book")
            store.upsert_source(source)
            a = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=0, text="a")
            b = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=1, text="b")
            store.replace_chunks("fanqie", source.source_id, [a, b])
            store.upsert_embedding(namespace="fanqie", chunk_id=a.chunk_id, model_id="m", dimension=512, embedding_config_hash="h", vector=[1.0] + [0.0] * 511)
            store.upsert_embedding(namespace="fanqie", chunk_id=b.chunk_id, model_id="m", dimension=512, embedding_config_hash="h", vector=[0.0, 1.0] + [0.0] * 510)

            result = query_vectors(store, namespace="fanqie", embedding_config_hash="h", query_vector=[0.9, 0.1] + [0.0] * 510, top_k=2, backend="sqlite_vec")

            self.assertEqual(result.status, VectorStatus.AVAILABLE)
            self.assertEqual([item.chunk_id for item in result.items], [a.chunk_id, b.chunk_id])

    def test_query_vectors_sqlite_vec_backend_error_does_not_fallback_to_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            source = KnowledgeSource.new(namespace="fanqie", title="Book", kind="text", uri="local://book")
            store.upsert_source(source)
            chunk = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=0, text="a")
            store.replace_chunks("fanqie", source.source_id, [chunk])
            store.upsert_embedding(namespace="fanqie", chunk_id=chunk.chunk_id, model_id="m", dimension=512, embedding_config_hash="h", vector=[1.0] + [0.0] * 511)
            store.set_namespace_config_hash("fanqie", "h")
            conn = store._connect()
            try:
                store._delete_sqlite_vec_embeddings(conn, "fanqie", chunk_ids=[chunk.chunk_id])
                conn.commit()
            finally:
                conn.close()
            with mock.patch.object(store, "sqlite_vec_available", return_value=True), mock.patch.object(store, "list_embeddings") as list_embeddings:
                result = query_vectors(store, namespace="fanqie", embedding_config_hash="h", query_vector=[1.0] + [0.0] * 511, top_k=2, backend="sqlite_vec")

            self.assertEqual(result.status, VectorStatus.BACKEND_ERROR)
            self.assertEqual(result.items, [])
            self.assertIn("sqlite-vec index", result.message)
            list_embeddings.assert_not_called()

    def test_query_vectors_sqlite_vec_missing_table_rows_reports_backend_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            source = KnowledgeSource.new(namespace="fanqie", title="Book", kind="text", uri="local://book")
            store.upsert_source(source)
            chunk = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=0, text="a")
            store.replace_chunks("fanqie", source.source_id, [chunk])
            store.upsert_embedding(namespace="fanqie", chunk_id=chunk.chunk_id, model_id="m", dimension=512, embedding_config_hash="h", vector=[1.0] + [0.0] * 511)
            store.set_namespace_config_hash("fanqie", "h")
            conn = store._connect()
            try:
                conn.execute("DELETE FROM knowledge_embedding_vec_512")
                conn.commit()
            finally:
                conn.close()
            with mock.patch.object(store, "sqlite_vec_available", return_value=True), mock.patch.object(store, "list_embeddings") as list_embeddings:
                result = query_vectors(store, namespace="fanqie", embedding_config_hash="h", query_vector=[1.0] + [0.0] * 511, top_k=2, backend="sqlite_vec")

            self.assertEqual(result.status, VectorStatus.BACKEND_ERROR)
            self.assertEqual(result.items, [])
            self.assertIn("sqlite-vec index", result.message)
            list_embeddings.assert_not_called()

    def test_query_vectors_sqlite_vec_reports_config_mismatch_without_json_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteKnowledgeStore(Path(tmp) / "knowledge.sqlite3")
            source = KnowledgeSource.new(namespace="fanqie", title="Book", kind="text", uri="local://book")
            store.upsert_source(source)
            chunk = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=0, text="a")
            store.replace_chunks("fanqie", source.source_id, [chunk])
            store.upsert_embedding(namespace="fanqie", chunk_id=chunk.chunk_id, model_id="m", dimension=512, embedding_config_hash="old", vector=[1.0] + [0.0] * 511)
            with mock.patch.object(store, "sqlite_vec_available", return_value=True), mock.patch.object(store, "list_embeddings") as list_embeddings:
                result = query_vectors(store, namespace="fanqie", embedding_config_hash="new", query_vector=[1.0] + [0.0] * 511, top_k=2, backend="sqlite_vec")

            self.assertEqual(result.status, VectorStatus.CONFIG_MISMATCH)
            list_embeddings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
