from __future__ import annotations

import math
import time

from marten_runtime.runtime.llm_request_instructions import (
    is_tool_followup_request as _is_tool_followup_request,
)

def remaining_timeout_seconds(deadline_monotonic: float | None) -> float | None:
    if deadline_monotonic is None:
        return None
    return max(0.05, deadline_monotonic - time.monotonic())


def resolve_request_responses_api(
    request: object,
    *,
    model_name: str | None = None,
    supports_responses_api: bool | None = None,
    supports_chat_completions: bool | None = None,
) -> bool | None:
    normalized_model_name = str(model_name or getattr(request, "model_name", None) or "").lower()
    if normalized_model_name.startswith("gpt-5"):
        if supports_responses_api:
            return True
        if supports_chat_completions:
            return False
        return None
    if supports_chat_completions is False:
        return None
    return False


def resolve_request_timeout_seconds(
    request: object,
    *,
    default_seconds: int = 30,
    model_name: str | None = None,
    responses_api: bool | None = None,
) -> int:
    timeout_seconds_override = getattr(request, "timeout_seconds_override", None)
    if timeout_seconds_override is not None:
        return max(1, int(math.ceil(timeout_seconds_override)))
    remaining_seconds = remaining_timeout_seconds(getattr(request, "cooperative_deadline_monotonic", None))
    if remaining_seconds is not None:
        return max(1, int(math.ceil(remaining_seconds)))
    if getattr(request, "request_kind", None) == "subagent":
        return 60
    is_tool_followup = _is_tool_followup_request(request)
    normalized_model_name = str(model_name or getattr(request, "model_name", None) or "").lower()
    if responses_api is False and normalized_model_name.startswith("gpt-5"):
        if getattr(request, "request_kind", None) == "interactive" or is_tool_followup:
            return 40
    if is_tool_followup or getattr(request, "request_kind", None) in {"interactive", "finalization_retry"}:
        return 20
    return max(1, int(default_seconds))
