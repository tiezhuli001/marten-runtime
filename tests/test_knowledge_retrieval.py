import tempfile
import unittest
from pathlib import Path

from marten_runtime.knowledge.config import KnowledgeSearchConfig
from marten_runtime.knowledge.models import KnowledgeChunk, KnowledgeSource
from marten_runtime.knowledge.retrieval import KnowledgeRetriever
from marten_runtime.knowledge.rerankers import RerankItem, RerankResult, RerankStatus
from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore


class RecordingReranker:
    def __init__(self) -> None:
        self.top_n_values: list[int] = []
        self.passage_values: list[list[str]] = []

    def rerank(self, query: str, passages: list[str], *, top_n: int) -> RerankResult:
        del query
        self.top_n_values.append(top_n)
        self.passage_values.append(list(passages))
        return RerankResult(
            status=RerankStatus.AVAILABLE,
            items=[RerankItem(index=index, score=float(len(passages) - index)) for index in range(min(top_n, len(passages)))],
        )


class KnowledgeRetrievalTests(unittest.TestCase):
    def test_search_uses_fts_only_when_vector_config_mismatch(self) -> None:
        store, source, chunk = _store_with_chunk("师父在山门出现")
        retriever = KnowledgeRetriever(store)

        result = retriever.search(namespace="fanqie", query="师父", embedding_config_hash="missing", query_vector=[1.0, 0.0], top_k=5)

        self.assertEqual(result.retrieval_mode, "fts_only")
        self.assertEqual(result.vector_status, "config_mismatch")
        self.assertEqual(result.results[0].chunk_id, chunk.chunk_id)
        self.assertIn("knowledge.reindex --namespace fanqie", result.degraded_reason)
        runs = store.list_search_runs("fanqie")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["retrieval_mode"], "fts_only")
        self.assertEqual(runs[0]["result_count"], 1)

    def test_search_merges_vector_and_fts_candidates_without_duplicates(self) -> None:
        store, source, chunk = _store_with_chunk("师父在山门出现")
        other = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=1, text="主角练剑")
        store.replace_chunks("fanqie", source.source_id, [chunk, other])
        store.upsert_embedding(namespace="fanqie", chunk_id=chunk.chunk_id, model_id="m", dimension=2, embedding_config_hash="h", vector=[1.0, 0.0])
        store.upsert_embedding(namespace="fanqie", chunk_id=other.chunk_id, model_id="m", dimension=2, embedding_config_hash="h", vector=[0.9, 0.1])
        retriever = KnowledgeRetriever(store)

        result = retriever.search(namespace="fanqie", query="师父", embedding_config_hash="h", query_vector=[1.0, 0.0], top_k=5)

        self.assertEqual(result.retrieval_mode, "hybrid_rerank")
        self.assertEqual(len({item.chunk_id for item in result.results}), len(result.results))
        self.assertEqual(result.results[0].chunk_id, chunk.chunk_id)
        self.assertEqual(result.results[0].source_title, "Book")


    def test_search_uses_configured_candidate_pool_and_weights(self) -> None:
        store, source, chunk = _store_with_chunk("师父在山门出现")
        other = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=1, text="主角练剑")
        store.replace_chunks("fanqie", source.source_id, [chunk, other])
        store.upsert_embedding(namespace="fanqie", chunk_id=chunk.chunk_id, model_id="m", dimension=2, embedding_config_hash="h", vector=[1.0, 0.0])
        store.upsert_embedding(namespace="fanqie", chunk_id=other.chunk_id, model_id="m", dimension=2, embedding_config_hash="h", vector=[0.0, 1.0])
        config = KnowledgeSearchConfig(default_top_k=1, candidate_pool=1, fts_weight=0.0, vector_weight=10.0, metadata_weight=0.0, reranker_weight=0.0)
        retriever = KnowledgeRetriever(store, search_config=config)

        result = retriever.search(namespace="fanqie", query="师父", embedding_config_hash="h", query_vector=[0.0, 1.0], top_k=1)

        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].chunk_id, other.chunk_id)
        self.assertAlmostEqual(result.results[0].score, result.results[0].score_parts["vector"] * 10.0)

    def test_metadata_filter_limits_results(self) -> None:
        store, source, chunk = _store_with_chunk("师父在山门出现", metadata={"novel_id": "a"})
        other = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=1, text="师父在山门出现", metadata={"novel_id": "b"})
        store.replace_chunks("fanqie", source.source_id, [chunk, other])
        retriever = KnowledgeRetriever(store)

        result = retriever.search(namespace="fanqie", query="师父", embedding_config_hash="missing", query_vector=[], top_k=5, filters={"novel_id": "a"})

        self.assertEqual([item.chunk_id for item in result.results], [chunk.chunk_id])

    def test_reranker_top_n_limits_configured_rerank_scope(self) -> None:
        store, source, chunk = _store_with_chunk("师父在山门出现")
        other_chunks = [
            KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=index + 1, text=f"师父 候选 {index}")
            for index in range(4)
        ]
        chunks = [chunk, *other_chunks]
        store.replace_chunks("fanqie", source.source_id, chunks)
        for index, item in enumerate(chunks):
            store.upsert_embedding(namespace="fanqie", chunk_id=item.chunk_id, model_id="m", dimension=2, embedding_config_hash="h", vector=[1.0, float(index)])
        reranker = RecordingReranker()
        config = KnowledgeSearchConfig(default_top_k=5, candidate_pool=5, fts_weight=1.0, vector_weight=1.0, metadata_weight=0.0, reranker_weight=1.0)
        retriever = KnowledgeRetriever(store, reranker=reranker, search_config=config, reranker_top_n=2)

        result = retriever.search(namespace="fanqie", query="师父", embedding_config_hash="h", query_vector=[1.0, 0.0], top_k=5)

        self.assertEqual(reranker.top_n_values, [2])
        self.assertEqual(len(result.results), 5)
        self.assertEqual(len(reranker.passage_values[0]), 2)
        self.assertTrue(any("候选" in item.text for item in result.results[2:]))

    def test_reranker_top_n_uses_highest_weighted_candidates(self) -> None:
        store, source, chunk = _store_with_chunk("师父 强相关")
        low_weight_chunks = [
            KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=index + 1, text=f"师父 弱相关 {index}")
            for index in range(3)
        ]
        high_vector = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=4, text="向量最相关")
        chunks = [chunk, *low_weight_chunks, high_vector]
        store.replace_chunks("fanqie", source.source_id, chunks)
        for item in chunks:
            vector = [0.0, 1.0] if item.chunk_id == high_vector.chunk_id else [1.0, 0.0]
            store.upsert_embedding(namespace="fanqie", chunk_id=item.chunk_id, model_id="m", dimension=2, embedding_config_hash="h", vector=vector)
        reranker = RecordingReranker()
        config = KnowledgeSearchConfig(default_top_k=5, candidate_pool=5, fts_weight=0.0, vector_weight=10.0, metadata_weight=0.0, reranker_weight=1.0)
        retriever = KnowledgeRetriever(store, reranker=reranker, search_config=config, reranker_top_n=2)

        retriever.search(namespace="fanqie", query="师父", embedding_config_hash="h", query_vector=[0.0, 1.0], top_k=5)

        self.assertIn("向量最相关", reranker.passage_values[0])


def _store_with_chunk(text: str, metadata: dict | None = None):
    tmp = tempfile.TemporaryDirectory()
    store = SQLiteKnowledgeStore(Path(tmp.name) / "knowledge.sqlite3")
    store._tmp = tmp
    source = KnowledgeSource.new(namespace="fanqie", title="Book", kind="text", uri="local://book")
    chunk = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=0, text=text, metadata=metadata or {})
    store.upsert_source(source)
    store.replace_chunks("fanqie", source.source_id, [chunk])
    return store, source, chunk


if __name__ == "__main__":
    unittest.main()
