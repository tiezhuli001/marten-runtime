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

    def test_metadata_filter_is_preserved_for_contains_fallback(self) -> None:
        store, _, _ = _store_with_chunk("无关内容", metadata={"content_type": "author_method"})
        calls: list[dict[str, object] | None] = []
        original = store.find_chunks_containing

        def recording_fallback(namespace, query, *, limit, filters=None):
            calls.append(filters)
            return original(namespace, query, limit=limit, filters=filters)

        store.find_chunks_containing = recording_fallback  # type: ignore[method-assign]
        retriever = KnowledgeRetriever(store)

        retriever.search(
            namespace="fanqie",
            query="不存在的作者方法",
            embedding_config_hash="missing",
            query_vector=[],
            top_k=5,
            filters={"content_type": "author_method"},
        )

        self.assertEqual(calls, [{"content_type": "author_method"}])

    def test_metadata_filter_overfetches_vector_candidates_before_filtering(self) -> None:
        store, source, target = _store_with_chunk("目标方法", metadata={"content_type": "timing_method"})
        distractors = [
            KnowledgeChunk.new(
                namespace="fanqie", source_id=source.source_id, ordinal=index + 1,
                text=f"无关经典 {index}", metadata={"content_type": "classical"},
            )
            for index in range(120)
        ]
        store.replace_chunks("fanqie", source.source_id, [target, *distractors])
        store.upsert_embedding(namespace="fanqie", chunk_id=target.chunk_id, model_id="m", dimension=2, embedding_config_hash="h", vector=[0.8, 0.2])
        for index, item in enumerate(distractors):
            store.upsert_embedding(namespace="fanqie", chunk_id=item.chunk_id, model_id="m", dimension=2, embedding_config_hash="h", vector=[1.0, index * 0.01])
        config = KnowledgeSearchConfig(default_top_k=1, candidate_pool=1, fts_weight=0.0, vector_weight=1.0, metadata_weight=0.0, reranker_weight=0.0)
        retriever = KnowledgeRetriever(store, search_config=config)

        result = retriever.search(
            namespace="fanqie", query="不存在于正文", embedding_config_hash="h",
            query_vector=[1.0, 0.0], top_k=1, filters={"content_type": "timing_method"},
        )

        self.assertEqual([item.chunk_id for item in result.results], [target.chunk_id])

    def test_theory_search_excludes_course_notes_and_cases_by_default(self) -> None:
        store, source, original = _store_with_chunk("月劫格以月令为据", metadata={"evidence_kind": "classical_original"})
        notes = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=1, text="月劫格课程笔记", metadata={"evidence_kind": "course_notes"})
        case = KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=2, text="月劫格命例", metadata={"evidence_kind": "case_record"})
        store.replace_chunks("fanqie", source.source_id, [original, notes, case])
        retriever = KnowledgeRetriever(store)

        default_result = retriever.search(namespace="fanqie", query="月劫格", embedding_config_hash="missing", query_vector=[], top_k=5)
        notes_result = retriever.search(namespace="fanqie", query="月劫格", embedding_config_hash="missing", query_vector=[], top_k=5, filters={"evidence_kind": "course_notes"})

        self.assertEqual([item.chunk_id for item in default_result.results], [original.chunk_id])
        self.assertEqual([item.chunk_id for item in notes_result.results], [notes.chunk_id])
        self.assertGreaterEqual(default_result.total_ms, default_result.fts_ms)

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
        self.assertLessEqual(len(result.results), 5)
        self.assertEqual(len(reranker.passage_values[0]), 2)
        self.assertTrue(any("候选" in item.text for item in result.results))

    def test_search_limits_repeated_chunks_from_one_source(self) -> None:
        store, source, first = _store_with_chunk("月劫格 条件一")
        repeated = [
            KnowledgeChunk.new(namespace="fanqie", source_id=source.source_id, ordinal=index + 1, text=f"月劫格 条件{index + 2}")
            for index in range(4)
        ]
        other_source = KnowledgeSource.new(namespace="fanqie", title="Other", kind="text", uri="local://other")
        other = KnowledgeChunk.new(namespace="fanqie", source_id=other_source.source_id, ordinal=0, text="月劫格 另一来源")
        store.upsert_source(other_source)
        store.replace_chunks("fanqie", source.source_id, [first, *repeated])
        store.replace_chunks("fanqie", other_source.source_id, [other])
        retriever = KnowledgeRetriever(store)

        result = retriever.search(namespace="fanqie", query="月劫格", embedding_config_hash="missing", query_vector=[], top_k=5)

        counts = {}
        for item in result.results:
            counts[item.source_id] = counts.get(item.source_id, 0) + 1
        self.assertLessEqual(max(counts.values()), 2)

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
