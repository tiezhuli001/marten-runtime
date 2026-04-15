from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


def raise_if_interrupted(
    *,
    stop_event=None,
    deadline_monotonic: float | None = None,
    cancelled_message: str = "OPERATION_CANCELLED",
    timed_out_message: str = "OPERATION_TIMED_OUT",
) -> None:
    if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
        raise TimeoutError(cancelled_message)
    if deadline_monotonic is not None and time.monotonic() >= float(deadline_monotonic):
        raise TimeoutError(timed_out_message)


def effective_timeout_seconds(
    default_timeout_seconds: float,
    *,
    timeout_seconds_override: float | None = None,
    deadline_monotonic: float | None = None,
    minimum_seconds: float = 0.05,
) -> float:
    timeout = float(default_timeout_seconds)
    if timeout_seconds_override is not None:
        timeout = min(timeout, float(timeout_seconds_override))
    if deadline_monotonic is not None:
        timeout = min(timeout, max(minimum_seconds, float(deadline_monotonic) - time.monotonic()))
    return max(minimum_seconds, timeout)


def call_with_cooperative_timeout(
    operation: Callable[[float], T],
    *,
    default_timeout_seconds: float,
    stop_event=None,
    deadline_monotonic: float | None = None,
    timeout_seconds_override: float | None = None,
    cancelled_message: str = "OPERATION_CANCELLED",
    timed_out_message: str = "OPERATION_TIMED_OUT",
) -> T:
    raise_if_interrupted(
        stop_event=stop_event,
        deadline_monotonic=deadline_monotonic,
        cancelled_message=cancelled_message,
        timed_out_message=timed_out_message,
    )
    result = operation(
        effective_timeout_seconds(
            default_timeout_seconds,
            timeout_seconds_override=timeout_seconds_override,
            deadline_monotonic=deadline_monotonic,
        )
    )
    raise_if_interrupted(
        stop_event=stop_event,
        deadline_monotonic=deadline_monotonic,
        cancelled_message=cancelled_message,
        timed_out_message=timed_out_message,
    )
    return result


def interruptible_sleep(
    seconds: float,
    *,
    stop_event=None,
    deadline_monotonic: float | None = None,
    cancelled_message: str = "OPERATION_CANCELLED",
    timed_out_message: str = "OPERATION_TIMED_OUT",
    sleeper: Callable[[float], None] | None = None,
    poll_interval_seconds: float = 0.05,
) -> None:
    raise_if_interrupted(
        stop_event=stop_event,
        deadline_monotonic=deadline_monotonic,
        cancelled_message=cancelled_message,
        timed_out_message=timed_out_message,
    )
    remaining = max(0.0, float(seconds))
    sleep_fn = sleeper or time.sleep
    while remaining > 0:
        slice_seconds = min(remaining, poll_interval_seconds)
        if deadline_monotonic is not None:
            slice_seconds = min(slice_seconds, max(0.0, float(deadline_monotonic) - time.monotonic()))
        if slice_seconds <= 0:
            break
        sleep_fn(slice_seconds)
        remaining -= slice_seconds
        raise_if_interrupted(
            stop_event=stop_event,
            deadline_monotonic=deadline_monotonic,
            cancelled_message=cancelled_message,
            timed_out_message=timed_out_message,
        )
