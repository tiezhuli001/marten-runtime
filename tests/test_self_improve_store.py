import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.self_improve.models import (
    FailureEvent,
    LessonCandidate,
    RecoveryEvent,
    SystemLesson,
)
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


class SQLiteSelfImproveStoreTests(unittest.TestCase):
    def test_save_and_list_failure_and_recovery_events(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "self_improve.sqlite3"
            store = SQLiteSelfImproveStore(db_path)
            store.record_failure(
                FailureEvent(
                    failure_id="fail_1",
                    agent_id="assistant",
                    run_id="run_1",
                    trace_id="trace_1",
                    session_id="session_1",
                    error_code="PROVIDER_TIMEOUT",
                    error_stage="llm",
                    provider_name="minimax",
                    summary="provider timed out after retry exhaustion",
                    fingerprint="fp_timeout",
                )
            )
            store.record_recovery(
                RecoveryEvent(
                    recovery_id="recovery_1",
                    agent_id="assistant",
                    run_id="run_2",
                    trace_id="trace_2",
                    related_failure_fingerprint="fp_timeout",
                    recovery_kind="same_fingerprint_success",
                    fix_summary="retried after narrowing tool path",
                    success_evidence="final response generated",
                )
            )

            reloaded = SQLiteSelfImproveStore(db_path)
            failures = reloaded.list_recent_failures(agent_id="assistant", limit=10)
            recoveries = reloaded.list_recent_recoveries(agent_id="assistant", limit=10)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].error_code, "PROVIDER_TIMEOUT")
        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0].related_failure_fingerprint, "fp_timeout")

    def test_save_and_update_candidate_status(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "self_improve.sqlite3"
            store = SQLiteSelfImproveStore(db_path)
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_1",
                    agent_id="assistant",
                    source_fingerprints=["fp_timeout", "fp_timeout"],
                    candidate_text="遇到重复 provider timeout 时先减少无关工具面。",
                    rationale="same failure repeated with later successful narrowing",
                    status="pending",
                    score=0.8,
                )
            )
            updated = store.update_candidate_status("cand_1", status="accepted")
            reloaded = SQLiteSelfImproveStore(db_path)
            candidates = reloaded.list_candidates(agent_id="assistant", limit=10)

        self.assertEqual(updated.status, "accepted")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "accepted")

    def test_list_candidates_supports_status_filter_and_delete(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "self_improve.sqlite3"
            store = SQLiteSelfImproveStore(db_path)
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_1",
                    agent_id="assistant",
                    source_fingerprints=["fp_one", "fp_one"],
                    candidate_text="pending lesson",
                    rationale="pending rationale",
                    status="pending",
                    score=0.9,
                )
            )
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_2",
                    agent_id="assistant",
                    source_fingerprints=["fp_two", "fp_two"],
                    candidate_text="accepted lesson",
                    rationale="accepted rationale",
                    status="accepted",
                    score=0.95,
                )
            )

            pending = store.list_candidates(agent_id="assistant", limit=10, status="pending")
            deleted = store.delete_candidate("cand_1")
            remaining = store.list_candidates(agent_id="assistant", limit=10)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].candidate_id, "cand_1")
        self.assertTrue(deleted)
        self.assertEqual([candidate.candidate_id for candidate in remaining], ["cand_2"])

    def test_activate_lesson_supersedes_previous_topic_entry(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "self_improve.sqlite3"
            store = SQLiteSelfImproveStore(db_path)
            store.save_lesson(
                SystemLesson(
                    lesson_id="lesson_1",
                    agent_id="assistant",
                    topic_key="provider_timeout",
                    lesson_text="旧规则",
                    source_fingerprints=["fp_timeout"],
                    active=True,
                )
            )
            store.save_lesson(
                SystemLesson(
                    lesson_id="lesson_2",
                    agent_id="assistant",
                    topic_key="provider_timeout",
                    lesson_text="新规则",
                    source_fingerprints=["fp_timeout", "fp_timeout"],
                    active=True,
                )
            )

            reloaded = SQLiteSelfImproveStore(db_path)
            active_lessons = reloaded.list_active_lessons(agent_id="assistant")
            old_lesson = reloaded.get_lesson("lesson_1")
            new_lesson = reloaded.get_lesson("lesson_2")

        self.assertEqual(len(active_lessons), 1)
        self.assertEqual(active_lessons[0].lesson_id, "lesson_2")
        self.assertFalse(old_lesson.active)
        self.assertIsNotNone(old_lesson.superseded_at)
        self.assertTrue(new_lesson.active)


if __name__ == "__main__":
    unittest.main()
