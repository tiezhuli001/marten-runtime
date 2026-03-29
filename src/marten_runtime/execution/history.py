from datetime import datetime, timezone

from pydantic import BaseModel, Field


class RunRecord(BaseModel):
    run_id: str
    trace_id: str = "trace_runtime"
    session_id: str
    job_id: str | None = None
    config_snapshot_id: str | None = None
    bootstrap_manifest_id: str | None = None
    status: str = "pending"
    delivery_status: str = "none"
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None


class RunHistory:
    def __init__(self) -> None:
        self._items: list[RunRecord] = []

    def add(self, record: RunRecord) -> None:
        self._items.append(record)

    def list_runs(self) -> list[RunRecord]:
        return self._items
