from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class VectorStatus(StrEnum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    CONFIG_MISMATCH = "config_mismatch"
    QUERY_VECTOR_UNAVAILABLE = "query_vector_unavailable"
    BACKEND_ERROR = "backend_error"


class VectorResultItem(BaseModel):
    chunk_id: str
    score: float


class VectorQueryResult(BaseModel):
    status: VectorStatus
    items: list[VectorResultItem] = Field(default_factory=list)
    message: str = ""
