from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from marten_runtime.knowledge.corpus import LoadedKnowledgeCorpus


_CITATION_FIELDS = (
    "work",
    "chapter",
    "edition_or_source",
    "source_url",
    "verification_status",
    "license",
    "provenance",
    "corpus_release_id",
)


class KnowledgeCorpusGoldCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    query: str
    expected_source_ids: list[str]
    expected_headings: list[str] = Field(default_factory=list)
    forbidden_source_ids: list[str] = Field(default_factory=list)
    expected_evidence_kinds: list[str] = Field(default_factory=list)
    forbidden_evidence_kinds: list[str] = Field(default_factory=lambda: ["course_notes", "case_record"])
    required_text_any: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_case(self) -> "KnowledgeCorpusGoldCase":
        if not self.case_id.strip() or not self.query.strip() or not self.expected_source_ids:
            raise ValueError("case_id, query and expected_source_ids are required")
        return self


class KnowledgeCorpusGoldSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    release_id: str
    namespace: str
    required_metadata_fields: list[str] = Field(default_factory=lambda: list(_CITATION_FIELDS))
    cases: list[KnowledgeCorpusGoldCase]

    @model_validator(mode="after")
    def validate_dataset(self) -> "KnowledgeCorpusGoldSet":
        if self.schema_version != "knowledge.corpus.gold.v1":
            raise ValueError("schema_version must be knowledge.corpus.gold.v1")
        case_ids = [case.case_id for case in self.cases]
        if not self.cases or len(case_ids) != len(set(case_ids)):
            raise ValueError("gold cases must be non-empty and uniquely identified")
        if len(self.required_metadata_fields) != len(set(self.required_metadata_fields)):
            raise ValueError("required_metadata_fields must be unique")
        return self


def load_corpus_gold_set(path: str | Path) -> tuple[KnowledgeCorpusGoldSet, str]:
    raw = Path(path).read_bytes()
    return KnowledgeCorpusGoldSet(**json.loads(raw.decode("utf-8"))), hashlib.sha256(raw).hexdigest()


def evaluate_corpus_retrieval(
    *,
    corpus: LoadedKnowledgeCorpus,
    gold_set: KnowledgeCorpusGoldSet,
    gold_sha256: str,
    service,  # noqa: ANN001
    code_commit: str,
    code_tree_sha256: str,
    code_tree_file_count: int,
    top_k: int = 5,
) -> dict[str, object]:
    if gold_set.release_id != corpus.manifest.release_id or gold_set.namespace != corpus.manifest.namespace:
        raise ValueError("gold set release or namespace does not match corpus manifest")
    return evaluate_namespace_retrieval(
        gold_set=gold_set,
        gold_sha256=gold_sha256,
        service=service,
        code_commit=code_commit,
        code_tree_sha256=code_tree_sha256,
        code_tree_file_count=code_tree_file_count,
        manifest_sha256=corpus.manifest_sha256,
        top_k=top_k,
    )


