from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


SUBAGENT_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}


class SubagentTask(BaseModel):
    task_id: str = Field(default_factory=lambda: f"task_{uuid4().hex[:8]}")
    label: str
    status: str = "queued"
    parent_session_id: str
    parent_run_id: str
    parent_agent_id: str
    parent_allowed_tools: list[str] = Field(default_factory=list)
    origin_channel_id: str | None = None
    child_session_id: str
    child_run_id: str | None = None
    app_id: str
    agent_id: str
    tool_profile: str
    effective_tool_profile: str
    context_mode: str
    task_prompt: str
    notify_on_finish: bool = True
    include_parent_session_message: bool = True
    result_summary: str | None = None
    error_text: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
