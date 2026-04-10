from __future__ import annotations

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
    preserved_tail_count: int = 2,
) -> tuple[list[SessionMessage], list[SessionMessage]]:
    replayable = [item for item in list(session_messages or []) if item.role in {"user", "assistant"}]
    if replayable and replayable[-1].role == "user" and replayable[-1].content == current_message:
        replayable = replayable[:-1]
    if preserved_tail_count <= 0 or len(replayable) <= preserved_tail_count:
        return [], replayable
    return replayable[:-preserved_tail_count], replayable[-preserved_tail_count:]


def run_compaction(
    *,
    llm: LLMClient,
    session_id: str,
    current_message: str,
    session_messages: list[SessionMessage] | None,
    preserved_tail_count: int = 2,
) -> CompactedContext | None:
    prefix, _tail = build_compactable_prefix(
        session_messages,
        current_message=current_message,
        preserved_tail_count=preserved_tail_count,
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
            system_prompt=build_compaction_prompt(),
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
        source_message_range=[0, len(prefix)],
        preserved_tail_count=preserved_tail_count,
    )
