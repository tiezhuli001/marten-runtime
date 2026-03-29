from datetime import datetime, timezone

from pydantic import BaseModel


class ReceiptRecord(BaseModel):
    channel_id: str
    dedupe_key: str
    trace_id: str
    conversation_id: str
    message_id: str
    first_seen_at: datetime
    last_seen_at: datetime
    claim_count: int = 1


class ReceiptClaim(BaseModel):
    claimed: bool
    record: ReceiptRecord


class InMemoryReceiptStore:
    def __init__(self) -> None:
        self._items: dict[str, ReceiptRecord] = {}
        self._duplicate_total = 0
        self._last_duplicate_key: str | None = None

    def already_seen(self, dedupe_key: str) -> bool:
        return dedupe_key in self._items

    def claim(
        self,
        *,
        channel_id: str,
        dedupe_key: str,
        trace_id: str,
        conversation_id: str,
        message_id: str,
    ) -> ReceiptClaim:
        now = datetime.now(timezone.utc)
        record = self._items.get(dedupe_key)
        if record is not None:
            record.last_seen_at = now
            record.claim_count += 1
            self._duplicate_total += 1
            self._last_duplicate_key = dedupe_key
            return ReceiptClaim(claimed=False, record=record)
        record = ReceiptRecord(
            channel_id=channel_id,
            dedupe_key=dedupe_key,
            trace_id=trace_id,
            conversation_id=conversation_id,
            message_id=message_id,
            first_seen_at=now,
            last_seen_at=now,
        )
        self._items[dedupe_key] = record
        return ReceiptClaim(claimed=True, record=record)

    def stats(self) -> dict[str, object]:
        last_duplicate = None
        if self._last_duplicate_key is not None:
            last_duplicate = self._items[self._last_duplicate_key].model_dump(mode="json")
        return {
            "claimed_total": len(self._items),
            "duplicate_total": self._duplicate_total,
            "last_duplicate": last_duplicate,
        }
