from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ContextSnapshot(BaseModel):
    snapshot_id: str
    session_id: str
    active_goal: str
    user_constraints: list[str] = Field(default_factory=list)
    recent_files: list[str] = Field(default_factory=list)
    open_todos: list[str] = Field(default_factory=list)
    recent_decisions: list[str] = Field(default_factory=list)
    recent_results: list[str] = Field(default_factory=list)
    pending_risks: list[str] = Field(default_factory=list)
    source_message_range: list[int] = Field(default_factory=list)
    continuation_hint: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def compact_context(
    session_id: str,
    active_goal: str,
    user_constraints: list[str] | None = None,
    recent_files: list[str] | None = None,
    open_todos: list[str] | None = None,
    recent_decisions: list[str] | None = None,
    recent_results: list[str] | None = None,
    pending_risks: list[str] | None = None,
    source_message_range: list[int] | None = None,
) -> ContextSnapshot:
    user_constraints = user_constraints or []
    recent_files = recent_files or []
    open_todos = open_todos or []
    recent_decisions = recent_decisions or []
    recent_results = recent_results or []
    pending_risks = pending_risks or []
    source_message_range = source_message_range or []
    return ContextSnapshot(
        snapshot_id=f"ctx_{session_id}",
        session_id=session_id,
        active_goal=active_goal,
        user_constraints=user_constraints,
        recent_files=recent_files,
        open_todos=open_todos,
        recent_decisions=recent_decisions,
        recent_results=recent_results,
        pending_risks=pending_risks,
        source_message_range=source_message_range,
        continuation_hint=active_goal,
    )
