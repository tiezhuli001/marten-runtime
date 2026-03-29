from datetime import datetime, timezone

from pydantic import BaseModel, Field

from marten_runtime.session.manifest import build_context_manifest


class ContextSnapshot(BaseModel):
    snapshot_id: str
    session_id: str
    compaction_level: str
    token_budget: int
    active_goal: str
    recent_files: list[str] = Field(default_factory=list)
    open_todos: list[str] = Field(default_factory=list)
    recent_decisions: list[str] = Field(default_factory=list)
    pending_risks: list[str] = Field(default_factory=list)
    source_message_range: list[int] = Field(default_factory=list)
    compaction_reason: str = "auto_budget_pressure"
    bootstrap_manifest_id: str = "boot_default"
    skill_snapshot_id: str = "skill_default"
    tool_snapshot_id: str = "tool_default"
    manifest_id: str = "ctx_manifest_default"
    continuation_hint: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def memory_flush(session_id: str, active_goal: str, recent_decisions: list[str], pending_risks: list[str]) -> str:
    lines = [f"session={session_id}", f"goal={active_goal}"]
    lines.extend(f"decision={item}" for item in recent_decisions)
    lines.extend(f"risk={item}" for item in pending_risks)
    return "\n".join(lines)


def compact_context(
    session_id: str,
    active_goal: str,
    token_budget: int,
    compaction_level: str = "auto",
    recent_files: list[str] | None = None,
    open_todos: list[str] | None = None,
    recent_decisions: list[str] | None = None,
    pending_risks: list[str] | None = None,
    source_message_range: list[int] | None = None,
    bootstrap_manifest_id: str = "boot_default",
    skill_snapshot_id: str = "skill_default",
    tool_snapshot_id: str = "tool_default",
    compaction_reason: str | None = None,
) -> ContextSnapshot:
    recent_files = recent_files or []
    open_todos = open_todos or []
    recent_decisions = recent_decisions or []
    pending_risks = pending_risks or []
    source_message_range = source_message_range or []
    if compaction_level in {"auto", "manual"}:
        memory_flush(session_id, active_goal, recent_decisions, pending_risks)
    manifest = build_context_manifest(
        run_id=session_id.replace("sess_", "run_"),
        config_snapshot_id="cfg_bootstrap",
        bootstrap_manifest_id=bootstrap_manifest_id,
        prompt_mode="full",
        bootstrap_sources=["apps/example_assistant/AGENTS.md"],
        working_context={
            "active_goal": active_goal,
            "recent_files": recent_files,
            "open_todos": open_todos,
            "continuation_hint": active_goal,
        },
        skill_snapshot_id=skill_snapshot_id,
        tool_snapshot_id=tool_snapshot_id,
        token_estimate_by_layer={"working_context": 120, "runtime_assets": 60},
    )
    return ContextSnapshot(
        snapshot_id=f"ctx_{session_id}",
        session_id=session_id,
        compaction_level=compaction_level,
        token_budget=token_budget,
        active_goal=active_goal,
        recent_files=recent_files,
        open_todos=open_todos,
        recent_decisions=recent_decisions,
        pending_risks=pending_risks,
        source_message_range=source_message_range,
        compaction_reason=compaction_reason or f"{compaction_level}_budget_pressure",
        bootstrap_manifest_id=bootstrap_manifest_id,
        skill_snapshot_id=skill_snapshot_id,
        tool_snapshot_id=tool_snapshot_id,
        manifest_id=manifest.manifest_id,
        continuation_hint=active_goal,
    )
