from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel

from marten_runtime.channels.feishu.rendering_support import (
    dedupe_visible_text_against_protocol,
    default_card_template,
    default_card_title,
    derive_plain_title,
    render_section_item,
)
from marten_runtime.channels.feishu.usage import format_usage_summary

logger = logging.getLogger(__name__)
_INLINE_JSON_PREFIX_CHARS = set(" \t\r\n。.!?！？：:;；,，)]）】}\"'」』")
_FEISHU_CARD_BLOCK_RE = re.compile(r"\n*```feishu_card\s*\n(?P<body>[\s\S]*?)\n```(?P<trailing>[\s\S]*)$")
_FEISHU_CARD_JSON_BLOCK_RE = re.compile(r"\n*```json\s*\n(?P<body>[\s\S]*?)\n```\s*$")
_FEISHU_CARD_INVOKE_RE = re.compile(
    r"\n*(?:<minimax:tool_call>\s*)?<invoke name=\"feishu_card\">\s*(?P<body>[\s\S]*?)\s*</invoke>\s*(?:</minimax:tool_call>\s*)?$"
)
_FEISHU_CARD_BARE_RE = re.compile(r"\n*feishu_card\s*\n(?P<body>\{[\s\S]*\})\s*$")
_FEISHU_CARD_BARE_JSON_BLOCK_RE = re.compile(r"\n*feishu_card\s*\n```json\s*\n(?P<body>[\s\S]*?)\n```\s*$")
_FEISHU_CARD_TRAILING_JSON_RE = re.compile(r"\n+(?P<body>\{[\s\S]*\})\s*$")
_FEISHU_CARD_PARAM_RE = re.compile(
    r"<parameter name=\"(?P<name>[^\"]+)\">(?P<value>[\s\S]*?)</parameter>"
)


class FeishuCardSection(BaseModel):
    title: str | None = None
    items: list[str] = []


class FeishuCardProtocol(BaseModel):
    title: str | None = None
    summary: str | None = None
    sections: list[FeishuCardSection] = []


class SubagentTerminalCard(BaseModel):
    title: str
    summary: str | None = None
    visible_text: str | None = None


_SUBAGENT_SYSTEM_COMPLETED_RE = re.compile(
    r"^subagent task completed:\s*(?P<label>[^\n]+?)(?:\nsummary:\s*(?P<detail>[\s\S]*))?$"
)
_SUBAGENT_SYSTEM_FAILED_RE = re.compile(
    r"^subagent task failed:\s*(?P<label>[^\n]+?)(?:\nerror:\s*(?P<detail>[\s\S]*))?$"
)
_SUBAGENT_SYSTEM_TIMED_OUT_RE = re.compile(r"^subagent task timed out:\s*(?P<label>[^\n]+?)\s*$")
_SUBAGENT_SYSTEM_CANCELLED_RE = re.compile(r"^subagent task cancelled:\s*(?P<label>[^\n]+?)\s*$")
_BACKGROUND_COMPLETED_RE = re.compile(
    r"^后台任务已完成[:：]\s*(?P<label>[^\n]+?)(?:\n(?P<detail>[\s\S]*))?$"
)
_BACKGROUND_STATUS_RE = re.compile(
    r"^后台任务(?P<status>failed|timed_out|cancelled)[:：]\s*(?P<label>[^\n]+?)(?:\n(?P<detail>[\s\S]*))?$"
)



def build_feishu_card_protocol_guard_instruction() -> str:
    return (
        "当前回合需要遵守 Feishu 结构化回复协议。若最终答案不是单行直接回答，"
        "必须以且仅以一个尾部 fenced `feishu_card` block 结束；"
        "代码围栏标识必须是 `feishu_card`，不要使用 `json` 或其他围栏；"
        "可见正文只保留一行摘要，且 `feishu_card` 后不要再追加任何文字。"
    )

def parse_feishu_card_protocol(text: str) -> tuple[str, FeishuCardProtocol | None]:
    try:
        visible_text, payload = _extract_protocol_payload(text)
        if payload is None:
            return text, None
        card = _validate_protocol_payload(payload)
    except Exception as exc:
        logger.info("feishu_card_protocol action=ignore reason=%s", str(exc))
        return text, None
    return visible_text, card


