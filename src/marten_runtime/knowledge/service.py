from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, RLock, Thread
from time import perf_counter

from marten_runtime.knowledge.chunking import chunk_text
from marten_runtime.knowledge.config import (
    KnowledgeChunkingConfig,
    KnowledgeEmbeddingConfig,
    KnowledgeRuntimeConfig,
    KnowledgeSearchConfig,
    embedding_config_hash,
)
from marten_runtime.knowledge.embeddings import EmbeddingStatus, FakeEmbeddingAdapter, LocalModelEmbeddingAdapter
from marten_runtime.knowledge.jobs import KnowledgeIngestJobStore
from marten_runtime.knowledge.models import KnowledgeChunk, KnowledgeSource
from marten_runtime.knowledge.rerankers import FakeReranker, LocalModelReranker, RerankStatus
from marten_runtime.knowledge.retrieval import KnowledgeRetriever
from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore


_EVIDENCE_KINDS = frozenset(
    {
        "classical_original",
        "historical_commentary",
        "modern_commentary",
        "marten_interpretation",
        "course_notes",
        "case_record",
    }
)
_CLASSICAL_REQUIRED_METADATA = frozenset(
    {"work", "chapter", "edition_or_source", "source_url", "verification_status"}
)


@dataclass(frozen=True)
class _EmbedChunksResult:
    status: EmbeddingStatus
    embedded_count: int
    message: str = ""


@dataclass(frozen=True)
class _PreparedEmbeddings:
    status: EmbeddingStatus
    vectors: tuple[tuple[float, ...], ...] = ()
    message: str = ""


