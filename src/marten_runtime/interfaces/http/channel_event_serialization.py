from __future__ import annotations

from marten_runtime.channels.feishu.rendering import (
    normalize_feishu_durable_text,
    normalize_feishu_visible_text,
)
from marten_runtime.channels.output_normalization import (
    TerminalOutputNormalization,
    normalize_terminal_output,
)
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.history import InMemoryRunHistory


def history_durable_text(text: str) -> str:
    return normalize_feishu_durable_text(text)


def history_visible_text(text: str) -> str:
    return normalize_feishu_visible_text(text)


def serialize_event_for_channel(
    event: OutboundEvent,
    *,
    channel_id: str,
    run_history: InMemoryRunHistory | None,
    normalized_terminal_output: TerminalOutputNormalization | None = None,
) -> dict[str, object]:
    payload = dict(event.payload)
    if event.event_type in {"final", "error"}:
        normalized = normalized_terminal_output or normalize_terminal_output(
            raw_text=str(payload.get("text", "")),
            channel_id=channel_id,
            event_type=event.event_type,
            run_history=run_history,
            run_id=event.run_id,
        )
        payload["text"] = normalized.durable_text
        if normalized.channel_payload is not None:
            payload["card"] = normalized.channel_payload
    item = event.model_dump(mode="json")
    item["payload"] = payload
    return item
