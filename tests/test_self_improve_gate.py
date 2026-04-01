import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.self_improve.models import LessonCandidate
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.self_improve.service import JudgeVerdict, SelfImproveService, make_default_judge
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


class SelfImproveGateTests(unittest.TestCase):
    def test_low_value_candidate_is_rejected(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "self_improve.sqlite3"
            lessons_path = Path(tmpdir) / "SYSTEM_LESSONS.md"
            store = SQLiteSelfImproveStore(db_path)
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_1",
                    agent_id="assistant",
                    source_fingerprints=["fp_oneoff"],
                    candidate_text="昨天某个接口挂了，注意一下。",
                    rationale="one-off incident",
                    score=0.2,
                )
            )
            service = SelfImproveService(
                store,
                lessons_path=lessons_path,
                judge=lambda *_args, **_kwargs: JudgeVerdict(
                    accept=False,
                    reason="not stable",
                    normalized_lesson_text="",
                    topic_key="",
                ),
            )

            accepted = service.process_pending_candidates(agent_id="assistant")
            candidate = store.get_candidate("cand_1")

        self.assertEqual(accepted, [])
        self.assertEqual(candidate.status, "rejected")
        self.assertFalse(lessons_path.exists())

    def test_duplicate_candidate_is_rejected_when_topic_already_active(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "self_improve.sqlite3"
            lessons_path = Path(tmpdir) / "SYSTEM_LESSONS.md"
            store = SQLiteSelfImproveStore(db_path)
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_1",
                    agent_id="assistant",
                    source_fingerprints=["fp_timeout", "fp_timeout"],
                    candidate_text="先减少无关工具面。",
                    rationale="repeated timeout",
                    score=0.9,
                )
            )
            service = SelfImproveService(
                store,
                lessons_path=lessons_path,
                judge=lambda *_args, **_kwargs: JudgeVerdict(
                    accept=True,
                    reason="stable",
                    normalized_lesson_text="先减少无关工具面。",
                    topic_key="provider_timeout",
                ),
            )
            service.process_pending_candidates(agent_id="assistant")
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_2",
                    agent_id="assistant",
                    source_fingerprints=["fp_timeout", "fp_timeout"],
                    candidate_text="先减少无关工具面。",
                    rationale="repeated timeout again",
                    score=0.95,
                )
            )

            accepted = service.process_pending_candidates(agent_id="assistant")
            candidate = store.get_candidate("cand_2")

        self.assertEqual(accepted, [])
        self.assertEqual(candidate.status, "rejected")

    def test_high_value_candidate_is_accepted_and_exported_as_active_lessons_only(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "self_improve.sqlite3"
            lessons_path = Path(tmpdir) / "SYSTEM_LESSONS.md"
            store = SQLiteSelfImproveStore(db_path)
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_1",
                    agent_id="assistant",
                    source_fingerprints=["fp_timeout", "fp_timeout", "fp_timeout"],
                    candidate_text="遇到重复 provider timeout 时先减少无关工具面。",
                    rationale="repeated failure with later recovery",
                    score=0.95,
                )
            )
            service = SelfImproveService(
                store,
                lessons_path=lessons_path,
                judge=lambda *_args, **_kwargs: JudgeVerdict(
                    accept=True,
                    reason="stable and useful",
                    normalized_lesson_text="遇到重复 provider timeout 时先减少无关工具面。",
                    topic_key="provider_timeout",
                ),
            )

            accepted = service.process_pending_candidates(agent_id="assistant")
            lessons = store.list_active_lessons(agent_id="assistant")
            exported = lessons_path.read_text(encoding="utf-8")

        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(lessons), 1)
        self.assertIn("遇到重复 provider timeout 时先减少无关工具面。", exported)
        self.assertIn("active lessons only", exported)

    def test_llm_judge_accepts_high_value_candidate_with_structured_reply(self) -> None:
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    final_text=(
                        '{"accept": true, "reason": "stable lesson", '
                        '"normalized_lesson_text": "遇到重复 provider timeout 时先减少无关工具面。", '
                        '"topic_key": "provider_timeout"}'
                    )
                )
            ]
        )
        judge = make_default_judge(llm, app_id="example_assistant", agent_id="assistant")
        verdict = judge(
            LessonCandidate(
                candidate_id="cand_1",
                agent_id="assistant",
                source_fingerprints=["fp_timeout", "fp_timeout", "fp_timeout"],
                candidate_text="遇到重复 provider timeout 时先减少无关工具面。",
                rationale="repeated failure with later recovery",
                score=0.95,
            ),
            active_lessons=[],
        )

        self.assertTrue(verdict.accept)
        self.assertEqual(verdict.topic_key, "provider_timeout")
        self.assertEqual(len(llm.requests), 1)
        self.assertEqual(llm.requests[0].available_tools, [])

    def test_llm_judge_rejects_invalid_payload_safely(self) -> None:
        llm = ScriptedLLMClient([LLMReply(final_text="not json")])
        judge = make_default_judge(llm, app_id="example_assistant", agent_id="assistant")

        verdict = judge(
            LessonCandidate(
                candidate_id="cand_1",
                agent_id="assistant",
                source_fingerprints=["fp_timeout", "fp_timeout", "fp_timeout"],
                candidate_text="遇到重复 provider timeout 时先减少无关工具面。",
                rationale="repeated failure with later recovery",
                score=0.95,
            ),
            active_lessons=[],
        )

        self.assertFalse(verdict.accept)
        self.assertEqual(verdict.reason, "judge_invalid_payload")


if __name__ == "__main__":
    unittest.main()
