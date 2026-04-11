import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.self_improve.models import (
    FailureEvent,
    LessonCandidate,
    SystemLesson,
)
from marten_runtime.tools.builtins.self_improve_tool import (
    run_delete_lesson_candidate_tool,
    run_get_lesson_candidate_detail_tool,
    run_get_self_improve_summary_tool,
    run_list_lesson_candidates_tool,
    run_list_self_improve_evidence_tool,
    run_list_system_lessons_tool,
    run_save_lesson_candidate_tool,
    run_self_improve_tool,
)
from tests.support.domain_builders import build_self_improve_adapter


class SelfImproveToolTests(unittest.TestCase):

    def test_self_improve_tools_list_evidence_and_lessons_and_save_candidates(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = build_self_improve_adapter(Path(tmpdir))
            store.record_failure(
                FailureEvent(
                    failure_id="failure_1",
                    agent_id="assistant",
                    run_id="run_1",
                    trace_id="trace_1",
                    session_id="session_1",
                    error_code="PROVIDER_TIMEOUT",
                    error_stage="llm",
                    summary="provider timed out",
                    fingerprint="assistant|hello",
                )
            )
            store.save_lesson(
                SystemLesson(
                    lesson_id="lesson_1",
                    agent_id="assistant",
                    topic_key="provider_timeout",
                    lesson_text="先减少无关工具面。",
                    source_fingerprints=["assistant|hello"],
                    active=True,
                )
            )
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_keep",
                    agent_id="assistant",
                    source_fingerprints=["assistant|hello", "assistant|hello"],
                    candidate_text="pending candidate",
                    rationale="same failure repeated",
                    status="pending",
                    score=0.8,
                )
            )

            evidence = run_list_self_improve_evidence_tool(
                {"agent_id": "assistant"}, store
            )
            candidate = run_save_lesson_candidate_tool(
                {
                    "candidate_id": "cand_1",
                    "agent_id": "assistant",
                    "source_fingerprints": ["assistant|hello"],
                    "candidate_text": "遇到重复 provider timeout 时先减少无关工具面。",
                    "rationale": "same failure repeated",
                    "score": 0.9,
                },
                store,
            )
            candidates = run_list_lesson_candidates_tool(
                {"agent_id": "assistant", "status": "pending"}, adapter
            )
            detail = run_get_lesson_candidate_detail_tool(
                {"candidate_id": "cand_1"}, adapter
            )
            summary = run_get_self_improve_summary_tool(
                {"agent_id": "assistant"}, store
            )
            deleted = run_delete_lesson_candidate_tool(
                {"candidate_id": "cand_keep"}, adapter
            )
            missing_delete = run_delete_lesson_candidate_tool(
                {"candidate_id": "cand_missing"}, adapter
            )
            lessons = run_list_system_lessons_tool({"agent_id": "assistant"}, store)

        self.assertTrue(evidence["ok"])
        self.assertEqual(evidence["failure_count"], 1)
        self.assertTrue(candidate["ok"])
        self.assertEqual(candidate["candidate"]["status"], "pending")
        self.assertTrue(candidates["ok"])
        self.assertEqual(candidates["count"], 2)
        self.assertEqual(detail["candidate"]["candidate_id"], "cand_1")
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["candidate_counts"]["pending"], 2)
        self.assertEqual(summary["active_lessons_count"], 1)
        self.assertTrue(deleted["ok"])
        self.assertFalse(missing_delete["ok"])
        self.assertEqual(missing_delete["error"], "LESSON_CANDIDATE_NOT_FOUND")
        self.assertTrue(lessons["ok"])
        self.assertEqual(lessons["count"], 1)

    def test_self_improve_family_tool_dispatches_summary_and_delete(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = build_self_improve_adapter(Path(tmpdir))
            store.save_lesson(
                SystemLesson(
                    lesson_id="lesson_1",
                    agent_id="assistant",
                    topic_key="provider_timeout",
                    lesson_text="先减少无关工具面。",
                    source_fingerprints=["assistant|hello"],
                    active=True,
                )
            )
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_keep",
                    agent_id="assistant",
                    source_fingerprints=["assistant|hello", "assistant|hello"],
                    candidate_text="pending candidate",
                    rationale="same failure repeated",
                    status="pending",
                    score=0.8,
                )
            )

            summary = run_self_improve_tool(
                {"action": "summary", "agent_id": "assistant"}, adapter, store
            )
            deleted = run_self_improve_tool(
                {"action": "delete_candidate", "candidate_id": "cand_keep"},
                adapter,
                store,
            )

        self.assertEqual(summary["action"], "summary")
        self.assertTrue(summary["ok"])
        self.assertEqual(deleted["action"], "delete_candidate")
        self.assertTrue(deleted["ok"])


if __name__ == "__main__":
    unittest.main()
