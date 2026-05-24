from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

from marten_runtime.knowledge.chunking import chunk_text
from marten_runtime.knowledge.config import KnowledgeRuntimeConfig, embedding_config_hash
from marten_runtime.knowledge.embeddings import EmbeddingStatus, FakeEmbeddingAdapter, LocalModelEmbeddingAdapter
from marten_runtime.knowledge.jobs import KnowledgeIngestJobStore
from marten_runtime.knowledge.models import KnowledgeChunk, KnowledgeSource
from marten_runtime.knowledge.rerankers import FakeReranker, LocalModelReranker
from marten_runtime.knowledge.retrieval import KnowledgeRetriever
from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore


@dataclass(frozen=True)
class _EmbedChunksResult:
    status: EmbeddingStatus
    embedded_count: int
    message: str = ""


class KnowledgeService:
    def __init__(self, config: KnowledgeRuntimeConfig) -> None:
        self.config = config
        self.store = SQLiteKnowledgeStore(config.db_path)
        self.jobs = KnowledgeIngestJobStore(self.store)
        self.embedding_config_hash = embedding_config_hash(config.embedding)
        self.embedding_adapter = (
            FakeEmbeddingAdapter(dimension=config.embedding.dimension, model_id=config.embedding.model)
            if config.embedding.provider == "fake"
            else LocalModelEmbeddingAdapter(config.embedding)
        )
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
        source_model, chunks = self._prepare_source_chunks(namespace=namespace, source=source, text=text)
        self.store.upsert_source(source_model)
        self.store.replace_chunks(namespace, source_model.source_id, chunks)
        embedding_status = self._embed_chunks(namespace, chunks)
        return {
            "ok": True,
            "action": "ingest_text",
            "namespace": namespace,
            "source_id": source_model.source_id,
            "chunk_count": len(chunks),
            "embedding_status": _public_embedding_status(embedding_status),
            "vector_store_status": "indexed" if embedding_status == EmbeddingStatus.AVAILABLE else "disabled",
        }

    def ingest_file(self, *, namespace: str, file_path: str, source: dict[str, object]) -> dict[str, object]:
        self.unload_idle_models()
        namespace = _namespace(namespace, self.config.default_namespace)
        path = self._resolve_file_path(file_path)
        source_title = str(source.get("title") or path.name)
        job_id = self.jobs.create_job(namespace=namespace, source_title=source_title)
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

    def ingest_status(self, *, namespace: str, job_id: str) -> dict[str, object]:
        self.unload_idle_models()
        namespace = _namespace(namespace, self.config.default_namespace)
        job = self.jobs.get(namespace=namespace, job_id=job_id)
        if job is None:
            return {"ok": False, "error_code": "KNOWLEDGE_JOB_NOT_FOUND", "job_id": job_id}
        return {"ok": True, **job}

    def cancel_ingest(self, *, namespace: str, job_id: str) -> dict[str, object]:
        self.unload_idle_models()
        return self.jobs.cancel(namespace=_namespace(namespace, self.config.default_namespace), job_id=job_id)

    def search(
        self,
        *,
        namespace: str,
        query: str,
        top_k: int | None = None,
        filters: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.unload_idle_models()
        namespace = _namespace(namespace, self.config.default_namespace)
        query = str(query or "").strip()
        if not query:
            return {"ok": False, "error_code": "KNOWLEDGE_QUERY_REQUIRED", "message": "query is required"}
        resolved_top_k = self.config.search.default_top_k if top_k is None else int(top_k)
        if resolved_top_k < 1:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_TOP_K_INVALID",
                "top_k": resolved_top_k,
                "message": "top_k must be >= 1",
            }
        query_result = self.embedding_adapter.embed_texts([query])
        if query_result.status == EmbeddingStatus.MISSING_MODEL:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_QUERY_EMBEDDING_UNAVAILABLE",
                "embedding_status": _public_embedding_status(query_result.status),
                "message": query_result.message or "query embedding is unavailable",
            }
        query_vector = query_result.vectors[0] if query_result.vectors else []
        result = self.retriever.search(
            namespace=namespace,
            query=query,
            embedding_config_hash=self.embedding_config_hash,
            query_vector=query_vector,
            top_k=resolved_top_k,
            filters=filters,
        )
        self.unload_idle_models()
        return {"ok": True, **result.model_dump(mode="json")}

    def get_chunk(self, *, namespace: str, chunk_id: str) -> dict[str, object]:
        self.unload_idle_models()
        chunk = self.store.get_chunk(_namespace(namespace, self.config.default_namespace), chunk_id)
        if chunk is None:
            return {"ok": False, "error_code": "KNOWLEDGE_CHUNK_NOT_FOUND", "chunk_id": chunk_id}
        return {"ok": True, "chunk": chunk.model_dump(mode="json")}

    def delete_source(self, *, namespace: str, source_id: str) -> dict[str, object]:
        self.unload_idle_models()
        namespace = _namespace(namespace, self.config.default_namespace)
        result = self.store.delete_source(namespace, source_id)
        return {"ok": True, "namespace": namespace, **result.model_dump(mode="json")}

    def reindex(self, *, namespace: str, source_id: str | None = None) -> dict[str, object]:
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
        embedding_status = self._embed_chunks(namespace, chunks)
        if embedding_status != EmbeddingStatus.AVAILABLE:
            return {
                "ok": False,
                "action": "reindex",
                "error_code": "KNOWLEDGE_REINDEX_EMBEDDING_UNAVAILABLE",
                "namespace": namespace,
                "source_id": source_id or "",
                "chunk_count": len(chunks),
                "embedding_status": _public_embedding_status(embedding_status),
                "embedding_config_hash": self.embedding_config_hash,
                "message": "embedding is unavailable; reindex did not update vectors",
            }
        return {
            "ok": True,
            "action": "reindex",
            "namespace": namespace,
            "source_id": source_id or "",
            "chunk_count": len(chunks),
            "embedding_status": _public_embedding_status(embedding_status),
            "embedding_config_hash": self.embedding_config_hash,
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
        }

    def model_status(self) -> dict[str, object]:
        self.unload_idle_models()
        ttl = self.config.model_idle_ttl_seconds
        return {
            "ok": True,
            "action": "model_status",
            "idle_ttl_seconds": ttl,
            "embedding": self.embedding_adapter.model_status(idle_ttl_seconds=ttl),
            "reranker": self.reranker_adapter.model_status(idle_ttl_seconds=ttl),
        }

    def unload_models(self) -> dict[str, object]:
        embedding_unloaded = self.embedding_adapter.unload()
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
        ttl = self.config.model_idle_ttl_seconds
        if ttl <= 0:
            return {"embedding_unloaded": False, "reranker_unloaded": False}
        return {
            "embedding_unloaded": _unload_if_idle(self.embedding_adapter, ttl),
            "reranker_unloaded": _unload_if_idle(self.reranker_adapter, ttl),
        }

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
            total = len(chunks)
            self.store.upsert_source(source_model)
            self.store.replace_chunks(namespace, source_model.source_id, chunks)
            self.jobs.update(namespace=namespace, job_id=job_id, source_title=title, status="embedding", chunks_total=total, chunks_embedded=0, message="embedding")
            if self.jobs.is_cancelled(namespace=namespace, job_id=job_id):
                return
            embedded = self._embed_chunks(namespace, chunks, job_id=job_id, source_title=title)
            if isinstance(embedded, _EmbedChunksResult):
                embedded_count = embedded.embedded_count
                embedding_status = embedded.status
            else:
                embedding_status = embedded
            if embedding_status != EmbeddingStatus.AVAILABLE:
                self.jobs.update(
                    namespace=namespace,
                    job_id=job_id,
                    source_title=title,
                    status="failed",
                    chunks_total=total,
                    chunks_embedded=embedded_count,
                    message="embedding_failed",
                    error=f"embedding_status={_public_embedding_status(embedding_status)}",
                )
                return
            if self.jobs.is_cancelled(namespace=namespace, job_id=job_id):
                return
            self.jobs.update(namespace=namespace, job_id=job_id, source_title=title, status="completed", chunks_total=total, chunks_embedded=embedded_count, message="completed")
        except Exception as exc:  # noqa: BLE001
            self.jobs.update(namespace=namespace, job_id=job_id, source_title=title, status="failed", chunks_total=total, chunks_embedded=embedded_count, message="failed", error=str(exc))

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
        chunks = chunk_text(
            namespace=namespace,
            source_id=source_model.source_id,
            text=text,
            config=self.config.chunking,
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

    def _embed_chunks(self, namespace: str, chunks: list, *, job_id: str | None = None, source_title: str = "") -> EmbeddingStatus | _EmbedChunksResult:
        embedded = 0
        total = len(chunks)
        for start in range(0, total, self.config.chunking.batch_size):
            batch = chunks[start : start + self.config.chunking.batch_size]
            embedding_result = self.embedding_adapter.embed_texts([chunk.text for chunk in batch])
            if embedding_result.status != EmbeddingStatus.AVAILABLE:
                if job_id:
                    return _EmbedChunksResult(status=embedding_result.status, embedded_count=embedded, message=embedding_result.message)
                return embedding_result.status
            for chunk, vector in zip(batch, embedding_result.vectors, strict=True):
                self.store.upsert_embedding(
                    namespace=namespace,
                    chunk_id=chunk.chunk_id,
                    model_id=self.config.embedding.model,
                    dimension=self.config.embedding.dimension,
                    embedding_config_hash=self.embedding_config_hash,
                    vector=vector,
                )
                embedded += 1
            if job_id:
                self.jobs.update(namespace=namespace, job_id=job_id, source_title=source_title, status="embedding", chunks_total=total, chunks_embedded=embedded, message="embedding")
        self.store.set_namespace_config_hash(namespace, self.embedding_config_hash)
        self.unload_idle_models()
        return _EmbedChunksResult(status=EmbeddingStatus.AVAILABLE, embedded_count=embedded) if job_id else EmbeddingStatus.AVAILABLE


def _namespace(value: str, default: str) -> str:
    namespace = str(value or "").strip() or default
    if not namespace:
        raise ValueError("namespace is required")
    return namespace


def _public_embedding_status(status: EmbeddingStatus) -> str:
    if status == EmbeddingStatus.AVAILABLE:
        return "embedded"
    return str(status)


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
    encodings = [configured] if configured and configured != "auto" else ["utf-8", "utf-8-sig", "gb18030"]
    last_error: UnicodeDecodeError | None = None
    for candidate in encodings:
        try:
            return path.read_text(encoding=candidate)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise UnicodeDecodeError(last_error.encoding, last_error.object, last_error.start, last_error.end, f"unable to decode text file using {encodings}") from last_error
    return path.read_text(encoding=encoding)
