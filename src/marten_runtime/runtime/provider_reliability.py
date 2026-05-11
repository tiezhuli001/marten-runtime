from __future__ import annotations

from collections import Counter
import re
from collections.abc import Iterable, Mapping, Sequence

from pydantic import BaseModel, Field

from marten_runtime.runtime.usage_models import ProviderCallAttempt, ProviderCallDiagnostics


class ProviderErrorKindCount(BaseModel):
    error_kind: str
    count: int


class ProviderRunReliability(BaseModel):
    run_id: str
    status: str | None = None
    retry_count: int = 0
    fallback_count: int = 0
    provider_error_count: int = 0
    empty_output_count: int = 0
    final_provider_ref: str | None = None
    error_kinds: list[ProviderErrorKindCount] = Field(default_factory=list)


class ProviderHealthSummary(BaseModel):
    window_size: int = 20
    run_count: int = 0
    retry_count: int = 0
    fallback_count: int = 0
    provider_error_count: int = 0
    empty_output_count: int = 0
    top_error_kinds: list[ProviderErrorKindCount] = Field(default_factory=list)
    latest_final_provider_ref: str | None = None
    latest_runs: list[ProviderRunReliability] = Field(default_factory=list)


_AUTH_HINTS = (
    "unauthorized",
    "unauthorised",
    "forbidden",
    "credential",
    "credentials",
    "api key",
    "auth",
)
_QUOTA_HINTS = (
    "rate limit",
    "quota",
    "insufficient credit",
    "too many requests",
    "exceeded",
)
_CONTEXT_HINTS = (
    "context length",
    "token limit",
    "request too large",
    "prompt too long",
    "too long",
    "maximum context",
    "input too large",
)
_PROTOCOL_HINTS = (
    "schema",
    "malformed",
    "invalid",
    "parse",
    "parsing",
    "missing choices",
    "unsupported shape",
    "response invalid",
)
_TRANSIENT_HINTS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection refused",
    "dns",
    "unavailable",
    "upstream",
    "transport",
)