def _extract_protocol_payload(text: str) -> tuple[str, dict[str, object] | None]:
    fenced = _FEISHU_CARD_BLOCK_RE.search(text)
    if fenced:
        prefix = text[: fenced.start()].rstrip()
        trailing = (fenced.group("trailing") or "").strip()
        visible_text = prefix if not trailing else "\n\n".join(part for part in [prefix, trailing] if part)
        payload = json.loads(fenced.group("body"))
        return visible_text, payload

    bare_json_block = _FEISHU_CARD_BARE_JSON_BLOCK_RE.search(text)
    if bare_json_block:
        visible_text = text[: bare_json_block.start()].rstrip()
        payload = _unwrap_feishu_card_payload(json.loads(bare_json_block.group("body")))
        return visible_text, payload

    json_fenced = _FEISHU_CARD_JSON_BLOCK_RE.search(text)
    if json_fenced:
        visible_text = text[: json_fenced.start()].rstrip()
        payload = _unwrap_feishu_card_payload(json.loads(json_fenced.group("body")))
        return visible_text, payload

    invoke = _FEISHU_CARD_INVOKE_RE.search(text)
    if invoke:
        visible_text = text[: invoke.start()].rstrip()
        payload: dict[str, object] = {}
        for match in _FEISHU_CARD_PARAM_RE.finditer(invoke.group("body")):
            name = match.group("name")
            value = match.group("value").strip()
            if name == "sections":
                payload[name] = json.loads(value)
            else:
                payload[name] = value
        return visible_text, payload

    bare = _FEISHU_CARD_BARE_RE.search(text)
    if bare:
        visible_text = text[: bare.start()].rstrip()
        payload = json.loads(bare.group("body"))
        return visible_text, payload

    trailing_json = _FEISHU_CARD_TRAILING_JSON_RE.search(text)
    if trailing_json:
        visible_text = text[: trailing_json.start()].rstrip()
        payload = _unwrap_feishu_card_payload(json.loads(trailing_json.group("body")))
        return visible_text, payload

    inline_trailing = _extract_inline_trailing_json_object(text)
    if inline_trailing is not None:
        visible_text, payload = inline_trailing
        return visible_text, _unwrap_feishu_card_payload(payload)
    return text, None


def _extract_inline_trailing_json_object(text: str) -> tuple[str, dict[str, object]] | None:
    end = len(text.rstrip())
    if end == 0 or text[end - 1] != "}":
        return None

    depth = 0
    in_string = False
    escaped = False
    start: int | None = None
    for index in range(end - 1, -1, -1):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "}":
            depth += 1
            continue
        if char == "{":
            depth -= 1
            if depth == 0:
                start = index
                break
            continue

    if start is None:
        return None
    if start > 0 and text[start - 1] not in _INLINE_JSON_PREFIX_CHARS:
        return None

    candidate = text[start:end]
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("root_not_object")
    visible_text = text[:start].rstrip()
    return visible_text, payload


def _unwrap_feishu_card_payload(payload: object) -> dict[str, object]:
    if isinstance(payload, dict) and set(payload) == {"feishu_card"}:
        inner = payload["feishu_card"]
        if not isinstance(inner, dict):
            raise ValueError("feishu_card_wrapper_not_object")
        return inner
    if not isinstance(payload, dict):
        raise ValueError("root_not_object")
    return payload


def _validate_protocol_payload(payload: object) -> FeishuCardProtocol:
    if not isinstance(payload, dict):
        raise ValueError("root_not_object")
    unsupported = sorted(set(payload) - {"title", "summary", "sections"})
    if unsupported:
        raise ValueError(f"unsupported_keys:{','.join(unsupported)}")
    return FeishuCardProtocol.model_validate(payload)


def render_final_reply_card(
    text: str,
    *,
    event_type: str = "final",
    usage_summary: dict[str, int] | None = None,
) -> dict[str, object]:
    subagent_terminal = _parse_subagent_terminal_card(text)
    if subagent_terminal is not None:
        return _build_generic_card(
            title=subagent_terminal.title,
            visible_text=subagent_terminal.visible_text,
            summary=subagent_terminal.summary,
            sections=[],
            fallback_text=text,
            header_template=default_card_template(event_type),
            usage_summary=usage_summary,
        )
    visible_text, protocol = parse_feishu_card_protocol(text)
    if protocol is not None:
        visible_text = dedupe_visible_text_against_protocol(visible_text, protocol)
    if protocol is None:
        fallback_card = _render_fallback_structured_card(
            visible_text,
            event_type=event_type,
            usage_summary=usage_summary,
        )
        if fallback_card is not None:
            return fallback_card
    sections = protocol.sections if protocol is not None else []
    return _build_generic_card(
        title=protocol.title if protocol is not None else derive_plain_title(visible_text, event_type=event_type),
        visible_text=visible_text,
        summary=protocol.summary if protocol is not None else None,
        sections=sections,
        fallback_text=text,
        header_template=default_card_template(event_type),
        usage_summary=usage_summary,
    )


