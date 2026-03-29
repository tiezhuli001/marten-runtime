import unittest

from marten_runtime.execution.history import RunHistory
from marten_runtime.execution.models import JobRecord
from marten_runtime.execution.queue import InMemoryExecutionQueue
from marten_runtime.execution.recovery import recover_expired_leases
from marten_runtime.execution.worker import ExecutionWorker


class ExecutionQueueTests(unittest.TestCase):
    def test_queue_claim_lease_heartbeat_and_success_history(self) -> None:
        queue = InMemoryExecutionQueue()
        history = RunHistory()
        worker = ExecutionWorker(queue, history)
        queue.push(
            JobRecord(
                job_id="job_1",
                job_type="automation",
                session_id="sess_1",
                app_id="example_assistant",
                agent_id="assistant",
                dedupe_key="job_1",
            )
        )

        run = worker.process_next(worker_id="worker_1")
        queued = queue.peek_all()[0]

        self.assertEqual(run.job_id, "job_1")
        self.assertEqual(queued.state, "succeeded")
        self.assertEqual(queued.resolved_config_snapshot_id, "cfg_bootstrap")
        self.assertEqual(history.list_runs()[0].job_id, "job_1")

    def test_recovery_requeues_expired_running_jobs(self) -> None:
        queue = InMemoryExecutionQueue()
        job = JobRecord(
            job_id="job_2",
            job_type="automation",
            session_id="sess_1",
            app_id="example_assistant",
            agent_id="assistant",
            dedupe_key="job_2",
            state="running",
            lease_expires_at=10,
        )
        queue.push(job)

        recovered = recover_expired_leases(queue.peek_all(), now_ts=20)

        self.assertEqual(recovered, ["job_2"])
        self.assertEqual(queue.peek_all()[0].state, "queued")
        self.assertEqual(queue.peek_all()[0].attempt, 1)


if __name__ == "__main__":
    unittest.main()
