from __future__ import annotations

from marten_runtime.apps.runtime_defaults import DEFAULT_AGENT_ID


def canonicalize_runtime_agent_id(
    agent_id: str | None,
    *,
    default: str | None = None,
) -> str | None:
    value = str(agent_id or "").strip()
    if not value:
        return default
    if value.lower() == "assistant":
        return DEFAULT_AGENT_ID
    return value
