from __future__ import annotations

import inspect
from collections.abc import Callable

from marten_runtime.runtime.cooperative_stop import call_with_cooperative_timeout
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
    stop_event=None,
    deadline_monotonic: float | None = None,
) -> dict:
    parameters = inspect.signature(transport).parameters
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    kwargs: dict[str, object] = {}
    if len(parameters) >= 4:
        kwargs["timeout_seconds"] = timeout_seconds
    if stop_event is not None and (accepts_kwargs or "stop_event" in parameters):
        kwargs["stop_event"] = stop_event
    if deadline_monotonic is not None and (
        accepts_kwargs or "deadline_monotonic" in parameters
    ):
        kwargs["deadline_monotonic"] = deadline_monotonic
    return transport(url, headers, body, **kwargs)


def invoke_transport(
    *,
    transport: Transport,
    url: str,
    headers: dict[str, str],
    body: dict,
    timeout_seconds: int,
    attempts: list[ProviderCallAttempt],
    stop_event=None,
    deadline_monotonic: float | None = None,
) -> dict:
    started_at = __import__('time').perf_counter()
    try:
        result = call_with_cooperative_timeout(
            lambda effective_timeout_seconds: call_transport(
                transport,
                url,
                headers,
                body,
                timeout_seconds=max(0.05, float(effective_timeout_seconds)),
                stop_event=stop_event,
                deadline_monotonic=deadline_monotonic,
            ),
            default_timeout_seconds=timeout_seconds,
            stop_event=stop_event,
            deadline_monotonic=deadline_monotonic,
            timeout_seconds_override=timeout_seconds,
            cancelled_message="PROVIDER_CALL_CANCELLED",
            timed_out_message="PROVIDER_CALL_TIMED_OUT",
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
