from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class RunTimings(BaseModel):
    llm_first_ms: int = 0
    tool_ms: int = 0
    llm_second_ms: int = 0
    outbound_ms: int = 0
    total_ms: int = 0


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
    llm_request_count: int = 0
    tool_calls: list[dict[str, object]] = Field(default_factory=list)
    timings: RunTimings = Field(default_factory=RunTimings)


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

    def record_tool_call(
        self,
        run_id: str,
        *,
        tool_name: str,
        tool_payload: dict,
        tool_result: dict,
    ) -> None:
        record = self._items[run_id]
        record.tool_calls.append(
            {
                "tool_name": tool_name,
                "tool_payload": tool_payload,
                "tool_result": tool_result,
            }
        )

    def set_llm_request_count(self, run_id: str, count: int) -> None:
        self._items[run_id].llm_request_count = count

    def set_stage_timing(self, run_id: str, *, stage: str, elapsed_ms: int) -> None:
        record = self._items[run_id]
        if stage == "llm_first":
            record.timings.llm_first_ms = elapsed_ms
            return
        if stage == "tool":
            record.timings.tool_ms = elapsed_ms
            return
        if stage == "llm_second":
            record.timings.llm_second_ms = elapsed_ms
            return
        raise KeyError(stage)

    def add_outbound_timing(self, run_id: str, *, elapsed_ms: int) -> None:
        record = self._items[run_id]
        record.timings.outbound_ms += elapsed_ms
        record.timings.total_ms += elapsed_ms

    def finalize_total_timing(self, run_id: str, *, elapsed_ms: int) -> None:
        self._items[run_id].timings.total_ms = elapsed_ms
