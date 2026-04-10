from datetime import datetime

from pydantic import BaseModel, Field


class InboundEnvelope(BaseModel):
    channel_id: str
    user_id: str
    conversation_id: str
    message_id: str
    body: str
    requested_agent_id: str | None = None
    received_at: datetime
    enqueued_at: datetime | None = None
    started_at: datetime | None = None
    dedupe_key: str = Field(min_length=8)
    trace_id: str
