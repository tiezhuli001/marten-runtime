from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.session.models import SessionMessage, SessionRecord


class SessionStore:
    def __init__(self) -> None:
        self._items: dict[str, SessionRecord] = {}
        self._conversation_index: dict[str, str] = {}

    def create(
        self,
        session_id: str,
        conversation_id: str,
        config_snapshot_id: str = "cfg_bootstrap",
        bootstrap_manifest_id: str = "boot_default",
    ) -> SessionRecord:
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            session_id=session_id,
            conversation_id=conversation_id,
            created_at=now,
            updated_at=now,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id=bootstrap_manifest_id,
        )
        record.history.append(SessionMessage.system("created"))
        self._items[session_id] = record
        self._conversation_index[conversation_id] = session_id
        return record

    def get_or_create_for_conversation(
        self,
        conversation_id: str,
        config_snapshot_id: str = "cfg_bootstrap",
        bootstrap_manifest_id: str = "boot_default",
    ) -> SessionRecord:
        session_id = self._conversation_index.get(conversation_id)
        if session_id is not None:
            return self._items[session_id]
        return self.create(
            session_id=f"sess_{uuid4().hex[:8]}",
            conversation_id=conversation_id,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id=bootstrap_manifest_id,
        )

    def append_message(self, session_id: str, message: SessionMessage) -> SessionRecord:
        record = self._items[session_id]
        record.history.append(message)
        record.updated_at = message.created_at
        record.last_event_at = message.created_at
        return record

    def mark_run(self, session_id: str, run_id: str, event_at: datetime) -> SessionRecord:
        record = self._items[session_id]
        record.state = "running"
        record.last_run_id = run_id
        record.last_event_at = event_at
        record.updated_at = event_at
        return record

    def set_active_agent(self, session_id: str, agent_id: str) -> SessionRecord:
        record = self._items[session_id]
        record.active_agent_id = agent_id
        return record

    def get(self, session_id: str) -> SessionRecord:
        return self._items[session_id]

    def list_sessions(self) -> list[SessionRecord]:
        return list(self._items.values())

    def count(self) -> int:
        return len(self._items)
