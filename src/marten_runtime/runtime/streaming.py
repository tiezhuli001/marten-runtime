from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.runtime.events import OutboundEvent


def make_event(
    session_id: str,
    run_id: str,
    sequence: int,
    event_type: str,
    payload: dict,
    trace_id: str | None = None,
) -> OutboundEvent:
    return OutboundEvent(
        session_id=session_id,
        run_id=run_id,
        event_id=f"evt_{uuid4().hex[:8]}",
        event_type=event_type,
        sequence=sequence,
        trace_id=trace_id or f"trace_{uuid4().hex[:8]}",
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )
