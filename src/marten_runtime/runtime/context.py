from __future__ import annotations

from pydantic import BaseModel, Field

from marten_runtime.session.compaction import compact_context
from marten_runtime.session.models import SessionMessage
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
    working_context: dict[str, object] = Field(default_factory=dict)
    working_context_text: str | None = None
    skill_snapshot: SkillSnapshot = Field(
        default_factory=lambda: SkillSnapshot(skill_snapshot_id="skill_default")
    )
    activated_skill_ids: list[str] = Field(default_factory=list)
    skill_heads_text: str | None = None
    capability_catalog_text: str | None = None
    always_on_skill_text: str | None = None
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
    activated_skill_bodies: list[str] | None = None,
    replay_limit: int = 6,
) -> RuntimeContext:
    replay = replay_session_messages(
        session_messages or [],
        current_message=current_message,
        limit=replay_limit,
    )
    snapshot = compact_context(
        session_id=session_id,
        active_goal=current_message,
        token_budget=2048,
        recent_decisions=[
            message.content for message in replay if message.role == "assistant"
        ][-2:],
        source_message_range=[max(0, len((session_messages or [])) - len(replay)), len(session_messages or [])],
        tool_snapshot_id=tool_snapshot.tool_snapshot_id,
    )
    working_context = rehydrate_context(snapshot)
    return RuntimeContext(
        system_prompt=system_prompt,
        conversation_messages=[
            RuntimeMessage(role=message.role, content=message.content)
            for message in replay
        ],
        working_context=working_context,
        working_context_text=_render_working_context(working_context),
        skill_snapshot=skill_snapshot or SkillSnapshot(skill_snapshot_id="skill_default"),
        activated_skill_ids=list(activated_skill_ids or []),
        skill_heads_text=skill_heads_text,
        capability_catalog_text=capability_catalog_text,
        always_on_skill_text=always_on_skill_text,
        activated_skill_bodies=list(activated_skill_bodies or []),
        context_snapshot_id=snapshot.snapshot_id,
        tool_snapshot=tool_snapshot,
    )


def _render_working_context(working_context: dict[str, object]) -> str | None:
    if not working_context:
        return None
    lines = ["Working context:"]
    for key, value in working_context.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)
