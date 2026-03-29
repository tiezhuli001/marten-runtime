from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel


class RunRecord(BaseModel):
    run_id: str
    trace_id: str
    session_id: str
    job_id: str | None = None
    config_snapshot_id: str = "cfg_bootstrap"
    bootstrap_manifest_id: str = "boot_default"
    trigger_kind: str = "interactive"
    status: str = "pending"
    parent_run_id: str | None = None
    context_snapshot_id: str | None = None
    skill_snapshot_id: str = "skill_default"
    tool_snapshot_id: str = "tool_default"
    started_at: datetime
    finished_at: datetime | None = None
    delivery_status: str = "none"
    error_code: str | None = None


class InMemoryRunHistory:
    def __init__(self) -> None:
        self._items: dict[str, RunRecord] = {}

    def start(
        self,
        session_id: str,
        trace_id: str,
        config_snapshot_id: str,
        bootstrap_manifest_id: str,
        *,
        context_snapshot_id: str | None = None,
        skill_snapshot_id: str = "skill_default",
        tool_snapshot_id: str = "tool_default",
    ) -> RunRecord:
        record = RunRecord(
            run_id=f"run_{uuid4().hex[:8]}",
            trace_id=trace_id,
            session_id=session_id,
            config_snapshot_id=config_snapshot_id,
            bootstrap_manifest_id=bootstrap_manifest_id,
            context_snapshot_id=context_snapshot_id,
            skill_snapshot_id=skill_snapshot_id,
            tool_snapshot_id=tool_snapshot_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        self._items[record.run_id] = record
        return record

    def finish(self, run_id: str, delivery_status: str) -> RunRecord:
        record = self._items[run_id]
        record.status = "succeeded"
        record.delivery_status = delivery_status
        record.finished_at = datetime.now(timezone.utc)
        return record

    def fail(self, run_id: str, error_code: str, delivery_status: str = "error") -> RunRecord:
        record = self._items[run_id]
        record.status = "failed"
        record.error_code = error_code
        record.delivery_status = delivery_status
        record.finished_at = datetime.now(timezone.utc)
        return record

    def get(self, run_id: str) -> RunRecord:
        return self._items[run_id]

    def list_runs(self) -> list[RunRecord]:
        return list(self._items.values())
