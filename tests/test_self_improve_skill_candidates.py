import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.self_improve.models import ReviewTrigger, SkillCandidate
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


class SelfImproveSkillCandidateStoreTests(unittest.TestCase):
    def test_review_trigger_store_supports_lifecycle_and_dedupe_queries(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="lesson_recovery_threshold",
                source_run_id="run_123",
                source_trace_id="trace_123",
                source_fingerprints=["main|timeout"],
                status="pending",
                payload_json={"reason": "repeated failure with recovery"},
                semantic_fingerprint="main|lesson_recovery_threshold|timeout",
            )
            store.save_review_trigger(trigger)

            fetched = store.get_review_trigger("trigger_1")
            pending = store.list_review_triggers(
                agent_id="main", limit=10, status="pending"
            )
            latest = store.latest_review_trigger_by_semantic_fingerprint(
                agent_id="main",
                semantic_fingerprint="main|lesson_recovery_threshold|timeout",
                status="pending",
            )
            running = store.update_review_trigger_status("trigger_1", status="running")
            processed = store.update_review_trigger_status("trigger_1", status="processed")
            processed_items = store.list_review_triggers(
                agent_id="main", limit=10, status="processed"
            )

        self.assertEqual(fetched.trigger_id, "trigger_1")
        self.assertEqual(fetched.payload_json["reason"], "repeated failure with recovery")
        self.assertEqual(len(pending), 1)
        self.assertEqual(latest.trigger_id if latest else None, "trigger_1")
        self.assertEqual(running.status, "running")
        self.assertEqual(processed.status, "processed")
        self.assertEqual([item.trigger_id for item in processed_items], ["trigger_1"])

    def test_skill_candidate_store_supports_status_queries_and_promotion_metadata(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            candidate = SkillCandidate(
                candidate_id="skillcand_1",
                agent_id="main",
                status="pending",
                title="Provider Timeout Recovery",
                slug="provider-timeout-recovery",
                summary="Summarize provider timeout recovery workflow.",
                trigger_conditions=["repeated provider timeout", "later recovery"],
                body_markdown="# Provider Timeout Recovery\n\n- Keep the path narrow.",
                rationale="Observed repeated timeout followed by successful narrowed retry",
                source_run_ids=["run_1", "run_2"],
                source_fingerprints=["main|timeout", "main|timeout"],
                confidence=0.91,
                semantic_fingerprint="main|provider-timeout-recovery",
            )
            store.save_skill_candidate(candidate)

            fetched = store.get_skill_candidate("skillcand_1")
            pending = store.list_skill_candidates(
                agent_id="main", limit=10, status="pending"
            )
            latest = store.latest_skill_candidate_by_semantic_fingerprint(
                agent_id="main",
                semantic_fingerprint="main|provider-timeout-recovery",
                status="pending",
            )
            accepted = store.update_skill_candidate_status(
                "skillcand_1", status="accepted"
            )
            promoted = store.mark_skill_candidate_promoted(
                "skillcand_1",
                promoted_skill_id="provider-timeout-recovery",
            )
            promoted_items = store.list_skill_candidates(
                agent_id="main", limit=10, status="promoted"
            )

        self.assertEqual(fetched.slug, "provider-timeout-recovery")
        self.assertEqual(fetched.trigger_conditions, ["repeated provider timeout", "later recovery"])
        self.assertEqual(len(pending), 1)
        self.assertEqual(latest.candidate_id if latest else None, "skillcand_1")
        self.assertEqual(accepted.status, "accepted")
        self.assertEqual(promoted.status, "promoted")
        self.assertEqual(promoted.promoted_skill_id, "provider-timeout-recovery")
        self.assertEqual(
            [item.candidate_id for item in promoted_items], ["skillcand_1"]
        )


if __name__ == "__main__":
    unittest.main()
