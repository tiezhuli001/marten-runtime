from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeSource(BaseModel):
    namespace: str
    source_id: str
    title: str
    kind: str
    uri: str
    version: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)
    status: str = "active"
    created_at: str
    updated_at: str

    @classmethod
    def new(
        cls,
        *,
        namespace: str,
        title: str,
        kind: str,
        uri: str,
        source_id: str | None = None,
        version: str = "",
        metadata: dict[str, object] | None = None,
    ) -> "KnowledgeSource":
        now = utc_now_iso()
        return cls(
            namespace=namespace,
            source_id=source_id or f"ksrc_{uuid4().hex[:12]}",
            title=title,
            kind=kind,
            uri=uri,
            version=version,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )


class KnowledgeChunk(BaseModel):
    namespace: str
    chunk_id: str
    source_id: str
    heading: str = ""
    ordinal: int
    text: str
    token_estimate: int = 0
    metadata: dict[str, object] = Field(default_factory=dict)
    status: str = "active"
    created_at: str
    updated_at: str

    @classmethod
    def new(
        cls,
        *,
        namespace: str,
        source_id: str,
        ordinal: int,
        text: str,
        heading: str = "",
        metadata: dict[str, object] | None = None,
        token_estimate: int = 0,
    ) -> "KnowledgeChunk":
        now = utc_now_iso()
        return cls(
            namespace=namespace,
            chunk_id=f"kchk_{uuid4().hex[:12]}",
            source_id=source_id,
            heading=heading,
            ordinal=ordinal,
            text=text,
            token_estimate=token_estimate,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )


class KnowledgeDeleteResult(BaseModel):
    deleted_source_id: str
    deleted_chunk_count: int


class KnowledgeIngestJob(BaseModel):
    namespace: str
    job_id: str
    source_title: str = ""
    status: str
    chunks_total: int = 0
    chunks_embedded: int = 0
    percent: float = 0.0
    message: str = ""
    error: str = ""
    error_code: str = ""
    retryable: bool = False
    staged_file_path: str = ""
    created_at: str
    updated_at: str


class KnowledgeEmbeddingRecord(BaseModel):
    namespace: str
    chunk_id: str
    model_id: str
    dimension: int
    embedding_config_hash: str
    vector: list[float]
    status: str = "active"
    created_at: str
    updated_at: str
