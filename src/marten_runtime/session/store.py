from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compaction_job import SessionCompactionJob
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage, SessionRecord
from marten_runtime.session.tool_outcome_summary import ToolOutcomeSummary, coerce_tool_outcome_summary


class SessionStore:
    def __init__(self) -> None:
        self._items: dict[str, SessionRecord] = {}
        self._conversation_index: dict[str, str] = {}
        self._bindings: dict[tuple[str, str, str], str] = {}
        self._compaction_jobs: dict[str, SessionCompactionJob] = {}
        self._compaction_job_order: list[str] = []

    def create(
        self,
        session_id: str,
        conversation_id: str,
        config_snapshot_id: str = "cfg_bootstrap",
        bootstrap_manifest_id: str = "boot_default",
        *,
        channel_id: str = "",
        user_id: str = "",
    ) -> SessionRecord:
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            session_id=session_id,
            conversation_id=conversation_id,
            channel_id=channel_id,
            user_id=user_id,
            created_at=now,
            updated_at=now,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id=bootstrap_manifest_id,
        )
        record.history.append(SessionMessage.system("created"))
        self._refresh_message_count(record)
        self._items[session_id] = record
        self._conversation_index[conversation_id] = session_id
        self.bind_conversation(
            channel_id=channel_id,
            conversation_id=conversation_id,
            session_id=session_id,
            user_id=user_id,
        )
        return record

    def create_child_session(
        self,
        *,
        parent_session_id: str,
        conversation_id: str,
        session_id: str | None = None,
        agent_id: str | None = None,
        active_agent_id: str | None = None,
    ) -> SessionRecord:
        parent = self._items[parent_session_id]
        child = self.create(
            session_id=session_id or f"sess_{uuid4().hex[:8]}",
            conversation_id=conversation_id,
            config_snapshot_id=parent.config_snapshot_id,
            bootstrap_manifest_id=parent.bootstrap_manifest_id,
            channel_id=parent.channel_id,
            user_id=parent.user_id,
        )
        child.parent_session_id = parent.session_id
        child.session_kind = "subagent"
        child.lineage_depth = parent.lineage_depth + 1
        child.agent_id = parent.agent_id if agent_id is None else agent_id
        child.active_agent_id = (
            parent.active_agent_id if active_agent_id is None else active_agent_id
        )
        return child

    def get_or_create_for_conversation(
        self,
        conversation_id: str,
        config_snapshot_id: str = "cfg_bootstrap",
        bootstrap_manifest_id: str = "boot_default",
        *,
        channel_id: str = "",
        user_id: str = "",
    ) -> SessionRecord:
        session_id = self.resolve_session_for_conversation(
            channel_id=channel_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        if session_id is not None:
            return self._items[session_id]
        return self.create(
            session_id=f"sess_{uuid4().hex[:8]}",
            conversation_id=conversation_id,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id=bootstrap_manifest_id,
            channel_id=channel_id,
            user_id=user_id,
        )

    def bind_conversation(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        session_id: str,
        user_id: str = "",
    ) -> None:
        for key, bound_session_id in list(self._bindings.items()):
            if bound_session_id == session_id and key != (
                channel_id,
                conversation_id,
                user_id,
            ):
                del self._bindings[key]
        if user_id:
            for key in list(self._bindings):
                bound_channel_id, bound_conversation_id, bound_user_id = key
                if (
                    bound_channel_id == channel_id
                    and bound_conversation_id == conversation_id
                    and bound_user_id in {"", user_id}
                    and key != (channel_id, conversation_id, user_id)
                ):
                    del self._bindings[key]
        for bound_conversation_id, bound_session_id in list(self._conversation_index.items()):
            if bound_session_id == session_id and bound_conversation_id != conversation_id:
                del self._conversation_index[bound_conversation_id]
        self._conversation_index[conversation_id] = session_id
        self._bindings[(channel_id, conversation_id, user_id)] = session_id
        record = self._items.get(session_id)
        if record is not None:
            record.conversation_id = conversation_id
            record.channel_id = channel_id
            record.user_id = user_id or record.user_id

    def resolve_session_for_conversation(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        user_id: str = "",
    ) -> str | None:
        if user_id:
            session_id = self._bindings.get((channel_id, conversation_id, user_id))
            if session_id is not None:
                return session_id
            legacy_session_id = self._bindings.get((channel_id, conversation_id, ""))
            legacy_record = (
                self._items.get(legacy_session_id) if legacy_session_id is not None else None
            )
            if legacy_record is not None and not legacy_record.user_id:
                return legacy_record.session_id
            return None
        bound_session_ids = {
            bound_session_id
            for (
                bound_channel_id,
                bound_conversation_id,
                bound_user_id,
            ), bound_session_id in self._bindings.items()
            if bound_channel_id == channel_id
            and bound_conversation_id == conversation_id
            and bound_user_id == ""
            and not self._items[bound_session_id].user_id
        }
        if len(bound_session_ids) == 1:
            return next(iter(bound_session_ids))
        if channel_id:
            return None
        session_id = self._conversation_index.get(conversation_id)
        record = self._items.get(session_id) if session_id is not None else None
        if record is not None and not record.user_id:
            return record.session_id
        return None

    def append_message(self, session_id: str, message: SessionMessage) -> SessionRecord:
        record = self._items[session_id]
        record.history.append(message)
        self._refresh_message_count(record)
        record.updated_at = message.created_at
        record.last_event_at = message.created_at
        return record

    def remove_last_message_if_match(
        self,
        session_id: str,
        message: SessionMessage,
        *,
        restore_updated_at: datetime,
        restore_last_event_at: datetime | None,
    ) -> SessionRecord:
        record = self._items[session_id]
        if not record.history:
            return record
        last = record.history[-1]
        if (
            last.role != message.role
            or last.content != message.content
            or last.created_at != message.created_at
        ):
            return record
        record.history.pop()
        self._refresh_message_count(record)
        record.updated_at = restore_updated_at
        record.last_event_at = restore_last_event_at
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
        record.agent_id = agent_id
        return record

    def set_catalog_metadata(
        self,
        session_id: str,
        *,
        user_id: str,
        agent_id: str,
        session_title: str,
        session_preview: str,
    ) -> SessionRecord:
        record = self._items[session_id]
        record.user_id = user_id
        record.agent_id = agent_id
        record.session_title = session_title
        record.session_preview = session_preview
        self.bind_conversation(
            channel_id=record.channel_id,
            conversation_id=record.conversation_id,
            session_id=session_id,
            user_id=user_id,
        )
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

    def set_compacted_context_if_newer(
        self,
        session_id: str,
        compacted_context: CompactedContext,
    ) -> bool:
        record = self._items[session_id]
        if not _should_apply_compacted_context(record.latest_compacted_context, compacted_context):
            return False
        self.set_compacted_context(session_id, compacted_context)
        return True

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

    def enqueue_compaction_job(self, **payload) -> dict[str, object]:  # noqa: ANN003
        job = SessionCompactionJob(**payload)
        self._compaction_jobs[job.job_id] = job
        self._compaction_job_order.append(job.job_id)
        return job.model_dump(mode="json")

    def claim_next_compaction_job(self) -> dict[str, object] | None:
        for job_id in self._compaction_job_order:
            job = self._compaction_jobs[job_id]
            if job.status != "queued":
                continue
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            return job.model_dump(mode="json")
        return None

    def get_compaction_job(self, job_id: str) -> dict[str, object]:
        return self._compaction_jobs[job_id].model_dump(mode="json")

    def list_compaction_jobs(self) -> list[dict[str, object]]:
        return [
            self._compaction_jobs[job_id].model_dump(mode="json")
            for job_id in self._compaction_job_order
        ]

    def reset_running_compaction_jobs(self) -> None:
        for job in self._compaction_jobs.values():
            if job.status != "running":
                continue
            job.status = "queued"
            job.started_at = None
            job.finished_at = None
            job.result_reason = "requeued_startup"
            job.error_code = None
            job.error_text = None

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
    ) -> dict[str, object]:
        job = self._compaction_jobs[job_id]
        job.status = "succeeded"
        job.finished_at = datetime.now(timezone.utc)
        job.queue_wait_ms = max(0, int(queue_wait_ms))
        job.compaction_llm_ms = max(0, int(compaction_llm_ms))
        job.persist_ms = max(0, int(persist_ms))
        job.result_reason = result_reason
        job.source_range_end = source_range_end
        job.write_applied = bool(write_applied)
        job.error_code = None
        job.error_text = None
        return job.model_dump(mode="json")

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
    ) -> dict[str, object]:
        job = self._compaction_jobs[job_id]
        job.status = "failed"
        job.finished_at = datetime.now(timezone.utc)
        job.queue_wait_ms = max(0, int(queue_wait_ms))
        job.compaction_llm_ms = max(0, int(compaction_llm_ms))
        job.persist_ms = max(0, int(persist_ms))
        job.result_reason = result_reason
        job.error_code = error_code
        job.error_text = error_text
        job.write_applied = False
        return job.model_dump(mode="json")

    def list_sessions(self) -> list[SessionRecord]:
        return sorted(
            self._items.values(),
            key=lambda item: item.last_event_at or item.updated_at,
            reverse=True,
        )

    def count(self) -> int:
        return len(self._items)

    def binding_count(self) -> int:
        return len(self._bindings)

    def storage_kind(self) -> str:
        return "memory"

    def storage_path(self) -> str | None:
        return None

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
