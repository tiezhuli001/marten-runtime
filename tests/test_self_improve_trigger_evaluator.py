import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Thread

from marten_runtime.runtime.llm_client import ToolExchange
from marten_runtime.self_improve.models import FailureEvent
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.self_improve.trigger_evaluator import SelfImproveTriggerEvaluator


class SelfImproveTriggerEvaluatorTests(unittest.TestCase):
    def test_failure_burst_enqueues_once_after_threshold(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            evaluator = SelfImproveTriggerEvaluator(store)
            for index in range(2):
                store.record_failure(
                    FailureEvent(
                        failure_id=f"failure_{index}",
                        agent_id="main",
                        run_id=f"run_{index}",
                        trace_id=f"trace_{index}",
                        session_id=f"session_{index}",
                        error_code="PROVIDER_TIMEOUT",
                        error_stage="llm",
                        summary="provider timed out",
                        fingerprint="main|timeout",
                    )
                )

            first = evaluator.evaluate_failure_burst(
                agent_id="main",
                run_id="run_2",
                trace_id="trace_2",
                fingerprint="main|timeout",
                summary="provider timed out again",
            )
            second = evaluator.evaluate_failure_burst(
                agent_id="main",
                run_id="run_3",
                trace_id="trace_3",
                fingerprint="main|timeout",
                summary="provider timed out again",
            )
            pending = store.list_review_triggers(
                agent_id="main", limit=10, status="pending"
            )

        self.assertIsNotNone(first)
        self.assertEqual(first.trigger_kind if first else None, "lesson_failure_burst")
        self.assertIsNone(second)
        self.assertEqual(len(pending), 1)

    def test_recovery_threshold_enqueues_trigger_with_relevant_evidence(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            evaluator = SelfImproveTriggerEvaluator(store)
            for index in range(3):
                store.record_failure(
                    FailureEvent(
                        failure_id=f"failure_{index}",
                        agent_id="main",
                        run_id=f"run_{index}",
                        trace_id=f"trace_{index}",
                        session_id=f"session_{index}",
                        error_code="PROVIDER_TIMEOUT",
                        error_stage="llm",
                        summary="provider timed out",
                        fingerprint="main|timeout",
                    )
                )

            trigger = evaluator.evaluate_recovery_threshold(
                agent_id="main",
                run_id="run_recovery",
                trace_id="trace_recovery",
                fingerprint="main|timeout",
                fix_summary="narrowed path and retried",
                success_evidence="final reply generated",
            )

        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.trigger_kind if trigger else None, "lesson_recovery_threshold")
        self.assertEqual(trigger.payload_json["failure_count"] if trigger else None, 3)

    def test_complex_successful_tool_episode_requires_multiple_non_internal_tools(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            evaluator = SelfImproveTriggerEvaluator(store)

            skipped = evaluator.evaluate_complex_successful_tool_episode(
                agent_id="main",
                run_id="run_single",
                trace_id="trace_single",
                user_message="查一下最近的问题",
                tool_history=[
                    ToolExchange(
                        tool_name="runtime",
                        tool_payload={"action": "context_status"},
                        tool_result={"ok": True},
                    ),
                    ToolExchange(
                        tool_name="skill",
                        tool_payload={"skill_id": "github_trending"},
                        tool_result={"ok": True},
                    ),
                ],
                final_text="done",
                summary="single meaningful tool call",
            )
            created = evaluator.evaluate_complex_successful_tool_episode(
                agent_id="main",
                run_id="run_multi",
                trace_id="trace_multi",
                user_message="查一下最近的问题",
                tool_history=[
                    ToolExchange(
                        tool_name="skill",
                        tool_payload={"skill_id": "github_trending"},
                        tool_result={"ok": True},
                    ),
                    ToolExchange(
                        tool_name="mcp",
                        tool_payload={"server_id": "github", "tool_name": "recent"},
                        tool_result={"ok": True},
                    ),
                ],
                final_text="done",
                summary="used skill then mcp and succeeded",
            )

        self.assertIsNone(skipped)
        self.assertIsNotNone(created)
        self.assertEqual(
            created.trigger_kind if created else None, "complex_successful_tool_episode"
        )

    def test_complex_successful_tool_episode_payload_keeps_full_tool_chain_facts(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            evaluator = SelfImproveTriggerEvaluator(store)

            created = evaluator.evaluate_complex_successful_tool_episode(
                agent_id="main",
                run_id="run_multi",
                trace_id="trace_multi",
                user_message="按顺序调用 time runtime mcp",
                tool_history=[
                    ToolExchange(
                        tool_name="time",
                        tool_payload={"timezone": "Asia/Shanghai"},
                        tool_result={"iso_time": "2026-04-17T14:30:10+08:00"},
                    ),
                    ToolExchange(
                        tool_name="runtime",
                        tool_payload={"action": "context_status"},
                        tool_result={"ok": True},
                    ),
                    ToolExchange(
                        tool_name="mcp",
                        tool_payload={"action": "list"},
                        tool_result={"ok": True},
                    ),
                ],
                final_text="done",
                summary="used time then runtime then mcp and succeeded",
            )

        self.assertIsNotNone(created)
        self.assertEqual(
            created.payload_json["tool_names"] if created else None,
            ["time", "runtime", "mcp"],
        )
        self.assertEqual(created.payload_json["tool_call_count"] if created else None, 3)

    def test_pre_compaction_learning_flush_enqueues_once_per_message_fingerprint(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            evaluator = SelfImproveTriggerEvaluator(store)

            first = evaluator.evaluate_pre_compaction_learning_flush(
                agent_id="main",
                run_id="run_compact_1",
                trace_id="trace_compact_1",
                fingerprint="main|long followup",
                estimated_tokens_before=180000,
                estimated_tokens_after=60000,
                channel_id="http",
            )
            second = evaluator.evaluate_pre_compaction_learning_flush(
                agent_id="main",
                run_id="run_compact_2",
                trace_id="trace_compact_2",
                fingerprint="main|long followup",
                estimated_tokens_before=185000,
                estimated_tokens_after=62000,
                channel_id="http",
            )
            pending = store.list_review_triggers(agent_id="main", limit=10, status="pending")

        self.assertIsNotNone(first)
        self.assertEqual(
            first.trigger_kind if first else None, "pre_compaction_learning_flush"
        )
        self.assertEqual(first.payload_json["estimated_tokens_before"] if first else None, 180000)
        self.assertIsNone(second)
        self.assertEqual(len(pending), 1)

    def test_failure_burst_dedupe_is_atomic_under_concurrency(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            evaluator = SelfImproveTriggerEvaluator(store)
            for index in range(2):
                store.record_failure(
                    FailureEvent(
                        failure_id=f"failure_{index}",
                        agent_id="main",
                        run_id=f"run_{index}",
                        trace_id=f"trace_{index}",
                        session_id=f"session_{index}",
                        error_code="PROVIDER_TIMEOUT",
                        error_stage="llm",
                        summary="provider timed out",
                        fingerprint="main|timeout",
                    )
                )
            barrier = Barrier(4)
            results: list[object] = []

            def worker(worker_index: int) -> None:
                barrier.wait(timeout=1.0)
                results.append(
                    evaluator.evaluate_failure_burst(
                        agent_id="main",
                        run_id=f"run_worker_{worker_index}",
                        trace_id=f"trace_worker_{worker_index}",
                        fingerprint="main|timeout",
                        summary="provider timed out again",
                    )
                )

            threads = [Thread(target=worker, args=(index,)) for index in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=1.0)
            pending = store.list_review_triggers(
                agent_id="main", limit=10, status="pending"
            )

        self.assertEqual(len([item for item in results if item is not None]), 1)
        self.assertEqual(len(pending), 1)


if __name__ == "__main__":
    unittest.main()
