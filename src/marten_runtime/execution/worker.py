from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.execution.history import RunHistory, RunRecord
from marten_runtime.execution.queue import InMemoryExecutionQueue


class ExecutionWorker:
    def __init__(self, queue: InMemoryExecutionQueue, history: RunHistory) -> None:
        self.queue = queue
        self.history = history

    def process_next(self, worker_id: str) -> RunRecord:
        job = self.queue.pop()
        job.worker_id = worker_id
        job.lease_expires_at = 60
        job.last_heartbeat_at = 1
        job.resolved_config_snapshot_id = job.resolved_config_snapshot_id or "cfg_bootstrap"
        job.resolved_bootstrap_manifest_id = job.resolved_bootstrap_manifest_id or "boot_default"
        run = RunRecord(
            run_id=f"run_{uuid4().hex[:8]}",
            session_id=job.session_id,
            job_id=job.job_id,
            config_snapshot_id=job.resolved_config_snapshot_id,
            bootstrap_manifest_id=job.resolved_bootstrap_manifest_id,
            status="succeeded",
            delivery_status="none",
            finished_at=datetime.now(timezone.utc),
        )
        job.active_run_id = run.run_id
        job.state = "succeeded"
        job.updated_at = datetime.now(timezone.utc)
        self.history.add(run)
        return run
