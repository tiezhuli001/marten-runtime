from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel

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
    visible_text, protocol = parse_feishu_card_protocol(text)
    if protocol is not None:
        visible_text = _dedupe_visible_text_against_protocol(visible_text, protocol)
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
        title=protocol.title if protocol is not None else _derive_plain_title(visible_text, event_type=event_type),
        visible_text=visible_text,
        summary=protocol.summary if protocol is not None else None,
        sections=sections,
        fallback_text=text,
        header_template=_default_card_template(event_type),
        usage_summary=usage_summary,
    )


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
        title=title or _default_card_title(event_type),
        visible_text=None,
        summary=summary,
        sections=[FeishuCardSection(title=None, items=bullets)],
        note=trailing or None,
        fallback_text=text,
        header_template=_default_card_template(event_type),
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
        elements.append(_markdown_div("\n".join(_render_section_item(item) for item in section.items)))
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


def _default_card_title(event_type: str) -> str:
    if event_type == "error":
        return "处理失败"
    return "处理结果"


def _derive_plain_title(text: str, *, event_type: str) -> str:
    if event_type == "error":
        return _default_card_title(event_type)
    cleaned_lines = [re.sub(r"\*\*(.*?)\*\*", r"\1", line).strip() for line in text.splitlines() if line.strip()]
    if not cleaned_lines:
        return _default_card_title(event_type)
    first = cleaned_lines[0].rstrip("：:。!！")
    if re.match(r"^(当前|现在).*(北京时间|时间)", first):
        return "当前时间"
    if re.match(r"^现在是(?:[A-Za-z_./+-]+)?\s*\d{4}年\d{1,2}月\d{1,2}日", first):
        return "当前时间"
    commit_title = _derive_commit_title(first)
    if commit_title is not None:
        return commit_title
    candidates = [first]
    if "，" in first:
        _, tail = first.split("，", 1)
        candidates.insert(0, tail.strip())
    for candidate in candidates:
        normalized = candidate
        normalized = re.sub(r"^(查到了|好的|可以|已为你|已经)\s*", "", normalized).strip()
        normalized = re.sub(r"如下$", "", normalized).strip()
        normalized = normalized.rstrip("：:。!！")
        if _looks_like_semantic_title(normalized):
            return normalized
    return _default_card_title(event_type)


def _derive_commit_title(text: str) -> str | None:
    if "提交" not in text:
        return None
    if "最近提交" not in text and "最近一次提交" not in text:
        return None
    repo_match = re.search(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\b", text)
    if repo_match is not None:
        return f"{repo_match.group(1)} 最近提交"
    return "仓库最近提交"


def _looks_like_semantic_title(text: str) -> bool:
    if not text or not (2 <= len(text) <= 18):
        return False
    if re.fullmatch(r"[A-Za-z0-9_./:+-]+", text):
        return False
    if not re.search(r"[\u4e00-\u9fff]", text):
        return False
    title_markers = (
        "详情",
        "概览",
        "列表",
        "状态",
        "信息",
        "结果",
        "时间",
        "窗口",
        "摘要",
        "总结",
        "任务",
        "仓库",
        "提交",
    )
    return any(marker in text for marker in title_markers)


def _default_card_template(event_type: str) -> str:
    if event_type == "error":
        return "red"
    return "indigo"


def _dedupe_visible_text_against_protocol(text: str, protocol: FeishuCardProtocol) -> str:
    if not text:
        return text
    if any(section.items for section in protocol.sections):
        text = _strip_visible_markdown_table_blocks(text)
        text = _strip_visible_bullet_lines(text)
    protocol_items = {
        _normalize_bullet_text(item)
        for section in protocol.sections
        for item in section.items
        if _normalize_bullet_text(item)
    }
    if not protocol_items:
        return text
    kept_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullet_body = stripped[2:].strip()
            if _normalize_bullet_text(bullet_body) in protocol_items:
                continue
        kept_lines.append(line.rstrip())
    deduped = "\n".join(kept_lines)
    deduped = re.sub(r"\n{3,}", "\n\n", deduped).strip()
    return deduped


def _strip_visible_bullet_lines(text: str) -> str:
    kept_lines: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("- "):
            continue
        kept_lines.append(line.rstrip())
    stripped = "\n".join(kept_lines)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def _strip_visible_markdown_table_blocks(text: str) -> str:
    lines = text.splitlines()
    kept_lines: list[str] = []
    index = 0
    while index < len(lines):
        if _is_markdown_table_header(lines, index):
            index += 2
            while index < len(lines) and _is_markdown_table_row(lines[index]):
                index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            continue
        kept_lines.append(lines[index].rstrip())
        index += 1
    stripped = "\n".join(kept_lines)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def _is_markdown_table_header(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return _is_markdown_table_row(lines[index]) and _is_markdown_table_divider(lines[index + 1])


def _is_markdown_table_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return False
    return stripped.count("|") >= 3


def _is_markdown_table_divider(line: str) -> bool:
    if not _is_markdown_table_row(line):
        return False
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if not cells:
        return False
    return all(cell and set(cell) <= {"-", ":", " "} for cell in cells)


def _normalize_bullet_text(text: str) -> str:
    normalized = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    normalized = normalized.replace("GitHub热榜推荐", "GitHub热榜推荐")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _render_section_item(item: str) -> str:
    normalized = item.strip()
    if not normalized:
        return "-"
    if _is_ordered_or_bulleted_item(normalized):
        return normalized
    return f"- {normalized}"


def _is_ordered_or_bulleted_item(text: str) -> bool:
    return re.match(r"^(?:[-*•]\s+|\d+[.)]\s+|[A-Za-z][.)]\s+)", text) is not None
