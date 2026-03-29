import unittest

from marten_runtime.execution.models import JobRecord
from marten_runtime.execution.recovery import recover_expired_leases


class QueueRecoveryTests(unittest.TestCase):
    def test_queue_recovery_preserves_job_id_and_requeues(self) -> None:
        job = JobRecord(
            job_id="job_recover_1",
            job_type="automation",
            session_id="sess_1",
            app_id="example_assistant",
            agent_id="assistant",
            dedupe_key="job_recover_1",
            state="running",
            lease_expires_at=1,
        )

        recovered = recover_expired_leases([job], now_ts=2)

        self.assertEqual(recovered, ["job_recover_1"])
        self.assertEqual(job.state, "queued")


if __name__ == "__main__":
    unittest.main()
