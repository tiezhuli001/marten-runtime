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
                agent_id="assistant",
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
                agent_id="assistant",
                run_id="run_2",
                trace_id="trace_2",
                message="请总结今天的问题",
                fix_summary="narrowed the path and retried",
                success_evidence="final reply generated",
            )

            failures = store.list_recent_failures(agent_id="assistant", limit=10)
            recoveries = store.list_recent_recoveries(agent_id="assistant", limit=10)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].fingerprint, failure.fingerprint)
        self.assertIsNotNone(recovery)
        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0].related_failure_fingerprint, failure.fingerprint)

    def test_recorder_creates_one_threshold_trigger_on_third_matching_failure(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            recorder = SelfImproveRecorder(store)

            for run_id in ("run_1", "run_2", "run_3", "run_4"):
                recorder.record_failure(
                    agent_id="assistant",
                    run_id=run_id,
                    trace_id=f"trace_{run_id}",
                    session_id=f"session_{run_id}",
                    error_code="PROVIDER_TIMEOUT",
                    error_stage="llm",
                    summary="provider timed out",
                    provider_name="minimax",
                    message="请总结今天的问题",
                )

            triggers = store.list_pending_triggers(agent_id="assistant", limit=10)

        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["fingerprint"], "assistant|请总结今天的问题".lower())


if __name__ == "__main__":
    unittest.main()
