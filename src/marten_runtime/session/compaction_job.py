from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class SessionCompactionJob(BaseModel):
    job_id: str = Field(default_factory=lambda: f"job_{uuid4().hex[:8]}")
    source_session_id: str
    current_message: str
    preserved_tail_user_turns: int
    source_message_range: list[int] = Field(default_factory=lambda: [0, 0])
    snapshot_message_count: int = 0
    compaction_profile_name: str | None = None
    enqueue_status: str = "queued"
    status: str = "queued"
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    queue_wait_ms: int = 0
    compaction_llm_ms: int = 0
    persist_ms: int = 0
    source_range_end: int | None = None
    write_applied: bool = False
    result_reason: str | None = None
    error_code: str | None = None
    error_text: str | None = None
