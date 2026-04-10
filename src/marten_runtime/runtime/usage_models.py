from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NormalizedUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    provider_name: str | None = None
    model_name: str | None = None
    captured_at: datetime | None = None
    raw_usage_payload: dict[str, object] | None = None


class PreflightEstimate(BaseModel):
    input_tokens_estimate: int
    estimator_kind: str
    degraded: bool = False


class ProviderCallAttempt(BaseModel):
    attempt: int
    elapsed_ms: int
    ok: bool
    error_code: str | None = None
    error_detail: str | None = None
    retryable: bool = False


class ProviderCallDiagnostics(BaseModel):
    request_kind: str
    timeout_seconds: int
    max_attempts: int
    completed: bool
    final_error_code: str | None = None
    attempts: list[ProviderCallAttempt] = Field(default_factory=list)
