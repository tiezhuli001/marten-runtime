from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class AutomationDispatchRecord(BaseModel):
    automation_id: str
    scheduled_for: str
    delivery_target: str
    dedupe_key: str
    dispatched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
