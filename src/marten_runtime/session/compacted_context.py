from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class CompactedContext(BaseModel):
    compact_id: str
    session_id: str
    summary_text: str
    source_message_range: list[int] = Field(default_factory=list)
    preserved_tail_user_turns: int | None = None
    trigger_kind: str | None = None
    next_step: str | None = None
    open_todos: list[str] = Field(default_factory=list)
    pending_risks: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
