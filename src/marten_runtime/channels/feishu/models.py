from datetime import datetime

from pydantic import BaseModel, Field

from marten_runtime.gateway.models import InboundEnvelope


class FeishuInboundEvent(BaseModel):
    event_id: str
    message_id: str
    chat_id: str
    user_id: str
    sender_type: str = ""
    chat_type: str = ""
    message_type: str = ""
    mentions: list[str] = Field(default_factory=list)
    text: str


class FeishuWebsocketClientConfig(BaseModel):
    auto_reconnect: bool = True
    reconnect_count: int = -1
    reconnect_interval_s: int = 5
    reconnect_nonce_s: int = 0
    ping_interval_s: int = 120


class FeishuWebsocketEndpoint(BaseModel):
    url: str
    client_config: FeishuWebsocketClientConfig = Field(default_factory=FeishuWebsocketClientConfig)


class FeishuWebsocketState(BaseModel):
    running: bool = False
    connected: bool = False
    lock_acquired: bool = False
    endpoint_url: str | None = None
    service_id: str | None = None
    connection_id: str | None = None
    reconnect_attempts: int = 0
    last_error: str | None = None
    last_message_id: str | None = None
    last_trace_id: str | None = None
    last_event_id: str | None = None
    last_status: str | None = None
    last_event_at: datetime | None = None


class FeishuDispatchResult(BaseModel):
    status: str
    body: dict[str, object]
    envelope: InboundEnvelope | None = None
    event: FeishuInboundEvent | None = None
    delivery_results: list[object] = Field(default_factory=list)
