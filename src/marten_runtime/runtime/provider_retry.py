from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import time
from typing import TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0


class ProviderTransportError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, retryable: bool = False) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable


def with_retry(operation: Callable[[], T], *, policy: RetryPolicy | None = None) -> T:
    retry_policy = policy or RetryPolicy()
    last_error: Exception | None = None
    for attempt in range(1, retry_policy.max_attempts + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            normalized = normalize_provider_error(exc)
            if not normalized.retryable or attempt >= retry_policy.max_attempts:
                raise normalized
            last_error = normalized
            delay = min(
                retry_policy.max_backoff_seconds,
                retry_policy.base_backoff_seconds * max(1, 2 ** (attempt - 1)),
            )
            if delay > 0:
                time.sleep(delay)
    assert last_error is not None
    raise last_error


def normalize_provider_error(exc: Exception) -> ProviderTransportError:
    if isinstance(exc, ProviderTransportError):
        return exc
    if isinstance(exc, TimeoutError):
        return ProviderTransportError("PROVIDER_TIMEOUT", str(exc) or "provider timeout", retryable=True)
    if isinstance(exc, OSError):
        return ProviderTransportError(
            "PROVIDER_TRANSPORT_ERROR",
            str(exc) or "provider transport error",
            retryable=True,
        )
    message = str(exc)
    if message.startswith("provider_http_error:401") or message.startswith("provider_http_error:403"):
        return ProviderTransportError("PROVIDER_AUTH_ERROR", message)
    if message.startswith("provider_http_error:"):
        return ProviderTransportError("PROVIDER_HTTP_ERROR", message)
    if message.startswith("provider_transport_error:"):
        return ProviderTransportError("PROVIDER_TRANSPORT_ERROR", message, retryable=True)
    return ProviderTransportError("PROVIDER_TRANSPORT_ERROR", message or exc.__class__.__name__)
