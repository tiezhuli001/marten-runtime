import json
from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.channels.feishu.models import FeishuInboundEvent
from marten_runtime.gateway.dedupe import build_dedupe_key
from marten_runtime.gateway.models import InboundEnvelope


def parse_feishu_callback(payload: dict) -> FeishuInboundEvent:
    if {"event_id", "chat_id", "user_id", "text"}.issubset(payload.keys()):
        message_id = str(payload.get("message_id") or payload["event_id"])
        return FeishuInboundEvent(
            event_id=str(payload["event_id"]),
            message_id=message_id,
            chat_id=str(payload["chat_id"]),
            user_id=str(payload["user_id"]),
            sender_type=str(payload.get("sender_type") or ""),
            chat_type=str(payload.get("chat_type") or ""),
            message_type=str(payload.get("message_type") or ""),
            mentions=_extract_mentions(payload.get("mentions")),
            text=str(payload["text"]),
        )
    header = payload.get("header", {})
    event = payload.get("event", {})
    sender_wrapper = event.get("sender", {})
    sender = sender_wrapper.get("sender_id", {})
    message = event.get("message", {})
    content = _extract_text(message.get("content", ""))
    event_id = str(header.get("event_id") or payload.get("event_id") or message.get("message_id") or "")
    message_id = str(message.get("message_id") or header.get("event_id") or payload.get("message_id") or event_id)
    chat_id = str(message.get("chat_id") or payload.get("chat_id") or "")
    user_id = str(
        sender.get("user_id")
        or sender.get("open_id")
        or sender.get("union_id")
        or payload.get("user_id")
        or ""
    )
    return FeishuInboundEvent(
        event_id=event_id,
        message_id=message_id,
        chat_id=chat_id,
        user_id=user_id,
        sender_type=str(sender_wrapper.get("sender_type") or payload.get("sender_type") or ""),
        chat_type=str(message.get("chat_type") or payload.get("chat_type") or ""),
        message_type=str(message.get("message_type") or payload.get("message_type") or ""),
        mentions=_extract_mentions(message.get("mentions") or payload.get("mentions")),
        text=content,
    )


def to_inbound_envelope(event: FeishuInboundEvent) -> InboundEnvelope:
    message_id = event.message_id or event.event_id
    dedupe_key = build_dedupe_key(
        channel_id="feishu",
        conversation_id=event.chat_id,
        user_id=event.user_id,
        message_id=message_id,
    )
    return InboundEnvelope(
        channel_id="feishu",
        user_id=event.user_id,
        conversation_id=event.chat_id,
        message_id=message_id,
        body=event.text,
        received_at=datetime.now(timezone.utc),
        dedupe_key=dedupe_key,
        trace_id=f"trace_{uuid4().hex[:8]}",
    )


def _extract_text(content: object) -> str:
    if isinstance(content, dict):
        direct_text = str(content.get("text", ""))
        if direct_text:
            return direct_text
        rich_text = _extract_rich_text(content)
        if rich_text:
            return rich_text
        return ""
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            return content
        if isinstance(decoded, dict):
            direct_text = str(decoded.get("text", ""))
            if direct_text:
                return direct_text
            rich_text = _extract_rich_text(decoded)
            if rich_text:
                return rich_text
    return ""


def _extract_rich_text(payload: dict) -> str:
    fragments: list[str] = []
    candidate_payloads: list[dict] = []
    if isinstance(payload.get("content"), list):
        candidate_payloads.append(payload)
    for locale_payload in payload.values():
        if isinstance(locale_payload, dict) and isinstance(locale_payload.get("content"), list):
            candidate_payloads.append(locale_payload)
    for candidate in candidate_payloads:
        rows = candidate.get("content")
        for row in rows:
            if not isinstance(row, list):
                continue
            for block in row:
                if not isinstance(block, dict):
                    continue
                tag = str(block.get("tag", "")).strip().lower()
                if tag == "text":
                    text = str(block.get("text", ""))
                    if text:
                        fragments.append(text)
                    continue
                if tag == "at":
                    mention_name = (
                        str(block.get("user_name") or block.get("name") or block.get("text") or "").strip()
                    )
                    if mention_name:
                        fragments.append(f"@{mention_name}")
    return "".join(fragments).strip()


def _extract_mentions(mentions: object) -> list[str]:
    if not isinstance(mentions, list):
        return []
    result: list[str] = []
    for item in mentions:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("key")
        if name is None:
            continue
        result.append(str(name))
    return result
