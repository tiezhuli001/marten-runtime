from datetime import datetime

from pydantic import BaseModel, Field


class InboundEnvelope(BaseModel):
    channel_id: str
    user_id: str
    conversation_id: str
    message_id: str
    body: str
    received_at: datetime
    dedupe_key: str = Field(min_length=8)
    trace_id: str
