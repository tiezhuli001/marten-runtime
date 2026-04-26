from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marten_runtime.channels.feishu.rendering import FeishuCardProtocol


_NEWLINE_GAP_RE = re.compile(r"\n{3,}")
_PROTOCOL_SHELL_TOKENS = {
    "```",
    "feishu_card",
    "<minimax:tool_call>",
    "</invoke>",
    "</minimax:tool_call>",
}


def default_card_title(event_type: str) -> str:
    if event_type == "error":
        return "处理失败"
    return "处理结果"


def strip_protocol_shell_residue(text: str, *, protocol_context: bool = False) -> str:
    if not protocol_context:
        return str(text or "").rstrip()
    normalized = str(text or "").rstrip()
    while normalized:
        lines = normalized.splitlines()
        if not lines:
            break
        last_line = lines[-1].strip()
        if last_line not in _PROTOCOL_SHELL_TOKENS:
            break
        if last_line == "```":
            fence_count = sum(1 for line in lines if line.strip().startswith("```"))
            if fence_count % 2 == 0:
                break
        normalized = "\n".join(lines[:-1]).rstrip()
    return normalized


def derive_plain_title(text: str, *, event_type: str) -> str:
    if event_type == "error":
        return default_card_title(event_type)
    collapsed = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if "多次模型/工具往返" in collapsed and "当前可用 MCP 服务" in collapsed:
        return "链路结果"
    cleaned_lines = [
        re.sub(r"\*\*(.*?)\*\*", r"\1", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]
    if not cleaned_lines:
        return default_card_title(event_type)
    first = cleaned_lines[0].rstrip("：:。!！")
    if first.startswith("当前上下文使用详情"):
        return "当前上下文使用详情"
    if first.startswith("当前有 ") and "可见会话" in first:
        return "会话列表"
    if first.startswith("已切换到新会话"):
        return "已切换到新会话"
    if first.startswith("已切换到会话"):
        return first
    if first.startswith("当前已在会话"):
        return first
    if first.startswith("已受理，子 agent"):
        return "子任务已受理"
    if re.match(r"^(当前|现在).*(北京时间|时间)", first):
        return "当前时间"
    if re.match(r"^现在是(?:[A-Za-z_./+-]+)?\s*\d{4}年\d{1,2}月\d{1,2}日", first):
        return "当前时间"
    commit_title = derive_commit_title(first)
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
        if looks_like_semantic_title(normalized):
            return normalized
    return default_card_title(event_type)


def derive_commit_title(text: str) -> str | None:
    if "提交" not in text:
        return None
    if "最近提交" not in text and "最近一次提交" not in text:
        return None
    repo_match = re.search(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\b", text)
    if repo_match is not None:
        return f"{repo_match.group(1)} 最近提交"
    return "仓库最近提交"


def looks_like_semantic_title(text: str) -> bool:
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


def default_card_template(event_type: str) -> str:
    if event_type == "error":
        return "red"
    return "indigo"


def dedupe_visible_text_against_protocol(text: str, protocol: "FeishuCardProtocol") -> str:
    if not text:
        return text
    if any(section.items for section in protocol.sections):
        text = strip_visible_markdown_table_blocks(text)
        text = strip_visible_bullet_lines(text)
    protocol_items = {
        normalize_bullet_text(item)
        for section in protocol.sections
        for item in section.items
        if normalize_bullet_text(item)
    }
    if not protocol_items:
        return text
    kept_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullet_body = stripped[2:].strip()
            if normalize_bullet_text(bullet_body) in protocol_items:
                continue
        kept_lines.append(line.rstrip())
    deduped = "\n".join(kept_lines)
    return _NEWLINE_GAP_RE.sub("\n\n", deduped).strip()


def strip_visible_bullet_lines(text: str) -> str:
    kept_lines: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("- "):
            continue
        kept_lines.append(line.rstrip())
    stripped = "\n".join(kept_lines)
    return _NEWLINE_GAP_RE.sub("\n\n", stripped).strip()


def strip_visible_markdown_table_blocks(text: str) -> str:
    lines = text.splitlines()
    kept_lines: list[str] = []
    index = 0
    while index < len(lines):
        if is_markdown_table_header(lines, index):
            index += 2
            while index < len(lines) and is_markdown_table_row(lines[index]):
                index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            continue
        kept_lines.append(lines[index].rstrip())
        index += 1
    stripped = "\n".join(kept_lines)
    return _NEWLINE_GAP_RE.sub("\n\n", stripped).strip()


def is_markdown_table_header(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return is_markdown_table_row(lines[index]) and is_markdown_table_divider(lines[index + 1])


def is_markdown_table_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return False
    return stripped.count("|") >= 3


def is_markdown_table_divider(line: str) -> bool:
    if not is_markdown_table_row(line):
        return False
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if not cells:
        return False
    return all(cell and set(cell) <= {"-", ":", " "} for cell in cells)


def normalize_bullet_text(text: str) -> str:
    normalized = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def render_section_item(item: str) -> str:
    normalized = item.strip()
    if not normalized:
        return "-"
    if is_ordered_or_bulleted_item(normalized):
        return normalized
    return f"- {normalized}"


def is_ordered_or_bulleted_item(text: str) -> bool:
    return re.match(r"^(?:[-*•]\s+|\d+[.)]\s+|[A-Za-z][.)]\s+)", text) is not None