def classify_provider_error_kind(
    *,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> str | None:
    normalized_code = str(error_code or "").strip().upper()
    normalized_detail = _normalize_text(error_detail)
    if not normalized_code and not normalized_detail:
        return None
    if normalized_code in {"PROVIDER_AUTH_ERROR"} or _contains_any(normalized_detail, _AUTH_HINTS):
        return "auth"
    if normalized_code in {"PROVIDER_RATE_LIMITED"} or _contains_any(normalized_detail, _QUOTA_HINTS):
        return "quota"
    if _contains_any(normalized_detail, _CONTEXT_HINTS):
        return "context"
    if normalized_code in {"PROVIDER_RESPONSE_INVALID", "PROVIDER_PROTOCOL_ERROR"} or _contains_any(
        normalized_detail,
        _PROTOCOL_HINTS,
    ):
        return "protocol"
    if normalized_code in {
        "PROVIDER_TIMEOUT",
        "PROVIDER_TRANSPORT_ERROR",
        "PROVIDER_UPSTREAM_UNAVAILABLE",
    } or _contains_any(normalized_detail, _TRANSIENT_HINTS):
        return "transient"
    if normalized_code in {"PROVIDER_HTTP_ERROR"}:
        if _looks_like_transient_http_status(normalized_detail):
            return "transient"
        return "protocol"
    return "protocol"


def resolve_retry_after_seconds(
    *,
    error_kind: str | None,
    explicit_retry_after_seconds: float | int | None = None,
) -> int:
    if explicit_retry_after_seconds is not None:
        return max(0, int(round(float(explicit_retry_after_seconds))))
    default_values = {
        "auth": 0,
        "quota": 30,
        "context": 0,
        "protocol": 0,
        "transient": 2,
    }
    return default_values.get(error_kind or "", 0)


def build_provider_call_diagnostics(
    *,
    request_kind: str,
    timeout_seconds: int,
    max_attempts: int,
    completed: bool,
    final_error_code: str | None,
    attempts: list[ProviderCallAttempt],
    provider_name: str | None = None,
    model_name: str | None = None,
    profile_name: str | None = None,
    error_detail: str | None = None,
    retry_after_seconds: float | int | None = None,
) -> ProviderCallDiagnostics:
    error_kind = None
    resolved_retry_after_seconds = 0
    if not completed or final_error_code:
        error_kind = classify_provider_error_kind(
            error_code=final_error_code,
            error_detail=error_detail,
        )
        resolved_retry_after_seconds = resolve_retry_after_seconds(
            error_kind=error_kind,
            explicit_retry_after_seconds=retry_after_seconds,
        )
    return ProviderCallDiagnostics(
        request_kind=request_kind,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        completed=completed,
        final_error_code=final_error_code,
        provider_name=provider_name,
        model_name=model_name,
        profile_name=profile_name,
        error_kind=error_kind,
        retry_after_seconds=resolved_retry_after_seconds,
        attempts=list(attempts),
    )


def summarize_provider_run_reliability(run: object) -> ProviderRunReliability:
    run_id = str(_get_value(run, "run_id") or "")
    provider_calls = _as_sequence(_get_value(run, "provider_calls"))
    retry_count = sum(max(0, len(_as_sequence(_get_value(call, "attempts"))) - 1) for call in provider_calls)
    attempted_providers = _normalize_unique_sequence(_as_sequence(_get_value(run, "attempted_providers")))
    fallback_count = max(0, len(attempted_providers) - 1)
    final_provider_ref = _normalize_text(_get_value(run, "final_provider_ref")) or None
    if final_provider_ref is None:
        final_provider_ref = _normalize_text(_get_value(run, "provider_ref")) or None
    if final_provider_ref is None and provider_calls:
        final_provider_ref = _normalize_text(_get_value(provider_calls[-1], "provider_name")) or None

    error_kind_counts: Counter[str] = Counter()
    provider_error_count = 0
    for call in provider_calls:
        completed = bool(_get_value(call, "completed"))
        final_error_code = _normalize_text(_get_value(call, "final_error_code"))
        error_detail = _normalize_text(_get_value(call, "error_detail"))
        error_kind = _normalize_text(_get_value(call, "error_kind")) or None
        if not completed or final_error_code:
            provider_error_count += 1
            if error_kind is None:
                error_kind = classify_provider_error_kind(
                    error_code=final_error_code,
                    error_detail=error_detail,
                )
            if error_kind:
                error_kind_counts[error_kind] += 1

    final_text = _normalize_text(_get_value(run, "final_text"))
    empty_output_count = 1 if provider_calls and not final_text else 0
    status = _normalize_text(_get_value(run, "status")) or None

    return ProviderRunReliability(
        run_id=run_id,
        status=status,
        retry_count=retry_count,
        fallback_count=fallback_count,
        provider_error_count=provider_error_count,
        empty_output_count=empty_output_count,
        final_provider_ref=final_provider_ref,
        error_kinds=[
            ProviderErrorKindCount(error_kind=kind, count=count)
            for kind, count in sorted(
                error_kind_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
    )


def build_provider_health_summary(
    runs: Sequence[object],
    *,
    window_size: int = 20,
) -> ProviderHealthSummary:
    normalized_window_size = max(1, int(window_size))
    selected_runs = list(runs)[-normalized_window_size:]
    latest_runs = [summarize_provider_run_reliability(run) for run in selected_runs]
    top_error_counts: Counter[str] = Counter()
    for run_summary in latest_runs:
        for item in run_summary.error_kinds:
            top_error_counts[item.error_kind] += item.count
    return ProviderHealthSummary(
        window_size=normalized_window_size,
        run_count=len(selected_runs),
        retry_count=sum(item.retry_count for item in latest_runs),
        fallback_count=sum(item.fallback_count for item in latest_runs),
        provider_error_count=sum(item.provider_error_count for item in latest_runs),
        empty_output_count=sum(item.empty_output_count for item in latest_runs),
        top_error_kinds=[
            ProviderErrorKindCount(error_kind=kind, count=count)
            for kind, count in sorted(
                top_error_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        latest_final_provider_ref=latest_runs[-1].final_provider_ref if latest_runs else None,
        latest_runs=latest_runs,
    )


def _contains_any(text: str, hints: Iterable[str]) -> bool:
    return any(hint in text for hint in hints)


def _looks_like_transient_http_status(text: str) -> bool:
    return bool(re.search(r"(?<!\d)(?:500|502|503|504|529)(?!\d)", text))


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def _normalize_unique_sequence(items: Sequence[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = _normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _as_sequence(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _get_value(item: object, key: str) -> object:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


__all__ = [
    "ProviderErrorKindCount",
    "ProviderHealthSummary",
    "ProviderRunReliability",
    "build_provider_call_diagnostics",
    "build_provider_health_summary",
    "classify_provider_error_kind",
    "resolve_retry_after_seconds",
    "summarize_provider_run_reliability",
]