class KnowledgeService:
    def __init__(self, config: KnowledgeRuntimeConfig) -> None:
        self.config = config
        self.store = SQLiteKnowledgeStore(config.db_path)
        self.jobs = KnowledgeIngestJobStore(self.store, staging_root=_knowledge_staging_root(config))
        self._job_recovery_status = self.jobs.reconcile_startup()
        self._source_locks_guard = Lock()
        self._source_locks: dict[tuple[str, str], tuple[Lock, int]] = {}
        # Local embedding and reranker models are large and their lazy loaders are not thread-safe.
        self._model_runtime_lock = RLock()
        self._prewarm_status: dict[str, object] = {
            "requested": False,
            "ready": not config.prewarm_on_start,
            "embedding_status": "not_requested",
            "reranker_status": "not_requested",
            "elapsed_ms": 0.0,
        }
        self.embedding_profiles = config.resolved_embedding_profiles()
        self.embedding_profile_hashes = {
            profile_id: embedding_config_hash(profile)
            for profile_id, profile in self.embedding_profiles.items()
        }
        self.embedding_config_hash = self.embedding_profile_hashes["default"]
        self.embedding_adapter = self._build_embedding_adapter(config.embedding)
        self._embedding_adapters = {"default": self.embedding_adapter}
        self.reranker_adapter = (
            FakeReranker(model_id=config.reranker.model)
            if config.reranker.provider == "fake"
            else LocalModelReranker(config.reranker)
        )
        self.retriever = KnowledgeRetriever(
            self.store,
            reranker=self.reranker_adapter,
            vector_store_enabled=config.vector_store.enabled,
            vector_store_backend=config.vector_store.backend,
            search_config=config.search,
            reranker_top_n=config.reranker.top_n,
        )

    def ingest_text(self, *, namespace: str, source: dict[str, object]) -> dict[str, object]:
        self.unload_idle_models()
        namespace = _namespace(namespace, self.config.default_namespace)
        text = str(source.get("text") or "").strip()
        if not text:
            return {"ok": False, "error_code": "KNOWLEDGE_SOURCE_TEXT_REQUIRED", "message": "source.text is required for text ingest"}
        profile_id = self._source_embedding_profile_id(namespace, source)
        source_model, chunks = self._prepare_source_chunks(namespace=namespace, source=source, text=text)
        self.store.upsert_source(source_model)
        self.store.replace_chunks(namespace, source_model.source_id, chunks)
        embedding_status = self._embed_chunks(namespace, chunks, embedding_profile_id=profile_id)
        return {
            "ok": True,
            "action": "ingest_text",
            "namespace": namespace,
            "source_id": source_model.source_id,
            "chunk_count": len(chunks),
            "embedding_status": _public_embedding_status(embedding_status),
            "vector_store_status": "indexed" if embedding_status == EmbeddingStatus.AVAILABLE else "disabled",
        }

    def ingest_file(
        self,
        *,
        namespace: str,
        file_path: str,
        source: dict[str, object],
        staged_file_path: str = "",
    ) -> dict[str, object]:
        self.unload_idle_models()
        namespace = _namespace(namespace, self.config.default_namespace)
        path = self._resolve_file_path(file_path)
        if staged_file_path:
            self.jobs.validate_staged_file(staged_file_path=staged_file_path, file_path=path)
        source_title = str(source.get("title") or path.name)
        job_id = self.jobs.create_job(
            namespace=namespace,
            source_title=source_title,
            staged_file_path=staged_file_path,
        )
        thread = Thread(
            target=self._run_file_ingest_job,
            kwargs={
                "namespace": namespace,
                "job_id": job_id,
                "path": path,
                "source": {**source, "title": source_title},
            },
            name=f"knowledge-ingest-{job_id}",
            daemon=True,
        )
        thread.start()
        return {
            "ok": True,
            "action": "ingest_file",
            "namespace": namespace,
            "job_id": job_id,
            "status": "queued",
            "message": "已开始写入知识库，可用 knowledge.ingest_status 查询进度",
        }

    def preview_file(
        self,
        *,
        namespace: str,
        file_path: str,
        source: dict[str, object],
        sample_limit: int | None = None,
        sample_chars: int | None = None,
    ) -> dict[str, object]:
        namespace = _namespace(namespace, self.config.default_namespace)
        path = self._resolve_file_path(file_path)
        text = _read_text_file(path, encoding=self.config.file_encoding)
        source_model, chunks = self._prepare_source_chunks(
            namespace=namespace,
            source=source,
            text=text,
        )
        chunking_config = self._source_chunking_config(source_model.metadata)
        profile_id = self._source_embedding_profile_id(namespace, source)
        selected_chunks = chunks if sample_limit is None else chunks[:sample_limit]
        lengths = [len(chunk.text) for chunk in chunks]
        return {
            "ok": True,
            "namespace": namespace,
            "source_id": source_model.source_id,
            "title": source_model.title,
            "uri": source_model.uri,
            "version": source_model.version,
            "metadata": dict(source_model.metadata),
            "index_profile": {
                "chunking": chunking_config.model_dump(mode="json"),
                "embedding": next(
                    item for item in self.embedding_profile_summaries()
                    if item["profile_id"] == profile_id
                ),
            },
            "chunk_count": len(chunks),
            "chunk_length": {
                "min": min(lengths, default=0),
                "max": max(lengths, default=0),
                "average": round(sum(lengths) / len(lengths), 2) if lengths else 0.0,
            },
            "chunks": [
                {
                    "ordinal": chunk.ordinal,
                    "heading": chunk.heading,
                    "token_estimate": chunk.token_estimate,
                    "text_preview": chunk.text if sample_chars is None else chunk.text[:sample_chars],
                }
                for chunk in selected_chunks
            ],
        }

    def ingest_status(self, *, namespace: str, job_id: str) -> dict[str, object]:
        self.unload_idle_models()
        namespace = _namespace(namespace, self.config.default_namespace)
        job = self.jobs.get(namespace=namespace, job_id=job_id)
        if job is None:
            return {"ok": False, "error_code": "KNOWLEDGE_JOB_NOT_FOUND", "job_id": job_id}
        return {"ok": True, **job}

    @property
    def job_recovery_status(self) -> dict[str, object]:
        return {
            **self._job_recovery_status,
            "cleanup_failures": list(self.jobs.cleanup_failures),
        }

    def cancel_ingest(self, *, namespace: str, job_id: str) -> dict[str, object]:
        return self.jobs.cancel(namespace=_namespace(namespace, self.config.default_namespace), job_id=job_id)

    def search(
        self,
        *,
        namespace: str,
        query: str,
        top_k: int | None = None,
        filters: dict[str, object] | None = None,
        search_config: KnowledgeSearchConfig | None = None,
    ) -> dict[str, object]:
        self.unload_idle_models()
        namespace = _namespace(namespace, self.config.default_namespace)
        query = str(query or "").strip()
        if not query:
            return {"ok": False, "error_code": "KNOWLEDGE_QUERY_REQUIRED", "message": "query is required"}
        resolved_search_config = search_config or self.config.search
        resolved_top_k = resolved_search_config.default_top_k if top_k is None else int(top_k)
        if resolved_top_k < 1:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_TOP_K_INVALID",
                "top_k": resolved_top_k,
                "message": "top_k must be >= 1",
            }
        with self._model_runtime_lock:
            embedding_started_at = perf_counter()
            profile_id = self._namespace_embedding_profile_id(namespace)
            profile_hash = self.embedding_profile_hashes[profile_id]
            query_result = self._embedding_adapter(profile_id).embed_texts([query])
            if query_result.status == EmbeddingStatus.MISSING_MODEL:
                return {
                    "ok": False,
                    "error_code": "KNOWLEDGE_QUERY_EMBEDDING_UNAVAILABLE",
                    "embedding_status": _public_embedding_status(query_result.status),
                    "message": query_result.message or "query embedding is unavailable",
                }
            query_vector = query_result.vectors[0] if query_result.vectors else []
            embedding_ms = round((perf_counter() - embedding_started_at) * 1000.0, 3)
            retriever = self.retriever if resolved_search_config is self.config.search else KnowledgeRetriever(
                self.store,
                reranker=self.reranker_adapter,
                vector_store_enabled=self.config.vector_store.enabled,
                vector_store_backend=self.config.vector_store.backend,
                search_config=resolved_search_config,
                reranker_top_n=self.config.reranker.top_n,
            )
            result = retriever.search(
                namespace=namespace,
                query=query,
                embedding_config_hash=profile_hash,
                query_vector=query_vector,
                top_k=resolved_top_k,
                filters=filters,
            )
            self.unload_idle_models()
        payload = result.model_dump(mode="json")
        payload["embedding_ms"] = embedding_ms
        payload["total_ms"] = round(float(payload.get("total_ms") or 0.0) + embedding_ms, 3)
        return {"ok": True, **payload}

    def get_chunk(self, *, namespace: str, chunk_id: str) -> dict[str, object]:
        self.unload_idle_models()
        chunk = self.store.get_chunk(_namespace(namespace, self.config.default_namespace), chunk_id)
        if chunk is None:
            return {"ok": False, "error_code": "KNOWLEDGE_CHUNK_NOT_FOUND", "chunk_id": chunk_id}
        return {"ok": True, "chunk": chunk.model_dump(mode="json")}

    def delete_source(self, *, namespace: str, source_id: str) -> dict[str, object]:
        self.unload_idle_models()
        namespace = _namespace(namespace, self.config.default_namespace)
        with self._source_lock(namespace, source_id):
            result = self.store.delete_source(namespace, source_id)
        return {"ok": True, "namespace": namespace, **result.model_dump(mode="json")}

    def approve_source(
        self,
        *,
        draft_namespace: str,
        source_id: str,
        target_namespace: str,
    ) -> dict[str, object]:
        self.unload_idle_models()
        draft_namespace = _namespace(draft_namespace, self.config.default_namespace)
        target_namespace = _namespace(target_namespace, self.config.default_namespace)
        if draft_namespace == target_namespace:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_APPROVAL_NAMESPACE_INVALID",
                "message": "draft and target namespaces must differ",
            }
        draft_source = self.store.get_source(draft_namespace, source_id)
        if draft_source is None:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_SOURCE_NOT_FOUND",
                "message": "draft source was not found",
            }
        draft_chunks = self.store.list_chunks(draft_namespace, source_id=source_id)
        if not draft_chunks:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_SOURCE_HAS_NO_CHUNKS",
                "message": "draft source has no active chunks",
            }
        evidence_kind = str(draft_source.metadata.get("evidence_kind") or "")
        chunk_evidence_kinds = {
            str(chunk.metadata.get("evidence_kind") or "") for chunk in draft_chunks
        }
        if evidence_kind not in _EVIDENCE_KINDS or not chunk_evidence_kinds <= _EVIDENCE_KINDS:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_APPROVAL_EVIDENCE_KIND_REQUIRED",
                "message": "source and chunks require a valid evidence_kind before approval",
            }
        if evidence_kind in {"classical_original", "historical_commentary"}:
            missing = sorted(
                name
                for name in _CLASSICAL_REQUIRED_METADATA
                if not str(draft_source.metadata.get(name) or "").strip()
            )
            if missing:
                return {
                    "ok": False,
                    "error_code": "KNOWLEDGE_APPROVAL_CLASSICAL_METADATA_REQUIRED",
                    "message": "classical source metadata is incomplete: " + ", ".join(missing),
                }
        draft_profile_id = self._namespace_embedding_profile_id(draft_namespace)
        target_profile_id = self._namespace_embedding_profile_id(target_namespace)
        if self.store.count_chunks(target_namespace) > 0 and draft_profile_id != target_profile_id:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_APPROVAL_PROFILE_MISMATCH",
                "message": "draft and target namespaces use different embedding profiles",
            }
        target_profile_id = draft_profile_id
        profile_hash = self.embedding_profile_hashes[draft_profile_id]
        target_source_id = (
            self.store.find_source_id_by_uri_version(
                target_namespace,
                draft_source.uri,
                draft_source.version,
            )
            or source_id
        )
        approved_at = datetime.now(timezone.utc).isoformat()
        approval_metadata = {
            "review_status": "reviewed",
            "approval_status": "approved",
            "approved_at": approved_at,
            "approved_from_namespace": draft_namespace,
            "draft_source_id": source_id,
        }
        approved_source = KnowledgeSource.new(
            namespace=target_namespace,
            source_id=target_source_id,
            title=_approved_source_title(draft_source.title),
            kind=draft_source.kind,
            uri=draft_source.uri,
            version=draft_source.version,
            metadata={**draft_source.metadata, **approval_metadata},
        )
        approved_chunks = [
            KnowledgeChunk.new(
                namespace=target_namespace,
                source_id=target_source_id,
                ordinal=chunk.ordinal,
                heading=chunk.heading,
                text=chunk.text,
                token_estimate=chunk.token_estimate,
                metadata={**chunk.metadata, **approval_metadata},
            )
            for chunk in draft_chunks
        ]
        with self._source_lock(target_namespace, target_source_id):
            if self.config.embedding.enabled:
                records = {
                    record.chunk_id: record
                    for record in self.store.list_embeddings(
                        draft_namespace,
                        profile_hash,
                    )
                }
                missing = [chunk.chunk_id for chunk in draft_chunks if chunk.chunk_id not in records]
                if missing:
                    return {
                        "ok": False,
                        "error_code": "KNOWLEDGE_APPROVAL_EMBEDDINGS_INCOMPLETE",
                        "message": "draft source embeddings are incomplete",
                        "missing_embedding_count": len(missing),
                    }
                ordered_records = [records[chunk.chunk_id] for chunk in draft_chunks]
                first_record = ordered_records[0]
                self.store.replace_source_bundle(
                    source=approved_source,
                    chunks=approved_chunks,
                    vectors=[record.vector for record in ordered_records],
                    model_id=first_record.model_id,
                    dimension=first_record.dimension,
                    embedding_config_hash=profile_hash,
                    embedding_profile_id=target_profile_id,
                )
            else:
                self.store.upsert_source(approved_source)
                self.store.replace_chunks(target_namespace, target_source_id, approved_chunks)
        with self._source_lock(draft_namespace, source_id):
            deleted = self.store.delete_source(draft_namespace, source_id)
        return {
            "ok": True,
            "action": "approve_source",
            "draft_namespace": draft_namespace,
            "target_namespace": target_namespace,
            "source_id": target_source_id,
            "title": approved_source.title,
            "chunk_count": len(approved_chunks),
            "deleted_draft_chunk_count": deleted.deleted_chunk_count,
            "approved_at": approved_at,
        }

    def reindex(
        self,
        *,
        namespace: str,
        source_id: str | None = None,
        embedding_profile_id: str | None = None,
    ) -> dict[str, object]:
        self.unload_idle_models()
        namespace = _namespace(namespace, self.config.default_namespace)
        if source_id is not None:
            source = self.store.get_source(namespace, source_id)
            if source is None:
                return {
                    "ok": False,
                    "error_code": "KNOWLEDGE_SOURCE_NOT_FOUND",
                    "namespace": namespace,
                    "source_id": source_id,
                    "message": "source is not active",
                }
        chunks = self.store.list_chunks(namespace, source_id=source_id)
        if source_id is not None and not chunks:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_SOURCE_HAS_NO_CHUNKS",
                "namespace": namespace,
                "source_id": source_id,
                "message": "source has no active chunks to reindex",
            }
        current_profile_id = self._namespace_embedding_profile_id(namespace)
        requested_profile_id = str(embedding_profile_id or current_profile_id).strip()
        if requested_profile_id not in self.embedding_profiles:
            return {
                "ok": False,
                "action": "reindex",
                "error_code": "KNOWLEDGE_EMBEDDING_PROFILE_INVALID",
                "namespace": namespace,
                "embedding_profile_id": requested_profile_id,
                "message": "embedding profile is not configured",
            }
        if source_id is not None and requested_profile_id != current_profile_id:
            return {
                "ok": False,
                "action": "reindex",
                "error_code": "KNOWLEDGE_EMBEDDING_PROFILE_REQUIRES_NAMESPACE_REINDEX",
                "namespace": namespace,
                "source_id": source_id,
                "message": "embedding profile changes require namespace reindex",
            }
        if source_id is None:
            embedding_status = self._replace_namespace_embedding_profile(
                namespace=namespace,
                chunks=chunks,
                embedding_profile_id=requested_profile_id,
            )
        else:
            embedding_status = self._embed_chunks(
                namespace,
                chunks,
                embedding_profile_id=requested_profile_id,
            )
        profile_hash = self.embedding_profile_hashes[requested_profile_id]
        if embedding_status != EmbeddingStatus.AVAILABLE:
            return {
                "ok": False,
                "action": "reindex",
                "error_code": "KNOWLEDGE_REINDEX_EMBEDDING_UNAVAILABLE",
                "namespace": namespace,
                "source_id": source_id or "",
                "chunk_count": len(chunks),
                "embedding_status": _public_embedding_status(embedding_status),
                "embedding_config_hash": profile_hash,
                "embedding_profile_id": requested_profile_id,
                "message": "embedding is unavailable; reindex did not update vectors",
            }
        return {
            "ok": True,
            "action": "reindex",
            "namespace": namespace,
            "source_id": source_id or "",
            "chunk_count": len(chunks),
            "embedding_status": _public_embedding_status(embedding_status),
            "embedding_config_hash": profile_hash,
            "embedding_profile_id": requested_profile_id,
        }

    def stats(self, *, namespace: str) -> dict[str, object]:
        self.unload_idle_models()
        namespace = _namespace(namespace, self.config.default_namespace)
        return {
            "ok": True,
            "namespace": namespace,
            "source_count": self.store.count_sources(namespace),
            "chunk_count": self.store.count_chunks(namespace),
            "embedding_config_hash": self.store.get_namespace_config_hash(namespace) or "",
            "embedding_profile_id": self._namespace_embedding_profile_id(namespace),
            "embedding_profiles": self.embedding_profile_summaries(),
            "chunking_defaults": self.config.chunking.model_dump(mode="json"),
            "search_defaults": self.config.search.model_dump(mode="json"),
        }

    def embedding_profile_summaries(self) -> list[dict[str, object]]:
        return [
            {
                "profile_id": profile_id,
                "provider": profile.provider,
                "model": profile.model,
                "dimension": profile.dimension,
                "enabled": profile.enabled,
                "config_hash": self.embedding_profile_hashes[profile_id],
            }
            for profile_id, profile in self.embedding_profiles.items()
        ]

    def validate_embedding_profile(self, *, namespace: str, embedding_profile_id: str) -> dict[str, object]:
        namespace = _namespace(namespace, self.config.default_namespace)
        profile_id = str(embedding_profile_id or "default").strip()
        if profile_id not in self.embedding_profiles:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_EMBEDDING_PROFILE_INVALID",
                "message": "embedding profile is not configured",
            }
        current = self.store.get_namespace_embedding_profile_id(namespace)
        if current and current != profile_id and self.store.count_chunks(namespace) > 0:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_EMBEDDING_PROFILE_MISMATCH",
                "message": "namespace already uses a different embedding profile; run namespace reindex first",
                "embedding_profile_id": current,
            }
        return {"ok": True, "embedding_profile_id": profile_id}

    def model_status(self) -> dict[str, object]:
        self.unload_idle_models()
        ttl = self.config.model_idle_ttl_seconds
        return {
            "ok": True,
            "action": "model_status",
            "idle_ttl_seconds": ttl,
            "prewarm": dict(self._prewarm_status),
            "embedding": self.embedding_adapter.model_status(idle_ttl_seconds=ttl),
            "reranker": self.reranker_adapter.model_status(idle_ttl_seconds=ttl),
        }

    @property
    def ready(self) -> bool:
        return bool(self._prewarm_status.get("ready"))

    def prewarm_models(self) -> dict[str, object]:
        started_at = perf_counter()
        with self._model_runtime_lock:
            embedding = self.embedding_adapter.embed_texts(["知识模型预热"])
            reranker = self.reranker_adapter.rerank(
                "知识模型预热",
                ["用于确认本地重排模型已经加载。"],
                top_n=1,
            )
        embedding_status = str(embedding.status)
        reranker_status = str(reranker.status)
        ready = (
            embedding.status == EmbeddingStatus.AVAILABLE
            and reranker.status == RerankStatus.AVAILABLE
        )
        self._prewarm_status = {
            "requested": True,
            "ready": ready,
            "embedding_status": embedding_status,
            "reranker_status": reranker_status,
            "elapsed_ms": round((perf_counter() - started_at) * 1000.0, 3),
        }
        return {"ok": ready, "action": "prewarm_models", **self._prewarm_status}

    def unload_models(self) -> dict[str, object]:
        with self._model_runtime_lock:
            embedding_unloaded = any([adapter.unload() for adapter in self._all_embedding_adapters()])
            reranker_unloaded = self.reranker_adapter.unload()
            ttl = self.config.model_idle_ttl_seconds
            return {
                "ok": True,
                "action": "unload_models",
                "embedding_unloaded": embedding_unloaded,
                "reranker_unloaded": reranker_unloaded,
                "embedding": self.embedding_adapter.model_status(idle_ttl_seconds=ttl),
                "reranker": self.reranker_adapter.model_status(idle_ttl_seconds=ttl),
            }

    def unload_idle_models(self) -> dict[str, object]:
        with self._model_runtime_lock:
            ttl = self.config.model_idle_ttl_seconds
            if ttl <= 0:
                return {"embedding_unloaded": False, "reranker_unloaded": False}
            return {
                "embedding_unloaded": any([
                    _unload_if_idle(adapter, ttl) for adapter in self._all_embedding_adapters()
                ]),
                "reranker_unloaded": _unload_if_idle(self.reranker_adapter, ttl),
            }

    @staticmethod
    def _build_embedding_adapter(config: KnowledgeEmbeddingConfig):  # noqa: ANN205
        return (
            FakeEmbeddingAdapter(dimension=config.dimension, model_id=config.model)
            if config.provider == "fake"
            else LocalModelEmbeddingAdapter(config)
        )

    def _embedding_adapter(self, profile_id: str):  # noqa: ANN202
        if profile_id == "default":
            return self.embedding_adapter
        adapter = self._embedding_adapters.get(profile_id)
        if adapter is None:
            adapter = self._build_embedding_adapter(self.embedding_profiles[profile_id])
            self._embedding_adapters[profile_id] = adapter
        return adapter

    def _all_embedding_adapters(self) -> list[object]:
        adapters = [self.embedding_adapter]
        adapters.extend(
            adapter for profile_id, adapter in self._embedding_adapters.items()
            if profile_id != "default"
        )
        return adapters

    def _namespace_embedding_profile_id(self, namespace: str) -> str:
        profile_id = self.store.get_namespace_embedding_profile_id(namespace) or "default"
        return profile_id if profile_id in self.embedding_profiles else "default"

    def _source_embedding_profile_id(self, namespace: str, source: dict[str, object]) -> str:
        metadata = dict(source.get("metadata") or {})
        index_profile = dict(metadata.get("index_profile") or {})
        requested = str(index_profile.get("embedding_profile_id") or "").strip()
        profile_id = requested or self._namespace_embedding_profile_id(namespace)
        validation = self.validate_embedding_profile(
            namespace=namespace,
            embedding_profile_id=profile_id,
        )
        if not validation.get("ok"):
            raise ValueError(str(validation.get("message") or "invalid embedding profile"))
        return profile_id

    def _source_chunking_config(self, metadata: dict[str, object]) -> KnowledgeChunkingConfig:
        index_profile = dict(metadata.get("index_profile") or {})
        values = dict(index_profile.get("chunking") or {})
        if not values:
            return self.config.chunking
        return KnowledgeChunkingConfig(
            target_chars=int(values.get("target_chars", self.config.chunking.target_chars)),
            overlap_chars=int(values.get("overlap_chars", self.config.chunking.overlap_chars)),
            max_chars=int(values.get("max_chars", self.config.chunking.max_chars)),
            batch_size=self.config.chunking.batch_size,
        )

    def _replace_namespace_embedding_profile(
        self,
        *,
        namespace: str,
        chunks: list[KnowledgeChunk],
        embedding_profile_id: str,
    ) -> EmbeddingStatus:
        profile = self.embedding_profiles[embedding_profile_id]
        profile_hash = self.embedding_profile_hashes[embedding_profile_id]
        if not chunks:
            self.store.set_namespace_config_hash(namespace, profile_hash, embedding_profile_id)
            return EmbeddingStatus.AVAILABLE
        vectors: list[list[float]] = []
        with self._model_runtime_lock:
            adapter = self._embedding_adapter(embedding_profile_id)
            for start in range(0, len(chunks), self.config.chunking.batch_size):
                batch = chunks[start : start + self.config.chunking.batch_size]
                result = adapter.embed_texts([chunk.text for chunk in batch])
                if result.status != EmbeddingStatus.AVAILABLE:
                    return result.status
                vectors.extend([list(vector) for vector in result.vectors])
            self.store.replace_namespace_embeddings(
                namespace=namespace,
                chunks=chunks,
                vectors=vectors,
                model_id=profile.model,
                dimension=profile.dimension,
                embedding_config_hash=profile_hash,
                embedding_profile_id=embedding_profile_id,
            )
            self.unload_idle_models()
        return EmbeddingStatus.AVAILABLE

    def _run_file_ingest_job(self, *, namespace: str, job_id: str, path: Path, source: dict[str, object]) -> None:
        title = str(source.get("title") or path.name)
        total = 0
        embedded_count = 0
        try:
            if self.jobs.is_cancelled(namespace=namespace, job_id=job_id):
                return
            self.jobs.update(namespace=namespace, job_id=job_id, source_title=title, status="reading", message="reading")
            if self.jobs.is_cancelled(namespace=namespace, job_id=job_id):
                return
            text = _read_text_file(path, encoding=self.config.file_encoding)
            if self.jobs.is_cancelled(namespace=namespace, job_id=job_id):
                return
            self.jobs.update(namespace=namespace, job_id=job_id, source_title=title, status="chunking", message="chunking")
            source_model, chunks = self._prepare_source_chunks(
                namespace=namespace,
                source={**source, "kind": str(source.get("kind") or "txt"), "uri": str(source.get("uri") or path.as_uri())},
                text=text,
            )
            with self._source_lock(namespace, source_model.source_id):
                if self.jobs.is_cancelled(namespace=namespace, job_id=job_id):
                    return
                total = len(chunks)
                self.jobs.update(namespace=namespace, job_id=job_id, source_title=title, status="embedding", chunks_total=total, chunks_embedded=0, message="embedding")
                if self.jobs.is_cancelled(namespace=namespace, job_id=job_id):
                    return
                profile_id = self._source_embedding_profile_id(namespace, source)
                profile = self.embedding_profiles[profile_id]
                prepared = self._prepare_file_embeddings(
                    namespace=namespace,
                    chunks=chunks,
                    job_id=job_id,
                    source_title=title,
                    embedding_profile_id=profile_id,
                )
                embedded_count = len(prepared.vectors)
                if prepared.status != EmbeddingStatus.AVAILABLE:
                    self.jobs.update(
                        namespace=namespace,
                        job_id=job_id,
                        source_title=title,
                        status="failed",
                        chunks_total=total,
                        chunks_embedded=embedded_count,
                        message="embedding_failed",
                        error=(
                            f"embedding_status={_public_embedding_status(prepared.status)}"
                            + (f"; {prepared.message}" if prepared.message else "")
                        ),
                        error_code="KNOWLEDGE_INGEST_EMBEDDING_UNAVAILABLE",
                        retryable=True,
                    )
                    return
                if self.jobs.is_cancelled(namespace=namespace, job_id=job_id):
                    return
                published = self.store.complete_ingest_job_with_source_bundle(
                    namespace=namespace,
                    job_id=job_id,
                    source_title=title,
                    source=source_model,
                    chunks=chunks,
                    vectors=[list(vector) for vector in prepared.vectors],
                    model_id=profile.model,
                    dimension=profile.dimension,
                    embedding_config_hash=self.embedding_profile_hashes[profile_id],
                    embedding_profile_id=profile_id,
                )
                if published:
                    self.jobs.cleanup_terminal(namespace=namespace, job_id=job_id)
        except Exception as exc:  # noqa: BLE001
            self.jobs.update(
                namespace=namespace,
                job_id=job_id,
                source_title=title,
                status="failed",
                chunks_total=total,
                chunks_embedded=embedded_count,
                message="failed",
                error=str(exc),
                error_code="KNOWLEDGE_INGEST_FAILED",
                retryable=True,
            )

    def _prepare_source_chunks(self, *, namespace: str, source: dict[str, object], text: str) -> tuple[KnowledgeSource, list[KnowledgeChunk]]:
        source_id = str(source.get("source_id") or "").strip()
        uri = str(source.get("uri") or "")
        version = str(source.get("version") or "")
        if not source_id:
            source_id = self.store.find_source_id_by_uri_version(namespace, uri, version) or ""
        source_model = KnowledgeSource.new(
            namespace=namespace,
            title=str(source.get("title") or "untitled"),
            kind=str(source.get("kind") or "text"),
            uri=uri,
            version=version,
            source_id=source_id or None,
            metadata=dict(source.get("metadata") or {}),
        )
        chunking_config = self._source_chunking_config(source_model.metadata)
        chunks = chunk_text(
            namespace=namespace,
            source_id=source_model.source_id,
            text=text,
            config=chunking_config,
            metadata=source_model.metadata,
        )
        return source_model, chunks

    def _resolve_file_path(self, file_path: str) -> Path:
        path = Path(str(file_path or ""))
        if path.is_absolute():
            return path
        repo_root = Path(str(self.config.repo_root or ""))
        if str(repo_root):
            return repo_root / path
        return path.resolve()

    @contextmanager
    def _source_lock(self, namespace: str, source_id: str):  # noqa: ANN202
        key = (namespace, source_id)
        with self._source_locks_guard:
            entry = self._source_locks.get(key)
            if entry is None:
                lock = Lock()
                users = 1
            else:
                lock, users = entry
                users += 1
            self._source_locks[key] = (lock, users)
        try:
            with lock:
                yield
        finally:
            with self._source_locks_guard:
                current_lock, current_users = self._source_locks[key]
                if current_users == 1:
                    del self._source_locks[key]
                else:
                    self._source_locks[key] = (current_lock, current_users - 1)

    def _embed_chunks(
        self,
        namespace: str,
        chunks: list,
        *,
        job_id: str | None = None,
        source_title: str = "",
        embedding_profile_id: str | None = None,
    ) -> EmbeddingStatus | _EmbedChunksResult:
        profile_id = embedding_profile_id or self._namespace_embedding_profile_id(namespace)
        profile = self.embedding_profiles[profile_id]
        profile_hash = self.embedding_profile_hashes[profile_id]
        with self._model_runtime_lock:
            adapter = self._embedding_adapter(profile_id)
            embedded = 0
            total = len(chunks)
            for start in range(0, total, self.config.chunking.batch_size):
                batch = chunks[start : start + self.config.chunking.batch_size]
                embedding_result = adapter.embed_texts([chunk.text for chunk in batch])
                if embedding_result.status != EmbeddingStatus.AVAILABLE:
                    if job_id:
                        return _EmbedChunksResult(status=embedding_result.status, embedded_count=embedded, message=embedding_result.message)
                    return embedding_result.status
                for chunk, vector in zip(batch, embedding_result.vectors, strict=True):
                    self.store.upsert_embedding(
                        namespace=namespace,
                        chunk_id=chunk.chunk_id,
                        model_id=profile.model,
                        dimension=profile.dimension,
                        embedding_config_hash=profile_hash,
                        vector=vector,
                    )
                    embedded += 1
                if job_id:
                    self.jobs.update(namespace=namespace, job_id=job_id, source_title=source_title, status="embedding", chunks_total=total, chunks_embedded=embedded, message="embedding")
            self.store.set_namespace_config_hash(namespace, profile_hash, profile_id)
            self.unload_idle_models()
            return _EmbedChunksResult(status=EmbeddingStatus.AVAILABLE, embedded_count=embedded) if job_id else EmbeddingStatus.AVAILABLE

    def _prepare_file_embeddings(
        self,
        *,
        namespace: str,
        chunks: list[KnowledgeChunk],
        job_id: str,
        source_title: str,
        embedding_profile_id: str,
    ) -> _PreparedEmbeddings:
        with self._model_runtime_lock:
            adapter = self._embedding_adapter(embedding_profile_id)
            vectors: list[tuple[float, ...]] = []
            total = len(chunks)
            for start in range(0, total, self.config.chunking.batch_size):
                if self.jobs.is_cancelled(namespace=namespace, job_id=job_id):
                    return _PreparedEmbeddings(
                        status=EmbeddingStatus.DISABLED,
                        message="ingest was cancelled",
                    )
                batch = chunks[start : start + self.config.chunking.batch_size]
                result = adapter.embed_texts([chunk.text for chunk in batch])
                if result.status != EmbeddingStatus.AVAILABLE:
                    return _PreparedEmbeddings(
                        status=result.status,
                        vectors=tuple(vectors),
                        message=result.message,
                    )
                vectors.extend(tuple(float(value) for value in vector) for vector in result.vectors)
                self.jobs.update(
                    namespace=namespace,
                    job_id=job_id,
                    source_title=source_title,
                    status="embedding",
                    chunks_total=total,
                    chunks_embedded=len(vectors),
                    message="embedding",
                )
            self.unload_idle_models()
            return _PreparedEmbeddings(
                status=EmbeddingStatus.AVAILABLE,
                vectors=tuple(vectors),
            )


