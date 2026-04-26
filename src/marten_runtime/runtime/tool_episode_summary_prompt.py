from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from marten_runtime.session.tool_outcome_summary import ToolOutcomeFact, _trim_text

if TYPE_CHECKING:
    from marten_runtime.runtime.llm_client import ToolExchange


TOOL_EPISODE_SUMMARY_SYSTEM_PROMPT = """你负责生成一段很薄的跨轮工具摘要。

只根据给定 episode 输出 JSON，不要输出额外解释。
要求：
- summary: 1 句，描述这一轮工具调用完成了什么
- facts: 最多 3 条，仅保留下一轮真正有价值的短事实
- volatile: 如果结果强时效（例如当前时间、热门榜单、动态计数）则为 true
- keep_next_turn: 默认 false。只有当下一轮很可能需要明确承接这一轮结果时才为 true，例如用户明显会继续引用刚得到的结果、要求解释刚得到的结果、或后台 accepted/queued/running 状态需要后续继续跟进
- 对已经在本轮完整结束的一次性事实/列表/状态回答，keep_next_turn 应为 false
- refresh_hint: 可选；若再次被问到且应重查，可写短提示
- 即使最终回复为了遵守用户要求而省略细节，也要尽量在 facts 中保留稳定且高价值的隐藏事实
- 禁止复制大段 tool payload / JSON / markdown
- 禁止编造没有出现在 episode 里的事实
"""

TOOL_EPISODE_SUMMARY_BLOCK_MARKER = "tool_episode_summary"
_TOOL_EPISODE_SUMMARY_BLOCK_RE = re.compile(
    r"\n*```tool_episode_summary\s*\n(?P<body>[\s\S]*?)\n```\s*$"
)


class ToolEpisodeSummaryDraft(BaseModel):
    summary: str
    facts: list[ToolOutcomeFact] = Field(default_factory=list)
    volatile: bool = False
    keep_next_turn: bool = False
    refresh_hint: str = ""


class ToolFollowupRender(BaseModel):
    final_text: str
    summary_draft: ToolEpisodeSummaryDraft | None = None


def render_tool_followup_summary_instruction() -> str:
    return (
        "在正常回答用户后，请在末尾追加一个 ```tool_episode_summary``` 代码块。"
        "代码块内只放 JSON，字段必须包含 summary/facts/volatile/keep_next_turn/refresh_hint。"
        "summary 要概括这一轮工具调用完成了什么；facts 最多 3 条，只保留下一轮真正有价值的短事实；"
        "若结果强时效则 volatile=true；keep_next_turn 默认应为 false，只有下一轮很可能明确承接这轮结果时才设为 true。"
        "先回答用户，再输出代码块，不要只输出 JSON。"
    )


def render_tool_episode_summary_input(
    *,
    user_message: str,
    tool_history: list[ToolExchange],
    final_reply: str,
    max_tool_result_chars: int = 1000,
) -> str:
    tool_items: list[dict[str, object]] = []
    for item in tool_history:
        tool_items.append(
            {
                "tool_name": item.tool_name,
                "tool_payload": item.tool_payload,
                "tool_result": _trim_text(json.dumps(item.tool_result, ensure_ascii=False), limit=max_tool_result_chars),
            }
        )
    payload = {
        "user_message": _trim_text(user_message, limit=500),
        "tool_history": tool_items,
        "final_reply": _trim_text(final_reply, limit=600),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_tool_episode_summary_response(text: str) -> ToolEpisodeSummaryDraft:
    parsed = json.loads(text)
    facts: list[ToolOutcomeFact] = []
    for raw in list(parsed.get("facts") or [])[:3]:
        if isinstance(raw, dict) and raw.get("key") is not None and raw.get("value") is not None:
            facts.append(ToolOutcomeFact.create(str(raw["key"]), raw["value"]))
    return ToolEpisodeSummaryDraft(
        summary=_trim_text(str(parsed.get("summary") or ""), limit=220),
        facts=facts,
        volatile=bool(parsed.get("volatile", False)),
        keep_next_turn=bool(parsed.get("keep_next_turn", False)),
        refresh_hint=_trim_text(str(parsed.get("refresh_hint") or ""), limit=120),
    )


def extract_tool_episode_summary_block(text: str) -> ToolFollowupRender:
    normalized = str(text or "").strip()
    match = _TOOL_EPISODE_SUMMARY_BLOCK_RE.search(normalized)
    if not match:
        return ToolFollowupRender(final_text=normalized, summary_draft=None)
    visible_text = normalized[: match.start()].rstrip()
    try:
        draft = parse_tool_episode_summary_response(match.group("body"))
    except Exception:
        draft = None
    if not visible_text and draft is not None and draft.summary.strip():
        visible_text = draft.summary.strip()
    return ToolFollowupRender(final_text=visible_text.strip(), summary_draft=draft)
