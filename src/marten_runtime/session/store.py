from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage, SessionRecord
from marten_runtime.session.tool_outcome_summary import ToolOutcomeSummary


class SessionStore(ABC):
    @abstractmethod
    def create(
        self,
        session_id: str,
        conversation_id: str,
        config_snapshot_id: str = "cfg_bootstrap",
        bootstrap_manifest_id: str = "boot_default",
        *,
        channel_id: str = "",
        user_id: str = "",
    ) -> SessionRecord: ...

    @abstractmethod
    def create_child_session(
        self,
        *,
        parent_session_id: str,
        conversation_id: str,
        session_id: str | None = None,
        agent_id: str | None = None,
        active_agent_id: str | None = None,
    ) -> SessionRecord: ...

    @abstractmethod
    def get_or_create_for_conversation(
        self,
        conversation_id: str,
        config_snapshot_id: str = "cfg_bootstrap",
        bootstrap_manifest_id: str = "boot_default",
        *,
        channel_id: str = "",
        user_id: str = "",
    ) -> SessionRecord: ...

    @abstractmethod
    def bind_conversation(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        session_id: str,
        user_id: str = "",
    ) -> None: ...

    @abstractmethod
    def resolve_session_for_conversation(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        user_id: str = "",
    ) -> str | None: ...

    @abstractmethod
    def append_message(self, session_id: str, message: SessionMessage) -> SessionRecord: ...

    @abstractmethod
    def remove_last_message_if_match(
        self,
        session_id: str,
        message: SessionMessage,
        *,
        restore_updated_at: datetime,
        restore_last_event_at: datetime | None,
    ) -> SessionRecord: ...

    @abstractmethod
    def mark_run(self, session_id: str, run_id: str, event_at: datetime) -> SessionRecord: ...

    @abstractmethod
    def set_active_agent(self, session_id: str, agent_id: str) -> SessionRecord: ...

    @abstractmethod
    def set_catalog_metadata(
        self,
        session_id: str,
        *,
        user_id: str,
        agent_id: str,
        session_title: str,
        session_preview: str,
    ) -> SessionRecord: ...

    @abstractmethod
    def set_bootstrap_manifest(
        self,
        session_id: str,
        bootstrap_manifest_id: str,
    ) -> SessionRecord: ...

    @abstractmethod
    def set_compacted_context(
        self,
        session_id: str,
        compacted_context: CompactedContext,
    ) -> SessionRecord: ...

    @abstractmethod
    def set_compacted_context_if_newer(
        self,
        session_id: str,
        compacted_context: CompactedContext,
    ) -> bool: ...

    @abstractmethod
    def set_latest_actual_usage(
        self,
        session_id: str,
        usage: NormalizedUsage,
    ) -> SessionRecord: ...

    @abstractmethod
    def append_tool_outcome_summary(
        self,
        session_id: str,
        summary: ToolOutcomeSummary | dict[str, object],
        *,
        max_items: int = 5,
    ) -> SessionRecord: ...

    @abstractmethod
    def list_recent_tool_outcome_summaries(
        self,
        session_id: str,
        *,
        limit: int = 3,
    ) -> list[ToolOutcomeSummary]: ...

    @abstractmethod
    def get(self, session_id: str) -> SessionRecord: ...

    @abstractmethod
    def enqueue_compaction_job(self, **payload: object) -> dict[str, object]: ...

    @abstractmethod
    def claim_next_compaction_job(self) -> dict[str, object] | None: ...

    @abstractmethod
    def get_compaction_job(self, job_id: str) -> dict[str, object]: ...

    @abstractmethod
    def list_compaction_jobs(self) -> list[dict[str, object]]: ...

    @abstractmethod
    def reset_running_compaction_jobs(self) -> None: ...

    @abstractmethod
    def mark_compaction_job_succeeded(
        self,
        job_id: str,
        *,
        queue_wait_ms: int,
        compaction_llm_ms: int,
        persist_ms: int,
        result_reason: str,
        source_range_end: int | None,
        write_applied: bool,
    ) -> dict[str, object]: ...

    @abstractmethod
    def mark_compaction_job_failed(
        self,
        job_id: str,
        *,
        queue_wait_ms: int,
        compaction_llm_ms: int,
        persist_ms: int,
        result_reason: str,
        error_code: str | None = None,
        error_text: str | None = None,
    ) -> dict[str, object]: ...

    @abstractmethod
    def list_sessions(self) -> list[SessionRecord]: ...

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def binding_count(self) -> int: ...

    @abstractmethod
    def storage_kind(self) -> str: ...

    @abstractmethod
    def storage_path(self) -> str | None: ...

    @staticmethod
    def _refresh_message_count(record: SessionRecord) -> None:
        record.message_count = sum(1 for item in record.history if item.role != "system")


def _should_apply_compacted_context(
    current: CompactedContext | None,
    incoming: CompactedContext,
) -> bool:
    incoming_range = incoming.source_message_range or [0, 0]
    incoming_end = int(incoming_range[1]) if len(incoming_range) > 1 else 0
    if current is None:
        return True
    current_range = current.source_message_range or [0, 0]
    current_end = int(current_range[1]) if len(current_range) > 1 else 0
    if incoming_end > current_end:
        return True
    if incoming_end < current_end:
        return False
    return incoming.created_at >= current.created_at
