from __future__ import annotations

from dataclasses import dataclass

from marten_runtime.channels.feishu.rendering import (
    normalize_feishu_durable_text,
    normalize_feishu_visible_text,
    render_final_reply_card,
)
from marten_runtime.channels.feishu.usage import build_usage_summary_from_history
from marten_runtime.runtime.history import InMemoryRunHistory


@dataclass(frozen=True)
class TerminalOutputNormalization:
    durable_text: str
    visible_text: str
    channel_payload: dict[str, object] | None = None


def normalize_terminal_output(
    *,
    raw_text: str,
    channel_id: str,
    event_type: str,
    run_history: InMemoryRunHistory | None = None,
    run_id: str | None = None,
) -> TerminalOutputNormalization:
    if event_type not in {"final", "error"}:
        return TerminalOutputNormalization(
            durable_text=raw_text,
            visible_text=raw_text,
        )
    if channel_id != "feishu":
        return TerminalOutputNormalization(
            durable_text=raw_text,
            visible_text=raw_text,
        )
    usage_summary = (
        build_usage_summary_from_history(run_history, run_id)
        if run_history is not None and run_id
        else None
    )
    visible_text = normalize_feishu_visible_text(raw_text)
    return TerminalOutputNormalization(
        durable_text=normalize_feishu_durable_text(raw_text),
        visible_text=visible_text,
        channel_payload=render_final_reply_card(
            raw_text,
            event_type=event_type,
            usage_summary=usage_summary,
        ),
    )
