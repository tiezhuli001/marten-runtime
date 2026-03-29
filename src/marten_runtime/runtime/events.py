from datetime import datetime

from pydantic import BaseModel, Field


class OutboundEvent(BaseModel):
    session_id: str
    run_id: str
    event_id: str
    event_type: str
    sequence: int
    trace_id: str
    visibility: str = "channel"
    payload: dict = Field(default_factory=dict)
    created_at: datetime
