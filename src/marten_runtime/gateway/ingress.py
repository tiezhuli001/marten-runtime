from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.gateway.dedupe import build_dedupe_key
from marten_runtime.gateway.models import InboundEnvelope


def ingest_message(payload: dict[str, str]) -> InboundEnvelope:
    return InboundEnvelope(
        channel_id=payload["channel_id"],
        user_id=payload["user_id"],
        conversation_id=payload["conversation_id"],
        message_id=payload["message_id"],
        body=payload["body"],
        requested_agent_id=payload.get("requested_agent_id"),
        source_transport="http_api",
        received_at=datetime.now(timezone.utc),
        dedupe_key=build_dedupe_key(
            channel_id=payload["channel_id"],
            conversation_id=payload["conversation_id"],
            user_id=payload["user_id"],
            message_id=payload["message_id"],
        ),
        trace_id=f"trace_{uuid4().hex[:8]}",
    )
