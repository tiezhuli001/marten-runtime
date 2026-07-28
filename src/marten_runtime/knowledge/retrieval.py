from __future__ import annotations

from time import perf_counter

from pydantic import BaseModel, Field

from marten_runtime.knowledge.config import KnowledgeSearchConfig
from marten_runtime.knowledge.models import KnowledgeChunk
from marten_runtime.knowledge.rerankers import FakeReranker, RerankStatus, weighted_rerank
from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore
from marten_runtime.knowledge.vector_store import VectorStatus, query_vectors


class KnowledgeSearchResultItem(BaseModel):
    chunk_id: str
    source_id: str
    source_title: str = ""
    text: str
    heading: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)
    score: float = 0.0
    score_parts: dict[str, float] = Field(default_factory=dict)


class KnowledgeSearchResult(BaseModel):
    namespace: str
    query: str
    retrieval_mode: str
    vector_status: str
    rerank_status: str = ""
    degraded_reason: str = ""
    search_run_id: str = ""
    fts_ms: float = 0.0
    vector_ms: float = 0.0
    rerank_ms: float = 0.0
    total_ms: float = 0.0
    results: list[KnowledgeSearchResultItem] = Field(default_factory=list)


class KnowledgeRetriever:
    def __init__(
        self,
        store: SQLiteKnowledgeStore,
        *,
        reranker=None,
        vector_store_enabled: bool = True,
        vector_store_backend: str = "json_cosine",
        search_config: KnowledgeSearchConfig | None = None,
        reranker_top_n: int | None = None,
    ) -> None:
        self.store = store
        self.reranker = reranker or FakeReranker()
        self.vector_store_enabled = vector_store_enabled
        self.vector_store_backend = vector_store_backend
        self.search_config = search_config
        self.reranker_top_n = reranker_top_n

    def search(
        self,
        *,
        namespace: str,
        query: str,
        embedding_config_hash: str,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, object] | None = None,
    ) -> KnowledgeSearchResult:
        started_at = perf_counter()
        candidate_limit = self._candidate_limit(top_k)
        fts_started_at = perf_counter()
        fts_chunks = self.store.search_fts(namespace, query, limit=candidate_limit)
        if not fts_chunks:
            fts_chunks = self.store.find_chunks_containing(namespace, query, limit=candidate_limit)
        fts_ms = _elapsed_ms(fts_started_at)
        vector_started_at = perf_counter()
        vector_result = query_vectors(
            self.store,
            namespace=namespace,
            embedding_config_hash=embedding_config_hash,
            query_vector=query_vector,
            top_k=candidate_limit,
            enabled=self.vector_store_enabled,
            backend=self.vector_store_backend,
        )
        vector_ms = _elapsed_ms(vector_started_at)
        candidates: dict[str, KnowledgeSearchResultItem] = {}
        for rank, chunk in enumerate(fts_chunks):
            if _matches_filters(chunk, filters):
                item = self._item_from_chunk(namespace, chunk)
                item.score_parts["fts"] = 1.0 / float(rank + 1)
                candidates[item.chunk_id] = item

        vector_status = str(vector_result.status)
        degraded_reason = ""
        if vector_result.status == VectorStatus.AVAILABLE:
            for vector_item in vector_result.items:
                chunk = self.store.get_chunk(namespace, vector_item.chunk_id)
                if chunk is None or not _matches_filters(chunk, filters):
                    continue
                item = candidates.get(chunk.chunk_id) or self._item_from_chunk(namespace, chunk)
                item.score_parts["vector"] = float(vector_item.score)
                candidates[chunk.chunk_id] = item
            retrieval_mode = "hybrid_rerank"
        else:
            retrieval_mode = "fts_only"
            if vector_result.status == VectorStatus.CONFIG_MISMATCH:
                degraded_reason = f"Vector index does not match current embedding config. Run knowledge.reindex --namespace {namespace}."
            elif vector_result.message:
                degraded_reason = vector_result.message

        items = list(candidates.values())
        rerank_status = ""
        rerank_started_at = perf_counter()
        if retrieval_mode == "hybrid_rerank" and items:
            ranked_items = self._rank_without_reranker(items)
            rerank_limit = self._reranker_limit(len(ranked_items))
            rerank_candidates = ranked_items[:rerank_limit]
            passages = [item.text for item in rerank_candidates]
            reranked = self.reranker.rerank(query, passages, top_n=rerank_limit)
            rerank_status = str(reranked.status)
            if reranked.status == RerankStatus.AVAILABLE:
                ordered: list[KnowledgeSearchResultItem] = []
                for rerank_item in reranked.items:
                    item = rerank_candidates[rerank_item.index]
                    item.score_parts["rerank"] = float(rerank_item.score)
                    item.score = self._final_score(item)
                    ordered.append(item)
                reranked_ids = {item.chunk_id for item in ordered}
                remainder = [item for item in ranked_items if item.chunk_id not in reranked_ids]
                items = sorted(ordered, key=lambda item: (item.score, item.chunk_id), reverse=True) + remainder
            else:
                items = ranked_items
        else:
            items = self._rank_without_reranker(items)
        rerank_ms = _elapsed_ms(rerank_started_at)

        top_items = _diverse_top_items(items, top_k=top_k, max_per_source=2)
        search_run_id = self.store.record_search_run(
            namespace=namespace,
            query=query,
            filters=dict(filters or {}),
            result_count=len(top_items),
            retrieval_mode=retrieval_mode,
            degraded_reason=degraded_reason,
        )
        return KnowledgeSearchResult(
            namespace=namespace,
            query=query,
            retrieval_mode=retrieval_mode,
            vector_status=vector_status,
            rerank_status=rerank_status,
            degraded_reason=degraded_reason,
            search_run_id=search_run_id,
            fts_ms=fts_ms,
            vector_ms=vector_ms,
            rerank_ms=rerank_ms,
            total_ms=_elapsed_ms(started_at),
            results=top_items,
        )

    def _candidate_limit(self, top_k: int) -> int:
        configured = int(getattr(self.search_config, "candidate_pool", 0) or 0) if self.search_config is not None else 0
        return max(configured, top_k, 1)

    def _reranker_limit(self, item_count: int) -> int:
        if self.reranker_top_n is None:
            return item_count
        return max(1, min(int(self.reranker_top_n), item_count))

    def _final_score(self, item: KnowledgeSearchResultItem) -> float:
        parts = item.score_parts
        if self.search_config is None:
            return sum(float(value) for value in parts.values())
        return (
            float(parts.get("fts") or 0.0) * self.search_config.fts_weight
            + float(parts.get("vector") or 0.0) * self.search_config.vector_weight
            + float(parts.get("metadata") or 0.0) * self.search_config.metadata_weight
            + float(parts.get("rerank") or 0.0) * self.search_config.reranker_weight
        )

    def _with_score(self, item: KnowledgeSearchResultItem | dict) -> KnowledgeSearchResultItem:
        model = item if isinstance(item, KnowledgeSearchResultItem) else KnowledgeSearchResultItem(**item)
        model.score = self._final_score(model)
        return model

    def _rank_without_reranker(self, items: list[KnowledgeSearchResultItem]) -> list[KnowledgeSearchResultItem]:
        ranked = [self._with_score(item) for item in weighted_rerank([item.model_dump() for item in items])]
        return sorted(ranked, key=lambda item: (item.score, item.chunk_id), reverse=True)

    def _item_from_chunk(self, namespace: str, chunk: KnowledgeChunk) -> KnowledgeSearchResultItem:
        item = KnowledgeSearchResultItem(
            chunk_id=chunk.chunk_id,
            source_id=chunk.source_id,
            source_title=self.store.get_source_title(namespace, chunk.source_id),
            text=chunk.text,
            heading=chunk.heading,
            metadata=dict(chunk.metadata),
        )
        evidence_weight = {
            "classical_original": 1.0,
            "historical_commentary": 0.8,
            "modern_commentary": 0.5,
            "marten_interpretation": 0.5,
        }.get(str(chunk.metadata.get("evidence_kind") or ""), 0.0)
        if evidence_weight:
            item.score_parts["metadata"] = evidence_weight
        return item


def _matches_filters(chunk: KnowledgeChunk, filters: dict[str, object] | None) -> bool:
    resolved = dict(filters or {})
    evidence_kind = str(chunk.metadata.get("evidence_kind") or "")
    if "evidence_kind" not in resolved and evidence_kind in {"course_notes", "case_record"}:
        return False
    return all(chunk.metadata.get(key) == value for key, value in resolved.items())


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000.0, 3)


def _diverse_top_items(
    items: list[KnowledgeSearchResultItem],
    *,
    top_k: int,
    max_per_source: int,
) -> list[KnowledgeSearchResultItem]:
    selected: list[KnowledgeSearchResultItem] = []
    source_counts: dict[str, int] = {}
    for item in items:
        count = source_counts.get(item.source_id, 0)
        if count >= max_per_source:
            continue
        selected.append(item)
        source_counts[item.source_id] = count + 1
        if len(selected) >= top_k:
            break
    return selected
