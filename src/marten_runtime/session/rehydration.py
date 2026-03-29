from pydantic import BaseModel, Field

from marten_runtime.session.compaction import ContextSnapshot


class ChildSessionHandoff(BaseModel):
    parent_session_id: str
    active_goal: str
    task_scope: str
    recent_files: list[str] = Field(default_factory=list)
    open_todos: list[str] = Field(default_factory=list)
    relevant_constraints: list[str] = Field(default_factory=list)
    bootstrap_manifest_id: str = "boot_default"
    skill_snapshot_id: str = "skill_default"
    tool_snapshot_id: str = "tool_default"
    continuation_hint: str = ""
    prompt_mode: str = "child"


def build_child_handoff(
    snapshot: ContextSnapshot,
    *,
    task_scope: str,
    relevant_constraints: list[str] | None = None,
) -> ChildSessionHandoff:
    return ChildSessionHandoff(
        parent_session_id=snapshot.session_id,
        active_goal=snapshot.active_goal,
        task_scope=task_scope,
        recent_files=snapshot.recent_files,
        open_todos=snapshot.open_todos,
        relevant_constraints=relevant_constraints or [],
        bootstrap_manifest_id=snapshot.bootstrap_manifest_id,
        skill_snapshot_id=snapshot.skill_snapshot_id,
        tool_snapshot_id=snapshot.tool_snapshot_id,
        continuation_hint=snapshot.continuation_hint,
    )


def rehydrate_context(snapshot: ContextSnapshot) -> dict:
    return {
        "active_goal": snapshot.active_goal,
        "recent_files": snapshot.recent_files,
        "open_todos": snapshot.open_todos,
        "continuation_hint": snapshot.continuation_hint,
        "manifest_id": snapshot.manifest_id,
        "source_message_range": snapshot.source_message_range,
    }
