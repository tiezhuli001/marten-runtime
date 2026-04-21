from __future__ import annotations

from pydantic import BaseModel, Field

from marten_runtime.session.compaction import compact_context
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.compaction_prompt import render_compact_summary_block
from marten_runtime.session.models import SessionMessage
from marten_runtime.session.tool_outcome_summary import ToolOutcomeSummary, render_tool_outcome_summary_block
from marten_runtime.session.rehydration import rehydrate_context
from marten_runtime.session.replay import replay_session_messages
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.tools.registry import ToolSnapshot


class RuntimeMessage(BaseModel):
    role: str
    content: str


class RuntimeContext(BaseModel):
    system_prompt: str | None = None
    conversation_messages: list[RuntimeMessage] = Field(default_factory=list)
    compact_summary_text: str | None = None
    tool_outcome_summary_text: str | None = None
    memory_text: str | None = None
    working_context: dict[str, object] = Field(default_factory=dict)
    working_context_text: str | None = None
    skill_snapshot: SkillSnapshot = Field(
        default_factory=lambda: SkillSnapshot(skill_snapshot_id="skill_default")
    )
    activated_skill_ids: list[str] = Field(default_factory=list)
    skill_heads_text: str | None = None
    capability_catalog_text: str | None = None
    always_on_skill_text: str | None = None
    channel_protocol_instruction_text: str | None = None
    activated_skill_bodies: list[str] = Field(default_factory=list)
    context_snapshot_id: str | None = None
    tool_snapshot: ToolSnapshot = Field(
        default_factory=lambda: ToolSnapshot(tool_snapshot_id="tool_empty")
    )


def assemble_runtime_context(
    *,
    session_id: str,
    current_message: str,
    system_prompt: str | None,
    session_messages: list[SessionMessage] | None,
    tool_snapshot: ToolSnapshot,
    skill_snapshot: SkillSnapshot | None = None,
    activated_skill_ids: list[str] | None = None,
    skill_heads_text: str | None = None,
    capability_catalog_text: str | None = None,
    always_on_skill_text: str | None = None,
    channel_protocol_instruction_text: str | None = None,
    activated_skill_bodies: list[str] | None = None,
    replay_limit: int = 6,
    compacted_context: CompactedContext | None = None,
    recent_tool_outcome_summaries: list[ToolOutcomeSummary | dict[str, object]] | None = None,
    memory_text: str | None = None,
) -> RuntimeContext:
    all_messages = session_messages or []
    replay_source = all_messages
    compact_summary_text: str | None = None
    if compacted_context is not None:
        compact_end = max(0, min(len(all_messages), compacted_context.source_message_range[1] if compacted_context.source_message_range else 0))
        replay_source = all_messages[compact_end:]
        limit = max(replay_limit, compacted_context.preserved_tail_count)
        replay = replay_session_messages(
            replay_source,
            current_message=current_message,
            limit=limit,
        )
        compact_summary_text = render_compact_summary_block(compacted_context.summary_text)
    else:
        replay = replay_session_messages(
            all_messages,
            current_message=current_message,
            limit=replay_limit,
        )
    context_source_messages = replay_source if compacted_context is not None else all_messages
    derived = _derive_context_inputs(context_source_messages, replay, current_message)
    tool_outcome_summary_text = render_tool_outcome_summary_block(recent_tool_outcome_summaries)
    snapshot = compact_context(
        session_id=session_id,
        active_goal=current_message,
        user_constraints=derived["user_constraints"],
        open_todos=derived["open_todos"],
        recent_decisions=derived["recent_decisions"],
        recent_results=derived["recent_results"],
        pending_risks=derived["pending_risks"],
        source_message_range=[max(0, len(all_messages) - len(replay)), len(all_messages)],
    )
    working_context = rehydrate_context(snapshot)
    return RuntimeContext(
        system_prompt=system_prompt,
        conversation_messages=[
            RuntimeMessage(role=message.role, content=message.content)
            for message in replay
        ],
        compact_summary_text=compact_summary_text,
        tool_outcome_summary_text=tool_outcome_summary_text,
        memory_text=memory_text,
        working_context=working_context,
        working_context_text=_render_working_context(working_context),
        skill_snapshot=skill_snapshot or SkillSnapshot(skill_snapshot_id="skill_default"),
        activated_skill_ids=list(activated_skill_ids or []),
        skill_heads_text=skill_heads_text,
        capability_catalog_text=capability_catalog_text,
        always_on_skill_text=always_on_skill_text,
        channel_protocol_instruction_text=channel_protocol_instruction_text,
        activated_skill_bodies=list(activated_skill_bodies or []),
        context_snapshot_id=snapshot.snapshot_id,
        tool_snapshot=tool_snapshot,
    )


