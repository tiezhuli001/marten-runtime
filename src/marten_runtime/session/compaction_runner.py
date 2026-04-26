from __future__ import annotations

from typing import Literal
from uuid import uuid4

from marten_runtime.runtime.llm_client import ConversationMessage, LLMClient, LLMRequest
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.compaction_prompt import build_compaction_prompt
from marten_runtime.session.models import SessionMessage
from marten_runtime.tools.registry import ToolSnapshot


def build_compactable_prefix(
    session_messages: list[SessionMessage] | None,
    *,
    current_message: str,
    preserved_tail_user_turns: int = 8,
) -> tuple[list[SessionMessage], list[SessionMessage], int]:
    indexed_replayable = [
        (index, item)
        for index, item in enumerate(list(session_messages or []))
        if item.role in {"user", "assistant"}
    ]
    if indexed_replayable:
        _, last_message = indexed_replayable[-1]
        if last_message.role == "user" and last_message.content == current_message:
            indexed_replayable = indexed_replayable[:-1]
    if preserved_tail_user_turns <= 0:
        replayable = [item for _, item in indexed_replayable]
        return [], replayable, 0
    selected_start = _preserved_tail_start(indexed_replayable, preserved_tail_user_turns)
    if selected_start is None:
        replayable = [item for _, item in indexed_replayable]
        return [], replayable, 0
    prefix_entries = indexed_replayable[:selected_start]
    tail_entries = indexed_replayable[selected_start:]
    return (
        [item for _, item in prefix_entries],
        [item for _, item in tail_entries],
        tail_entries[0][0],
    )


def _preserved_tail_start(
    indexed_replayable: list[tuple[int, SessionMessage]],
    preserved_tail_user_turns: int,
) -> int | None:
    user_turn_indices = [
        replayable_index
        for replayable_index, (_, message) in enumerate(indexed_replayable)
        if message.role == "user"
    ]
    if len(user_turn_indices) <= preserved_tail_user_turns:
        return None
    return user_turn_indices[-preserved_tail_user_turns]


def run_compaction(
    *,
    llm: LLMClient,
    session_id: str,
    current_message: str,
    session_messages: list[SessionMessage] | None,
    preserved_tail_user_turns: int = 8,
    prompt_mode: Literal["history_summary", "context_pressure"] = "context_pressure",
    trigger_kind: str | None = "context_pressure_proactive",
) -> CompactedContext | None:
    prefix, _tail, prefix_end_index = build_compactable_prefix(
        session_messages,
        current_message=current_message,
        preserved_tail_user_turns=preserved_tail_user_turns,
    )
    if not prefix:
        return None
    reply = llm.complete(
        LLMRequest(
            session_id=session_id,
            trace_id=f"trace_compact_{uuid4().hex[:8]}",
            message="请基于以上会话生成交接摘要。",
            agent_id="compaction",
            app_id="compaction",
            system_prompt=build_compaction_prompt(prompt_mode=prompt_mode),
            conversation_messages=[ConversationMessage(role=item.role, content=item.content) for item in prefix],
            skill_snapshot_id="skill_default",
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_empty"),
        )
    )
    summary_text = (reply.final_text or "").strip()
    if not summary_text:
        return None
    return CompactedContext(
        compact_id=f"cmp_{uuid4().hex[:8]}",
        session_id=session_id,
        summary_text=summary_text,
        source_message_range=[0, prefix_end_index],
        preserved_tail_user_turns=preserved_tail_user_turns,
        trigger_kind=trigger_kind,
    )