def _parse_subagent_terminal_card(text: str) -> SubagentTerminalCard | None:
    stripped = text.strip()
    patterns: list[tuple[re.Pattern[str], str, str | None]] = [
        (_BACKGROUND_COMPLETED_RE, "后台任务完成", "任务"),
        (_SUBAGENT_SYSTEM_COMPLETED_RE, "子任务完成", "任务"),
        (_BACKGROUND_STATUS_RE, _map_background_status_title, "任务"),
        (_SUBAGENT_SYSTEM_FAILED_RE, "子任务失败", "任务"),
        (_SUBAGENT_SYSTEM_TIMED_OUT_RE, "子任务超时", "任务"),
        (_SUBAGENT_SYSTEM_CANCELLED_RE, "子任务已取消", "任务"),
    ]
    for pattern, title, summary_prefix in patterns:
        match = pattern.match(stripped)
        if match is None:
            continue
        resolved_title = title(match.group("status")) if callable(title) else title
        label = (match.groupdict().get("label") or "").strip()
        detail = (match.groupdict().get("detail") or "").strip() or None
        summary = f"{summary_prefix}：{label}" if label else None
        return SubagentTerminalCard(
            title=resolved_title,
            summary=summary,
            visible_text=detail,
        )
    return None


def _map_background_status_title(status: str) -> str:
    return {
        "failed": "后台任务失败",
        "timed_out": "后台任务超时",
        "cancelled": "后台任务已取消",
    }.get(status, default_card_title("error"))


def _render_fallback_structured_card(
    text: str,
    *,
    event_type: str = "final",
    usage_summary: dict[str, int] | None = None,
) -> dict[str, object] | None:
    lines = [line.rstrip() for line in text.splitlines()]
    bullet_indexes = [index for index, line in enumerate(lines) if line.lstrip().startswith("- ")]
    if len(bullet_indexes) < 2:
        return None
    first_bullet = bullet_indexes[0]
    last_bullet = bullet_indexes[-1]
    leading = "\n".join(line.strip() for line in lines[:first_bullet]).strip()
    bullets = [lines[index].strip()[2:].strip() for index in bullet_indexes]
    trailing = "\n".join(line.strip() for line in lines[last_bullet + 1 :]).strip()
    title, summary = _derive_fallback_heading(leading)
    return _build_generic_card(
        title=title or default_card_title(event_type),
        visible_text=None,
        summary=summary,
        sections=[FeishuCardSection(title=None, items=bullets)],
        note=trailing or None,
        fallback_text=text,
        header_template=default_card_template(event_type),
        usage_summary=usage_summary,
    )


def _derive_fallback_heading(text: str) -> tuple[str | None, str | None]:
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", text).strip()
    if not cleaned:
        return None, None
    if "，" in cleaned:
        title, summary = cleaned.split("，", 1)
        return title.rstrip("：:。 "), summary.rstrip("：:。 ")
    return cleaned.rstrip("：:。 "), None


def _markdown_div(content: str) -> dict[str, object]:
    return {
        "tag": "markdown",
        "content": content,
    }


def _hr() -> dict[str, object]:
    return {"tag": "hr"}


def _build_generic_card(
    *,
    title: str | None,
    visible_text: str | None,
    summary: str | None,
    sections: list[FeishuCardSection],
    note: str | None = None,
    fallback_text: str | None = None,
    header_template: str = "indigo",
    usage_summary: dict[str, int] | None = None,
) -> dict[str, object]:
    elements: list[dict[str, object]] = []
    lead = (visible_text or "").strip()
    if lead:
        elements.append(_markdown_div(lead))
    if summary:
        if elements:
            elements.append(_hr())
        elements.append(_markdown_div(f"**📌 {summary}**"))
    normalized_sections = [section for section in sections if section.items]
    for section in normalized_sections:
        section_title = section.title or "详情"
        elements.append(_markdown_div(f"**🗂️ {section_title}**"))
        elements.append(_markdown_div("\n".join(render_section_item(item) for item in section.items)))
    if note:
        elements.append(_hr())
        elements.append(_markdown_div(f"<font color='grey'>💬 {note}</font>"))
    usage_text = format_usage_summary(usage_summary)
    if usage_text:
        elements.append(_hr())
        elements.append(_markdown_div(f"<font color='grey'>{usage_text}</font>"))
    if not elements:
        elements.append(_markdown_div(fallback_text or ""))
    card: dict[str, object] = {
        "schema": "2.0",
        "config": {
            "wide_screen_mode": True,
            "enable_forward": True,
        },
        "body": {
            "elements": elements,
        },
    }
    if title:
        card["header"] = {
            "title": {
                "tag": "plain_text",
                "content": title,
            },
            "template": header_template,
        }
    return card