def _render_working_context(working_context: dict[str, object]) -> str | None:
    if not working_context:
        return None
    lines: list[str] = []
    active_goal = str(working_context.get("active_goal", "")).strip()
    if active_goal:
        lines.extend(["当前目标:", f"- {active_goal}"])
    _append_section(lines, "用户约束", working_context.get("user_constraints"))
    _append_section(lines, "最近决策", working_context.get("recent_decisions"))
    _append_section(lines, "关键结果", working_context.get("recent_results"))
    _append_section(lines, "未完成事项", working_context.get("open_todos"))
    _append_section(lines, "风险/注意点", working_context.get("pending_risks"))
    continuation_hint = str(working_context.get("continuation_hint", "")).strip()
    if continuation_hint and continuation_hint != active_goal:
        lines.extend(["继续提示:", f"- {continuation_hint}"])
    if not lines:
        return None
    return "\n".join(lines)


def _append_section(lines: list[str], title: str, items: object) -> None:
    if not isinstance(items, list):
        return
    rendered = [str(item).strip() for item in items if str(item).strip()]
    if not rendered:
        return
    lines.append(f"{title}:")
    lines.extend(f"- {item}" for item in rendered)


def _derive_context_inputs(
    session_messages: list[SessionMessage],
    replay: list[SessionMessage],
    current_message: str,
) -> dict[str, list[str]]:
    user_messages = [message.content.strip() for message in session_messages if message.role == "user"]
    assistant_messages = [message.content.strip() for message in session_messages if message.role == "assistant"]
    return {
        "user_constraints": _dedupe_preserve_order(
            [message for message in user_messages if _looks_like_constraint(message)]
        )[-3:],
        "open_todos": _dedupe_preserve_order(
            [message for message in user_messages + assistant_messages if _looks_like_todo(message)]
        )[-3:],
        "recent_decisions": _dedupe_preserve_order(
            [_summarize_assistant_message(message.content) for message in replay if message.role == "assistant"]
        )[-3:],
        "recent_results": _dedupe_preserve_order(
            [
                summary
                for summary in (_extract_result_summary(message) for message in assistant_messages)
                if summary
            ]
        )[-3:],
        "pending_risks": _dedupe_preserve_order(
            [message for message in user_messages + assistant_messages if _looks_like_risk(message)]
        )[-3:],
    }


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _looks_like_constraint(content: str) -> bool:
    lowered = content.lower()
    keywords = ("请始终", "始终", "不要", "必须", "记住", "always", "must", "never", "do not", "don't")
    return any(keyword in content or keyword in lowered for keyword in keywords)


def _looks_like_todo(content: str) -> bool:
    lowered = content.lower()
    keywords = ("todo", "待办", "下一步", "接下来", "remaining", "follow-up")
    return any(keyword in lowered or keyword in content for keyword in keywords)


def _looks_like_risk(content: str) -> bool:
    lowered = content.lower()
    keywords = ("风险", "注意", "warning", "risk", "blocker")
    return any(keyword in lowered or keyword in content for keyword in keywords)


def _summarize_assistant_message(content: str) -> str:
    result_summary = _extract_result_summary(content)
    if result_summary:
        return result_summary
    normalized = " ".join(content.split())
    return normalized[:160]


def _extract_result_summary(content: str) -> str | None:
    for marker in ("结论:", "结果:", "已定位", "已完成", "resolved:", "found:"):
        if marker in content:
            summary = content.split(marker, 1)[1] if marker.endswith(":") else content[content.index(marker) :]
            return " ".join(summary.split())[:200]
    return None