def _knowledge_staging_root(config: KnowledgeRuntimeConfig) -> Path:
    repo_root = str(config.repo_root or "").strip()
    if repo_root:
        return Path(repo_root) / "data" / "knowledge" / "uploads"
    return Path(config.db_path).parent / "uploads"


def _namespace(value: str, default: str) -> str:
    namespace = str(value or "").strip() or default
    if not namespace:
        raise ValueError("namespace is required")
    return namespace


def _public_embedding_status(status: EmbeddingStatus) -> str:
    if status == EmbeddingStatus.AVAILABLE:
        return "embedded"
    return str(status)


def _approved_source_title(title: str) -> str:
    value = str(title or "").strip()
    prefix = "[本地测试] "
    return value[len(prefix):] if value.startswith(prefix) else value


def _unload_if_idle(adapter: object, ttl_seconds: float) -> bool:
    if not getattr(adapter, "is_loaded")():
        return False
    state = getattr(adapter, "state", None)
    last_used_at = getattr(state, "last_used_at", None)
    if last_used_at is None:
        return False
    idle_seconds = (datetime.now(timezone.utc) - last_used_at).total_seconds()
    if idle_seconds < ttl_seconds:
        return False
    return bool(getattr(adapter, "unload")())


def _read_text_file(path: Path, *, encoding: str) -> str:
    configured = str(encoding or "auto").strip().lower()
    encodings = [configured] if configured and configured != "auto" else ["utf-8-sig", "utf-8", "gb18030"]
    last_error: UnicodeDecodeError | None = None
    for candidate in encodings:
        try:
            return path.read_text(encoding=candidate)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise UnicodeDecodeError(last_error.encoding, last_error.object, last_error.start, last_error.end, f"unable to decode text file using {encodings}") from last_error
    return path.read_text(encoding=encoding)