def evaluate_namespace_retrieval(
    *,
    gold_set: KnowledgeCorpusGoldSet,
    gold_sha256: str,
    service,  # noqa: ANN001
    code_commit: str,
    code_tree_sha256: str,
    code_tree_file_count: int,
    manifest_sha256: str = "runtime-namespace",
    top_k: int = 5,
) -> dict[str, object]:
    case_results: list[dict[str, object]] = []
    reciprocal_rank_sum = 0.0
    recall_counts = {1: 0, 3: 0, 5: 0}
    expected_first_count = 0
    citation_complete_count = 0
    empty_count = 0
    false_positive_count = 0
    heading_match_count = 0
    first_evidence_kind_count = 0
    required_text_match_count = 0
    duplicate_source_ratios: list[float] = []
    for case in gold_set.cases:
        search = service.search(namespace=gold_set.namespace, query=case.query, top_k=top_k)
        if not search.get("ok"):
            raise RuntimeError(
                f"corpus retrieval failed for {case.case_id}: "
                f"{search.get('error_code') or search.get('message') or 'unknown error'}"
            )
        results = list(search.get("results") or [])
        actual_source_ids = [str(item.get("source_id") or "") for item in results]
        actual_evidence_kinds = [
            str(dict(item.get("metadata") or {}).get("evidence_kind") or "")
            for item in results
        ]
        expected_ranks = [
            index + 1
            for index, source_id in enumerate(actual_source_ids)
            if source_id in case.expected_source_ids
        ]
        best_rank = min(expected_ranks) if expected_ranks else 0
        if best_rank:
            reciprocal_rank_sum += 1.0 / best_rank
            for k in recall_counts:
                recall_counts[k] += int(best_rank <= k)
        expected_first_count += int(best_rank == 1)
        empty_count += int(not results)
        forbidden_hits = sorted(set(actual_source_ids) & set(case.forbidden_source_ids))
        forbidden_evidence_hits = sorted(
            set(actual_evidence_kinds) & set(case.forbidden_evidence_kinds)
        )
        false_positive_count += int(bool(forbidden_hits or forbidden_evidence_hits))
        expected_items = [
            item for item in results if str(item.get("source_id") or "") in case.expected_source_ids
        ]
        citation_complete = bool(expected_items) and all(
            all(
                str(dict(item.get("metadata") or {}).get(field) or "").strip()
                for field in gold_set.required_metadata_fields
            )
            for item in expected_items
        )
        citation_complete_count += int(citation_complete)
        heading_match = not case.expected_headings or any(
            str(item.get("heading") or "") in case.expected_headings for item in expected_items
        )
        heading_match_count += int(bool(heading_match and expected_items))
        first_evidence_kind_match = bool(results) and (
            not case.expected_evidence_kinds
            or actual_evidence_kinds[0] in case.expected_evidence_kinds
        )
        first_evidence_kind_count += int(first_evidence_kind_match)
        required_text_match = not case.required_text_any or any(
            phrase in str(item.get("text") or "")
            for phrase in case.required_text_any
            for item in results[:3]
        )
        required_text_match_count += int(required_text_match)
        duplicate_source_ratio = (
            (len(actual_source_ids) - len(set(actual_source_ids))) / len(actual_source_ids)
            if actual_source_ids
            else 0.0
        )
        duplicate_source_ratios.append(duplicate_source_ratio)
        case_results.append(
            {
                "case_id": case.case_id,
                "query": case.query,
                "expected_source_ids": list(case.expected_source_ids),
                "expected_headings": list(case.expected_headings),
                "actual_rank": best_rank,
                "actual_source_ids": actual_source_ids,
                "forbidden_hits": forbidden_hits,
                "forbidden_evidence_hits": forbidden_evidence_hits,
                "citation_complete": citation_complete,
                "heading_match": bool(heading_match and expected_items),
                "first_evidence_kind_match": first_evidence_kind_match,
                "required_text_match": required_text_match,
                "duplicate_source_ratio": duplicate_source_ratio,
                "retrieval_mode": str(search.get("retrieval_mode") or ""),
                "vector_status": str(search.get("vector_status") or ""),
                "rerank_status": str(search.get("rerank_status") or ""),
                "degraded_reason": str(search.get("degraded_reason") or ""),
                "results": results,
            }
        )
    total = len(case_results)
    denominator = float(total or 1)
    metrics = {
        "case_count": total,
        "recall_at_1": recall_counts[1] / denominator,
        "recall_at_3": recall_counts[3] / denominator,
        "recall_at_5": recall_counts[5] / denominator,
        "mrr": reciprocal_rank_sum / denominator,
        "expected_source_first_rate": expected_first_count / denominator,
        "citation_metadata_complete_rate": citation_complete_count / denominator,
        "heading_match_rate": heading_match_count / denominator,
        "empty_result_count": empty_count,
        "false_positive_case_count": false_positive_count,
        "first_evidence_kind_match_rate": first_evidence_kind_count / denominator,
        "required_text_match_rate": required_text_match_count / denominator,
        "mean_duplicate_source_ratio": sum(duplicate_source_ratios) / denominator,
    }
    knowledge_config = _retrieval_config_snapshot(service, top_k=top_k)
    knowledge_config_sha256 = hashlib.sha256(
        json.dumps(knowledge_config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    knowledge_snapshot = _knowledge_snapshot(service, namespace=gold_set.namespace)
    return {
        "schema_version": "knowledge.corpus.report.v1",
        "release_id": gold_set.release_id,
        "namespace": gold_set.namespace,
        "manifest_sha256": manifest_sha256,
        "gold_sha256": gold_sha256,
        "required_metadata_fields": list(gold_set.required_metadata_fields),
        "knowledge_config_sha256": knowledge_config_sha256,
        "knowledge_config": knowledge_config,
        "knowledge_snapshot": knowledge_snapshot,
        "embedding_config_hash": service.embedding_config_hash,
        "embedding_model_id": service.config.embedding.model,
        "reranker_model_id": service.config.reranker.model,
        "vector_store_backend": service.config.vector_store.backend,
        "code_commit": code_commit,
        "code_tree_sha256": code_tree_sha256,
        "code_tree_file_count": code_tree_file_count,
        "metrics": metrics,
        "cases": case_results,
    }


def corpus_retrieval_report_markdown(report: dict[str, object]) -> str:
    metrics = dict(report.get("metrics") or {})
    rows = [
        "# Knowledge Corpus Retrieval Report",
        "",
        f"- Release: `{report.get('release_id')}`",
        f"- Manifest SHA256: `{report.get('manifest_sha256')}`",
        f"- Gold SHA256: `{report.get('gold_sha256')}`",
        f"- Base commit: `{report.get('code_commit')}`",
        f"- Candidate tree SHA256: `{report.get('code_tree_sha256')}` ({report.get('code_tree_file_count')} files)",
        f"- Knowledge config SHA256: `{report.get('knowledge_config_sha256')}`",
        (
            f"- Knowledge snapshot SHA256: `{dict(report.get('knowledge_snapshot') or {}).get('sha256')}` "
            f"({dict(report.get('knowledge_snapshot') or {}).get('source_count')} sources, "
            f"{dict(report.get('knowledge_snapshot') or {}).get('chunk_count')} chunks, "
            f"{dict(report.get('knowledge_snapshot') or {}).get('current_embedding_count')} current embeddings)"
        ),
        f"- Embedding config: `{report.get('embedding_config_hash')}`",
        f"- Models: `{report.get('embedding_model_id')}` / `{report.get('reranker_model_id')}`",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for name, value in metrics.items():
        rows.append(f"| {name} | {value:.4f} |" if isinstance(value, float) else f"| {name} | {value} |")
    rows.extend(["", "| Case | Rank | Mode | Vector | Rerank | Citation |", "| --- | ---: | --- | --- | --- | --- |"])
    for case in list(report.get("cases") or []):
        rows.append(
            f"| {case.get('case_id')} | {case.get('actual_rank')} | {case.get('retrieval_mode')} | "
            f"{case.get('vector_status')} | {case.get('rerank_status')} | {case.get('citation_complete')} |"
        )
    return "\n".join(rows) + "\n"


def _knowledge_snapshot(service, *, namespace: str) -> dict[str, object]:  # noqa: ANN001
    source_count = service.store.count_sources(namespace)
    source_rows, _ = service.store.list_source_summaries(
        namespace,
        page=1,
        page_size=max(1, source_count),
    )
    sources = sorted(
        (
            {
                "source_id": str(item.get("source_id") or ""),
                "title": str(item.get("title") or ""),
                "kind": str(item.get("kind") or ""),
                "uri": str(item.get("uri") or ""),
                "version": str(item.get("version") or ""),
                "metadata": dict(item.get("metadata") or {}),
            }
            for item in source_rows
        ),
        key=lambda item: item["source_id"],
    )
    chunks = service.store.list_chunks(namespace)
    embedded_chunk_ids = {
        record.chunk_id
        for record in service.store.list_embeddings(namespace, service.embedding_config_hash)
    }
    logical_chunks = sorted(
        (
            {
                "source_id": chunk.source_id,
                "ordinal": chunk.ordinal,
                "heading": chunk.heading,
                "text": chunk.text,
                "token_estimate": chunk.token_estimate,
                "metadata": dict(chunk.metadata),
                "current_embedding": chunk.chunk_id in embedded_chunk_ids,
            }
            for chunk in chunks
        ),
        key=lambda item: (item["source_id"], item["ordinal"]),
    )
    snapshot = {
        "namespace": namespace,
        "embedding_config_hash": service.embedding_config_hash,
        "sources": sources,
        "chunks": logical_chunks,
    }
    digest = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "sha256": digest,
        "source_count": len(sources),
        "chunk_count": len(logical_chunks),
        "current_embedding_count": sum(int(item["current_embedding"]) for item in logical_chunks),
    }


def _retrieval_config_snapshot(service, *, top_k: int) -> dict[str, object]:  # noqa: ANN001
    config = service.config
    return {
        "file_encoding": str(config.file_encoding),
        "evaluation_top_k": int(top_k),
        "chunking": {
            "target_chars": int(config.chunking.target_chars),
            "overlap_chars": int(config.chunking.overlap_chars),
            "max_chars": int(config.chunking.max_chars),
            "batch_size": int(config.chunking.batch_size),
        },
        "embedding": {
            "enabled": bool(config.embedding.enabled),
            "provider": str(config.embedding.provider),
            "model": str(config.embedding.model),
            "dimension": int(config.embedding.dimension),
            "use_fp16": bool(config.embedding.use_fp16),
        },
        "reranker": {
            "enabled": bool(config.reranker.enabled),
            "provider": str(config.reranker.provider),
            "model": str(config.reranker.model),
            "use_fp16": bool(config.reranker.use_fp16),
            "top_n": int(config.reranker.top_n),
        },
        "vector_store": {
            "enabled": bool(config.vector_store.enabled),
            "backend": str(config.vector_store.backend),
        },
        "search": {
            "default_top_k": int(config.search.default_top_k),
            "candidate_pool": int(config.search.candidate_pool),
            "fts_weight": float(config.search.fts_weight),
            "vector_weight": float(config.search.vector_weight),
            "metadata_weight": float(config.search.metadata_weight),
            "reranker_weight": float(config.search.reranker_weight),
        },
    }
