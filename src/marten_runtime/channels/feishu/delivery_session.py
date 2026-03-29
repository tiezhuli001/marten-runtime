from datetime import datetime, timezone

from pydantic import BaseModel


class FeishuDeliverySession(BaseModel):
    channel_id: str
    conversation_id: str
    run_id: str
    trace_id: str
    created_at: datetime
    updated_at: datetime
    message_id: str | None = None
    status: str = "active"
    progress_count: int = 0
    last_event_type: str | None = None
    last_event_id: str | None = None
    last_sequence: int = 0


class InMemoryFeishuDeliverySessionStore:
    def __init__(self) -> None:
        self._active: dict[tuple[str, str, str], FeishuDeliverySession] = {}
        self._closed: list[FeishuDeliverySession] = []

    def start_or_get(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        run_id: str,
        trace_id: str,
    ) -> FeishuDeliverySession:
        key = (channel_id, conversation_id, run_id)
        existing = self._active.get(key)
        if existing is not None:
            return existing
        now = datetime.now(timezone.utc)
        session = FeishuDeliverySession(
            channel_id=channel_id,
            conversation_id=conversation_id,
            run_id=run_id,
            trace_id=trace_id,
            created_at=now,
            updated_at=now,
        )
        self._active[key] = session
        return session

    def append_progress(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        run_id: str,
        trace_id: str,
        message_id: str,
        event_id: str,
        sequence: int,
    ) -> FeishuDeliverySession:
        session = self.start_or_get(
            channel_id=channel_id,
            conversation_id=conversation_id,
            run_id=run_id,
            trace_id=trace_id,
        )
        session.message_id = message_id
        session.progress_count += 1
        session.last_event_type = "progress"
        session.last_event_id = event_id
        session.last_sequence = sequence
        session.updated_at = datetime.now(timezone.utc)
        return session

    def finalize_success(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        run_id: str,
        trace_id: str,
        message_id: str,
        event_id: str,
        sequence: int,
    ) -> FeishuDeliverySession:
        return self._finalize(
            channel_id=channel_id,
            conversation_id=conversation_id,
            run_id=run_id,
            trace_id=trace_id,
            message_id=message_id,
            event_id=event_id,
            event_type="final",
            sequence=sequence,
        )

    def finalize_error(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        run_id: str,
        trace_id: str,
        message_id: str,
        event_id: str,
        sequence: int,
    ) -> FeishuDeliverySession:
        return self._finalize(
            channel_id=channel_id,
            conversation_id=conversation_id,
            run_id=run_id,
            trace_id=trace_id,
            message_id=message_id,
            event_id=event_id,
            event_type="error",
            sequence=sequence,
        )

    def active_count(self) -> int:
        return len(self._active)

    def list_active(self) -> list[FeishuDeliverySession]:
        return list(self._active.values())

    def closed_count(self) -> int:
        return len(self._closed)

    def stats(self) -> dict[str, object]:
        return {
            "active_count": self.active_count(),
            "closed_count": self.closed_count(),
            "active_sessions": [item.model_dump(mode="json") for item in self.list_active()],
        }

    def _finalize(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        run_id: str,
        trace_id: str,
        message_id: str,
        event_id: str,
        event_type: str,
        sequence: int,
    ) -> FeishuDeliverySession:
        key = (channel_id, conversation_id, run_id)
        session = self._active.pop(
            key,
            self.start_or_get(
                channel_id=channel_id,
                conversation_id=conversation_id,
                run_id=run_id,
                trace_id=trace_id,
            ),
        )
        session.message_id = message_id
        session.status = "closed"
        session.last_event_type = event_type
        session.last_event_id = event_id
        session.last_sequence = sequence
        session.updated_at = datetime.now(timezone.utc)
        self._closed.append(session.model_copy(deep=True))
        return session
