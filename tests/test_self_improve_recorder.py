import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


class SelfImproveRecorderTests(unittest.TestCase):
    def test_recorder_persists_failure_and_recovery(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            recorder = SelfImproveRecorder(store)

            failure = recorder.record_failure(
                agent_id="main",
                run_id="run_1",
                trace_id="trace_1",
                session_id="session_1",
                error_code="PROVIDER_TIMEOUT",
                error_stage="llm",
                summary="provider timed out",
                provider_name="minimax",
                message="请总结今天的问题",
            )
            recovery = recorder.record_recovery(
                agent_id="main",
                run_id="run_2",
                trace_id="trace_2",
                message="请总结今天的问题",
                fix_summary="narrowed the path and retried",
                success_evidence="final reply generated",
            )

            failures = store.list_recent_failures(agent_id="main", limit=10)
            recoveries = store.list_recent_recoveries(agent_id="main", limit=10)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].fingerprint, failure.fingerprint)
        self.assertIsNotNone(recovery)
        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0].related_failure_fingerprint, failure.fingerprint)


if __name__ == "__main__":
    unittest.main()
