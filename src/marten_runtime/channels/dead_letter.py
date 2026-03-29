from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel


class DeliveryPayloadView(Protocol):
    chat_id: str
    run_id: str
    trace_id: str
    event_type: str
    event_id: str
    sequence: int

    def model_dump(self) -> dict[str, object]: ...


class DeadLetterRecord(BaseModel):
    dead_letter_id: str
    channel_id: str
    conversation_id: str
    run_id: str
    trace_id: str
    event_type: str
    event_id: str
    sequence: int
    attempts: int
    error: str
    payload: dict[str, object]
    created_at: datetime


class InMemoryDeadLetterQueue:
    def __init__(self) -> None:
        self._items: list[DeadLetterRecord] = []

    def record(self, *, channel_id: str, conversation_id: str, payload: DeliveryPayloadView, attempts: int, error: str) -> DeadLetterRecord:
        item = DeadLetterRecord(
            dead_letter_id=f"dlq_{len(self._items) + 1}",
            channel_id=channel_id,
            conversation_id=conversation_id,
            run_id=payload.run_id,
            trace_id=payload.trace_id,
            event_type=payload.event_type,
            event_id=payload.event_id,
            sequence=payload.sequence,
            attempts=attempts,
            error=error,
            payload=payload.model_dump(),
            created_at=datetime.now(timezone.utc),
        )
        self._items.append(item)
        return item

    def count(self) -> int:
        return len(self._items)

    def list_items(self) -> list[DeadLetterRecord]:
        return list(self._items)

    def stats(self) -> dict[str, object]:
        return {
            "count": self.count(),
            "items": [item.model_dump(mode="json") for item in self.list_items()],
        }
