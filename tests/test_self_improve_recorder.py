import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.runtime.llm_client import ToolExchange
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

    def test_recorder_enqueues_failure_and_recovery_review_triggers(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            recorder = SelfImproveRecorder(store)

            recorder.record_failure(
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
            recorder.record_failure(
                agent_id="main",
                run_id="run_2",
                trace_id="trace_2",
                session_id="session_1",
                error_code="PROVIDER_TIMEOUT",
                error_stage="llm",
                summary="provider timed out again",
                provider_name="minimax",
                message="请总结今天的问题",
            )
            recorder.record_recovery(
                agent_id="main",
                run_id="run_3",
                trace_id="trace_3",
                message="请总结今天的问题",
                fix_summary="narrowed the path and retried",
                success_evidence="final reply generated",
            )

            triggers = store.list_review_triggers(agent_id="main", limit=10)

        kinds = [item.trigger_kind for item in triggers]
        self.assertIn("lesson_failure_burst", kinds)
        self.assertIn("lesson_recovery_threshold", kinds)

    def test_recorder_enqueues_complex_successful_tool_episode_trigger(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            recorder = SelfImproveRecorder(store)

            trigger = recorder.record_successful_tool_episode(
                agent_id="main",
                run_id="run_success",
                trace_id="trace_success",
                message="查一下最近的 github 情况",
                tool_history=[
                    ToolExchange(tool_name="skill", tool_payload={"skill_id": "github"}, tool_result={"ok": True}),
                    ToolExchange(tool_name="mcp", tool_payload={"server_id": "github"}, tool_result={"ok": True}),
                ],
                final_text="done",
                summary="used skill then mcp and succeeded",
            )

        self.assertIsNotNone(trigger)
        self.assertEqual(
            trigger.trigger_kind if trigger else None, "complex_successful_tool_episode"
        )

    def test_recorder_enqueues_pre_compaction_learning_flush_trigger(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            recorder = SelfImproveRecorder(store)

            trigger = recorder.record_pre_compaction_learning_flush(
                agent_id="main",
                run_id="run_compact",
                trace_id="trace_compact",
                message="请继续总结复杂问题，并给我后续建议",
                estimated_tokens_before=180000,
                estimated_tokens_after=65000,
                channel_id="feishu",
            )

        self.assertIsNotNone(trigger)
        self.assertEqual(
            trigger.trigger_kind if trigger else None, "pre_compaction_learning_flush"
        )
        self.assertEqual(trigger.payload_json["source_channel_id"] if trigger else None, "feishu")


if __name__ == "__main__":
    unittest.main()
