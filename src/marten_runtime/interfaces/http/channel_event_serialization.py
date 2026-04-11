from __future__ import annotations

import re

from marten_runtime.channels.feishu.rendering import (
    parse_feishu_card_protocol,
    render_final_reply_card,
)
from marten_runtime.channels.feishu.usage import build_usage_summary_from_history
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.history import InMemoryRunHistory

_FEISHU_CARD_HISTORY_BLOCK_RE = re.compile(
    r"\n*```feishu_card\s*\n[\s\S]*?(?:\n```)?\s*$"
)


def history_visible_text(text: str) -> str:
    visible_text, _ = parse_feishu_card_protocol(text)
    if visible_text != text:
        return visible_text
    return _FEISHU_CARD_HISTORY_BLOCK_RE.sub("", text).rstrip()


def serialize_event_for_channel(
    event: OutboundEvent,
    *,
    channel_id: str,
    run_history: InMemoryRunHistory | None,
) -> dict[str, object]:
    payload = dict(event.payload)
    if channel_id == "feishu" and event.event_type in {"final", "error"}:
        raw_text = str(payload.get("text", ""))
        visible_text = history_visible_text(raw_text)
        payload["text"] = visible_text
        payload["card"] = render_final_reply_card(
            raw_text,
            event_type=event.event_type,
            usage_summary=build_usage_summary_from_history(run_history, event.run_id),
        )
    item = event.model_dump(mode="json")
    item["payload"] = payload
    return item
