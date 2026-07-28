from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator

from marten_runtime.config.file_resolver import resolve_config_path


class KnowledgeChunkingConfig(BaseModel):
    target_chars: int = Field(gt=0)
    overlap_chars: int = Field(ge=0)
    max_chars: int = Field(gt=0)
    batch_size: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "KnowledgeChunkingConfig":
        if self.target_chars > self.max_chars:
            raise ValueError("target_chars must be <= max_chars")
        if self.overlap_chars >= self.target_chars:
            raise ValueError("overlap_chars must be < target_chars")
        return self


class KnowledgeEmbeddingConfig(BaseModel):
    enabled: bool = True
    provider: str
    model: str
    local_path: str
    dimension: int = Field(gt=0)
    allow_remote_download: bool = False
    use_fp16: bool = False


class KnowledgeRerankerConfig(BaseModel):
    enabled: bool = True
    provider: str
    model: str
    local_path: str
    allow_remote_download: bool = False
    use_fp16: bool = False
    top_n: int = Field(gt=0)


class KnowledgeVectorStoreConfig(BaseModel):
    enabled: bool = True
    backend: str


class KnowledgeSearchConfig(BaseModel):
    default_top_k: int = Field(gt=0)
    candidate_pool: int = Field(gt=0)
    fts_weight: float = Field(ge=0.0)
    vector_weight: float = Field(ge=0.0)
    metadata_weight: float = Field(ge=0.0)
    reranker_weight: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_pool(self) -> "KnowledgeSearchConfig":
        if self.candidate_pool < self.default_top_k:
            raise ValueError("candidate_pool must be >= default_top_k")
        return self


class KnowledgeRuntimeConfig(BaseModel):
    db_path: str
    repo_root: str = ""
    default_namespace: str
    model_idle_ttl_seconds: float = Field(default=300.0, ge=0.0)
    prewarm_on_start: bool = False
    file_encoding: str = "auto"
    chunking: KnowledgeChunkingConfig
    embedding: KnowledgeEmbeddingConfig
    embedding_profiles: dict[str, KnowledgeEmbeddingConfig] = Field(default_factory=dict)
    reranker: KnowledgeRerankerConfig
    vector_store: KnowledgeVectorStoreConfig
    search: KnowledgeSearchConfig

    @model_validator(mode="after")
    def validate_namespace(self) -> "KnowledgeRuntimeConfig":
        if not self.default_namespace.strip():
            raise ValueError("default_namespace is required")
        if not self.file_encoding.strip():
            raise ValueError("file_encoding is required")
        if any(not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", profile_id) for profile_id in self.embedding_profiles):
            raise ValueError("embedding profile ids must use lowercase letters, digits, '_' or '-'")
        return self

    def resolved_embedding_profiles(self) -> dict[str, KnowledgeEmbeddingConfig]:
        return {"default": self.embedding, **self.embedding_profiles}


class KnowledgeConfigFile(BaseModel):
    knowledge: KnowledgeRuntimeConfig


class _LoadKnowledgeConfig:
    _model: ClassVar[type[KnowledgeConfigFile]] = KnowledgeConfigFile

    def __call__(self, path: str) -> KnowledgeConfigFile:
        resolved = resolve_config_path(path)
        if resolved is None:
            requested = Path(path)
            bundled_example = Path(__file__).resolve().parents[3] / "config" / "knowledge.example.toml"
            if requested.name == "knowledge.toml" and bundled_example.exists():
                resolved = bundled_example
            else:
                raise FileNotFoundError(f"knowledge config not found: {path}")
        return self.from_text(resolved.read_text(encoding="utf-8"))

    def from_text(self, text: str) -> KnowledgeConfigFile:
        data = tomllib.loads(text)
        return self._model(**data)


load_knowledge_config = _LoadKnowledgeConfig()


def embedding_config_hash(config: KnowledgeEmbeddingConfig) -> str:
    payload = {
        "provider": config.provider,
        "model": config.model,
        "local_path": _stable_path(config.local_path),
        "dimension": config.dimension,
        "use_fp16": config.use_fp16,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _stable_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return str(Path(raw))
