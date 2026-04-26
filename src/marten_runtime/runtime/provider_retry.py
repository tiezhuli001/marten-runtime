from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import random
from typing import TypeVar

from marten_runtime.runtime.cooperative_stop import interruptible_sleep, raise_if_interrupted

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0
    jitter_ratio: float = 0.2


class ProviderTransportError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        retryable: bool = False,
        attempt_count: int = 1,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable
        self.attempt_count = attempt_count
        self.provider_name = provider_name
        self.model_name = model_name


def with_retry(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    stop_event=None,
    deadline_monotonic: float | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> T:
    retry_policy = policy or RetryPolicy()
    last_error: Exception | None = None
    for attempt in range(1, retry_policy.max_attempts + 1):
        try:
            raise_if_interrupted(
                stop_event=stop_event,
                deadline_monotonic=deadline_monotonic,
                cancelled_message="PROVIDER_CALL_CANCELLED",
                timed_out_message="PROVIDER_CALL_TIMED_OUT",
            )
            return operation()
        except Exception as exc:  # noqa: BLE001
            normalized = normalize_provider_error(exc)
            normalized.attempt_count = attempt  # type: ignore[misc]
            if not normalized.retryable or attempt >= retry_policy.max_attempts:
                raise normalized
            last_error = normalized
            delay = min(
                retry_policy.max_backoff_seconds,
                retry_policy.base_backoff_seconds * max(1, 2 ** (attempt - 1)),
            )
            if delay > 0 and retry_policy.jitter_ratio > 0:
                delay += random.uniform(0, delay * retry_policy.jitter_ratio)
                delay = min(delay, retry_policy.max_backoff_seconds)
            if delay > 0:
                interruptible_sleep(
                    delay,
                    stop_event=stop_event,
                    deadline_monotonic=deadline_monotonic,
                    cancelled_message="PROVIDER_CALL_CANCELLED",
                    timed_out_message="PROVIDER_CALL_TIMED_OUT",
                    sleeper=sleeper,
                )
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
    if message.startswith("provider_http_error:429"):
        return ProviderTransportError("PROVIDER_RATE_LIMITED", message, retryable=True)
    if message.startswith("provider_http_error:529"):
        return ProviderTransportError("PROVIDER_UPSTREAM_UNAVAILABLE", message, retryable=True)
    if (
        message.startswith("provider_http_error:502")
        or message.startswith("provider_http_error:503")
        or message.startswith("provider_http_error:504")
    ):
        return ProviderTransportError("PROVIDER_UPSTREAM_UNAVAILABLE", message, retryable=True)
    if message.startswith("provider_http_error:"):
        return ProviderTransportError("PROVIDER_HTTP_ERROR", message)
    if message.startswith("provider_transport_error:"):
        return ProviderTransportError("PROVIDER_TRANSPORT_ERROR", message, retryable=True)
    if message.startswith("provider_response_invalid:"):
        return ProviderTransportError("PROVIDER_RESPONSE_INVALID", message)
    return ProviderTransportError("PROVIDER_TRANSPORT_ERROR", message or exc.__class__.__name__)
