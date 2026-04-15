from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage, SessionRecord
from marten_runtime.session.tool_outcome_summary import ToolOutcomeSummary, coerce_tool_outcome_summary


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

    def create_child_session(
        self,
        *,
        parent_session_id: str,
        conversation_id: str,
        session_id: str | None = None,
    ) -> SessionRecord:
        parent = self._items[parent_session_id]
        child = self.create(
            session_id=session_id or f"sess_{uuid4().hex[:8]}",
            conversation_id=conversation_id,
            config_snapshot_id=parent.config_snapshot_id,
            bootstrap_manifest_id=parent.bootstrap_manifest_id,
        )
        child.parent_session_id = parent.session_id
        child.session_kind = "subagent"
        child.lineage_depth = parent.lineage_depth + 1
        return child

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

    def set_bootstrap_manifest(self, session_id: str, bootstrap_manifest_id: str) -> SessionRecord:
        record = self._items[session_id]
        record.bootstrap_manifest_id = bootstrap_manifest_id
        return record

    def set_compacted_context(self, session_id: str, compacted_context: CompactedContext) -> SessionRecord:
        record = self._items[session_id]
        record.latest_compacted_context = compacted_context
        record.last_compacted_at = compacted_context.created_at
        record.updated_at = compacted_context.created_at
        return record

    def set_latest_actual_usage(self, session_id: str, usage: NormalizedUsage) -> SessionRecord:
        record = self._items[session_id]
        record.latest_actual_usage = usage
        if usage.captured_at is not None:
            record.updated_at = usage.captured_at
        return record

    def append_tool_outcome_summary(
        self,
        session_id: str,
        summary: ToolOutcomeSummary | dict[str, object],
        *,
        max_items: int = 5,
    ) -> SessionRecord:
        record = self._items[session_id]
        item = coerce_tool_outcome_summary(summary)
        dedupe_key = item.dedupe_key()
        existing = [current for current in record.recent_tool_outcome_summaries if current.dedupe_key() != dedupe_key]
        record.recent_tool_outcome_summaries = [*existing, item][-max_items:]
        record.updated_at = item.created_at
        return record

    def list_recent_tool_outcome_summaries(
        self,
        session_id: str,
        *,
        limit: int = 3,
    ) -> list[ToolOutcomeSummary]:
        record = self._items[session_id]
        if limit <= 0:
            return []
        return list(record.recent_tool_outcome_summaries[-limit:])

    def get(self, session_id: str) -> SessionRecord:
        return self._items[session_id]

    def list_sessions(self) -> list[SessionRecord]:
        return list(self._items.values())

    def count(self) -> int:
        return len(self._items)
