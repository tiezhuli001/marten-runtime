from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path
from pydantic import BaseModel, Field

from marten_runtime.knowledge.config import KnowledgeEmbeddingConfig
from marten_runtime.knowledge.model_runtime import LazyModelState, unload_model_object


class EmbeddingStatus(StrEnum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    MISSING_MODEL = "missing_model"


class EmbeddingResult(BaseModel):
    status: EmbeddingStatus
    vectors: list[list[float]] = Field(default_factory=list)
    message: str = ""


class FakeEmbeddingAdapter:
    def __init__(self, *, dimension: int = 8, model_id: str = "fake") -> None:
        self.dimension = dimension
        self.state = LazyModelState(model_id=model_id, enabled=True)

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        self.state.mark_loaded()
        vectors = [_fake_vector(text, self.dimension) for text in texts]
        return EmbeddingResult(status=EmbeddingStatus.AVAILABLE, vectors=vectors)

    def is_loaded(self) -> bool:
        return self.state.loaded_at is not None

    def unload(self) -> bool:
        was_loaded = self.is_loaded()
        self.state.mark_unloaded()
        return was_loaded

    def model_status(self, *, idle_ttl_seconds: float | None) -> dict[str, object]:
        return self.state.snapshot(loaded=self.is_loaded(), idle_ttl_seconds=idle_ttl_seconds)


class LocalModelEmbeddingAdapter:
    def __init__(self, config: KnowledgeEmbeddingConfig) -> None:
        self.config = config
        self._model = None
        self.state = LazyModelState(model_id=config.model, enabled=config.enabled)

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        if not self.config.enabled:
            return EmbeddingResult(status=EmbeddingStatus.DISABLED, message="embedding disabled")
        local_path = Path(self.config.local_path)
        if not local_path.exists() and not self.config.allow_remote_download:
            return EmbeddingResult(
                status=EmbeddingStatus.MISSING_MODEL,
                message=(
                    "Embedding model is not available. Configure [knowledge.embedding].local_path "
                    "or set [knowledge.embedding].enabled=false to use FTS-only retrieval."
                ),
            )
        try:
            model = self._load_model(local_path)
            output = _encode_dense(model, texts, batch_size=len(texts) or 1)
            raw_vectors = output.get("dense_vecs") if isinstance(output, dict) else output
            vectors = [_normalize_vector(vector, self.config.dimension) for vector in raw_vectors]
            self.state.mark_used()
            return EmbeddingResult(status=EmbeddingStatus.AVAILABLE, vectors=vectors)
        except Exception as exc:  # noqa: BLE001
            return EmbeddingResult(status=EmbeddingStatus.MISSING_MODEL, message=f"Embedding model failed: {exc}")

    def is_loaded(self) -> bool:
        return self._model is not None

    def unload(self) -> bool:
        unloaded = unload_model_object(self)
        self.state.mark_unloaded()
        return unloaded

    def model_status(self, *, idle_ttl_seconds: float | None) -> dict[str, object]:
        return self.state.snapshot(loaded=self.is_loaded(), idle_ttl_seconds=idle_ttl_seconds)

    def _load_model(self, local_path: Path):  # noqa: ANN202
        if self._model is not None:
            return self._model
        if self.config.model == "BAAI/bge-m3":
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]

            self._model = BGEM3FlagModel(str(local_path), use_fp16=self.config.use_fp16)
        else:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

            self._model = SentenceTransformer(str(local_path))
        self.state.mark_loaded()
        return self._model


def _encode_dense(model, texts: list[str], *, batch_size: int):  # noqa: ANN001, ANN202
    if model.__class__.__name__ == "BGEM3FlagModel":
        return model.encode(texts, batch_size=batch_size, return_dense=True)
    output = model.encode(texts, batch_size=batch_size)
    if isinstance(output, dict) or not hasattr(output, "tolist"):
        return output
    return output.tolist()


def _fake_vector(text: str, dimension: int) -> list[float]:
    digest = hashlib.sha256(str(text).encode("utf-8")).digest()
    values: list[float] = []
    for index in range(dimension):
        byte = digest[index % len(digest)]
        values.append(round((byte / 255.0) * 2.0 - 1.0, 6))
    return values


def _normalize_vector(vector: object, dimension: int) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    values = [float(item) for item in list(vector)]  # type: ignore[arg-type]
    if len(values) == dimension:
        return values
    if len(values) > dimension:
        return values[:dimension]
    return values + [0.0] * (dimension - len(values))
