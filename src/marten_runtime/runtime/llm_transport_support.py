from __future__ import annotations

import inspect
from collections.abc import Callable

from marten_runtime.runtime.llm_provider_support import elapsed_ms
from marten_runtime.runtime.provider_retry import normalize_provider_error
from marten_runtime.runtime.usage_models import ProviderCallAttempt

Transport = Callable[..., dict]


def call_transport(
    transport: Transport,
    url: str,
    headers: dict[str, str],
    body: dict,
    *,
    timeout_seconds: int,
) -> dict:
    if len(inspect.signature(transport).parameters) >= 4:
        return transport(url, headers, body, timeout_seconds)
    return transport(url, headers, body)


def invoke_transport(
    *,
    transport: Transport,
    url: str,
    headers: dict[str, str],
    body: dict,
    timeout_seconds: int,
    attempts: list[ProviderCallAttempt],
) -> dict:
    started_at = __import__('time').perf_counter()
    try:
        result = call_transport(
            transport,
            url,
            headers,
            body,
            timeout_seconds=timeout_seconds,
        )
        attempts.append(
            ProviderCallAttempt(
                attempt=len(attempts) + 1,
                elapsed_ms=elapsed_ms(started_at),
                ok=True,
                error_code=None,
                error_detail=None,
                retryable=False,
            )
        )
        return result
    except Exception as exc:
        normalized = normalize_provider_error(exc)
        attempts.append(
            ProviderCallAttempt(
                attempt=len(attempts) + 1,
                elapsed_ms=elapsed_ms(started_at),
                ok=False,
                error_code=normalized.error_code,
                error_detail=normalized.detail,
                retryable=normalized.retryable,
            )
        )
        raise
