from __future__ import annotations

import math

from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore
from marten_runtime.knowledge.vector_models import VectorQueryResult, VectorResultItem, VectorStatus


def query_vectors(
    store: SQLiteKnowledgeStore,
    *,
    namespace: str,
    embedding_config_hash: str,
    query_vector: list[float],
    top_k: int,
    enabled: bool = True,
    backend: str = "json_cosine",
) -> VectorQueryResult:
    if not enabled:
        return VectorQueryResult(status=VectorStatus.DISABLED, message="vector store disabled")
    if not query_vector:
        return VectorQueryResult(
            status=VectorStatus.QUERY_VECTOR_UNAVAILABLE,
            message="Query embedding is unavailable; using FTS-only retrieval.",
        )
    if backend == "sqlite_vec" and not store.sqlite_vec_available():
        return VectorQueryResult(status=VectorStatus.DISABLED, message="sqlite-vec is not available; using FTS-only retrieval")
    if backend == "sqlite_vec":
        sqlite_vec_result = store.query_sqlite_vec(
            namespace,
            embedding_config_hash,
            query_vector,
            top_k=top_k,
        )
        if sqlite_vec_result.status != VectorStatus.AVAILABLE:
            return sqlite_vec_result
        return VectorQueryResult(
            status=VectorStatus.AVAILABLE,
            items=[
                VectorResultItem(chunk_id=item.chunk_id, score=_distance_to_score(item.score))
                for item in sqlite_vec_result.items
            ],
        )
    records = store.list_embeddings(namespace, embedding_config_hash)
    if not records:
        namespace_hash = store.get_namespace_config_hash(namespace)
        if namespace_hash == embedding_config_hash:
            return VectorQueryResult(status=VectorStatus.AVAILABLE, items=[])
        return VectorQueryResult(
            status=VectorStatus.CONFIG_MISMATCH,
            message=(
                "Current embedding config has no vectors for this namespace. "
                "Run knowledge.reindex --namespace xxx."
            )
        )
    items = [
        VectorResultItem(chunk_id=record.chunk_id, score=_cosine(query_vector, record.vector))
        for record in records
    ]
    items.sort(key=lambda item: (item.score, item.chunk_id), reverse=True)
    return VectorQueryResult(status=VectorStatus.AVAILABLE, items=items[:top_k])


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _distance_to_score(distance: float) -> float:
    return 1.0 / (1.0 + max(0.0, distance))
