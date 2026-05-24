from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from marten_runtime.knowledge.config import KnowledgeRerankerConfig
from marten_runtime.knowledge.model_runtime import LazyModelState, unload_model_object


class RerankStatus(StrEnum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    MISSING_MODEL = "missing_model"


class RerankItem(BaseModel):
    index: int
    score: float


class RerankResult(BaseModel):
    status: RerankStatus
    items: list[RerankItem] = Field(default_factory=list)
    message: str = ""


class FakeReranker:
    def __init__(self, *, model_id: str = "fake") -> None:
        self.state = LazyModelState(model_id=model_id, enabled=True)

    def rerank(self, query: str, passages: list[str], *, top_n: int) -> RerankResult:
        self.state.mark_loaded()
        query_terms = _terms(query)
        scored = []
        for index, passage in enumerate(passages):
            passage_terms = _terms(passage)
            overlap = len(query_terms & passage_terms)
            char_overlap = sum(1 for char in query if char and char in passage)
            score = float(overlap * 10 + char_overlap / max(1, len(query)))
            scored.append(RerankItem(index=index, score=score))
        scored.sort(key=lambda item: (item.score, -item.index), reverse=True)
        self.state.mark_used()
        return RerankResult(status=RerankStatus.AVAILABLE, items=scored[:top_n])

    def is_loaded(self) -> bool:
        return self.state.loaded_at is not None

    def unload(self) -> bool:
        was_loaded = self.is_loaded()
        self.state.mark_unloaded()
        return was_loaded

    def model_status(self, *, idle_ttl_seconds: float | None) -> dict[str, object]:
        return self.state.snapshot(loaded=self.is_loaded(), idle_ttl_seconds=idle_ttl_seconds)


class LocalModelReranker:
    def __init__(self, config: KnowledgeRerankerConfig) -> None:
        self.config = config
        self._model = None
        self._model_backend = ""
        self.state = LazyModelState(model_id=config.model, enabled=config.enabled)

    def rerank(self, query: str, passages: list[str], *, top_n: int) -> RerankResult:
        if not self.config.enabled:
            return RerankResult(status=RerankStatus.DISABLED, message="reranker disabled")
        local_path = Path(self.config.local_path)
        if not local_path.exists() and not self.config.allow_remote_download:
            return RerankResult(
                status=RerankStatus.MISSING_MODEL,
                message="Reranker model is not available. Configure [knowledge.reranker].local_path or disable reranker.",
            )
        try:
            model = self._load_model(local_path)
            pairs = [[query, passage] for passage in passages]
            raw_scores = _compute_scores(model, pairs)
            if isinstance(raw_scores, (int, float)):
                scores = [float(raw_scores)]
            else:
                scores = [float(score) for score in raw_scores]
            items = [RerankItem(index=index, score=score) for index, score in enumerate(scores)]
            items.sort(key=lambda item: (item.score, -item.index), reverse=True)
            self.state.mark_used()
            return RerankResult(status=RerankStatus.AVAILABLE, items=items[:top_n])
        except Exception as exc:  # noqa: BLE001
            return RerankResult(status=RerankStatus.MISSING_MODEL, message=f"Reranker model failed: {exc}")

    def is_loaded(self) -> bool:
        return self._model is not None

    def unload(self) -> bool:
        unloaded = unload_model_object(self)
        if unloaded:
            self._model_backend = ""
        self.state.mark_unloaded()
        return unloaded

    def model_status(self, *, idle_ttl_seconds: float | None) -> dict[str, object]:
        status = self.state.snapshot(loaded=self.is_loaded(), idle_ttl_seconds=idle_ttl_seconds)
        if self._model_backend:
            status["backend"] = self._model_backend
        return status

    def _load_model(self, local_path: Path):  # noqa: ANN202
        if self._model is not None:
            return self._model
        if _is_sequence_classification_model(local_path):
            from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]

            self._model = CrossEncoder(str(local_path))
            self._model_backend = "sentence_transformers_cross_encoder"
        else:
            from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]

            self._model = FlagReranker(str(local_path), use_fp16=self.config.use_fp16)
            self._model_backend = "flag_embedding"
        self.state.mark_loaded()
        return self._model


def weighted_rerank(items: list[dict]) -> list[dict]:
    return sorted(items, key=_weighted_score, reverse=True)


def _weighted_score(item: dict) -> float:
    parts = item.get("score_parts") if isinstance(item.get("score_parts"), dict) else {}
    return float(parts.get("fts") or 0.0) + float(parts.get("vector") or 0.0) + float(parts.get("metadata") or 0.0)


def _terms(text: str) -> set[str]:
    return {term for term in str(text or "").replace("，", " ").replace("。", " ").split() if term}


def _is_sequence_classification_model(local_path: Path) -> bool:
    config_path = local_path / "config.json"
    if not config_path.exists():
        return False
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    architectures = [str(item) for item in data.get("architectures") or []]
    return any("SequenceClassification" in item for item in architectures)


def _compute_scores(model: object, pairs: list[list[str]]) -> object:
    if hasattr(model, "predict"):
        return model.predict(pairs)
    if hasattr(model, "compute_score"):
        return model.compute_score(pairs)
    raise TypeError(f"unsupported reranker backend: {type(model).__name__}")
