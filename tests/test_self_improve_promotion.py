import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.self_improve.models import SkillCandidate
from marten_runtime.self_improve.promotion import promote_skill_candidate
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.skills.service import SkillService


class SelfImprovePromotionTests(unittest.TestCase):
    def test_promote_skill_candidate_requires_accepted_status(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            store = SQLiteSelfImproveStore(repo_root / "self_improve.sqlite3")
            store.save_skill_candidate(
                SkillCandidate(
                    candidate_id="skillcand_1",
                    agent_id="main",
                    status="pending",
                    title="Provider Timeout Recovery",
                    slug="provider-timeout-recovery",
                    summary="Narrow the path after repeated timeout.",
                    trigger_conditions=["repeated timeout"],
                    body_markdown="# Provider Timeout Recovery",
                    rationale="Observed repeated timeout followed by recovery",
                    source_run_ids=["run_1"],
                    source_fingerprints=["main|timeout"],
                    confidence=0.92,
                    semantic_fingerprint="main|provider-timeout-recovery",
                )
            )

            with self.assertRaisesRegex(
                ValueError, "skill candidate must be accepted before promotion"
            ):
                promote_skill_candidate(
                    store=store,
                    candidate_id="skillcand_1",
                    repo_root=repo_root,
                )

    def test_promote_skill_candidate_writes_skill_and_marks_promoted(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            store = SQLiteSelfImproveStore(repo_root / "self_improve.sqlite3")
            store.save_skill_candidate(
                SkillCandidate(
                    candidate_id="skillcand_1",
                    agent_id="main",
                    status="accepted",
                    title="Provider Timeout Recovery",
                    slug="provider-timeout-recovery",
                    summary="Narrow the path after repeated timeout.",
                    trigger_conditions=["repeated timeout"],
                    body_markdown="# Provider Timeout Recovery\n\n- Keep the path narrow.",
                    rationale="Observed repeated timeout followed by recovery",
                    source_run_ids=["run_1"],
                    source_fingerprints=["main|timeout"],
                    confidence=0.92,
                    semantic_fingerprint="main|provider-timeout-recovery",
                )
            )

            result = promote_skill_candidate(
                store=store,
                candidate_id="skillcand_1",
                repo_root=repo_root,
            )

            updated = store.get_skill_candidate("skillcand_1")
            skill_path = repo_root / "skills" / "provider-timeout-recovery" / "SKILL.md"
            lessons_path = repo_root / "SYSTEM_LESSONS.md"
            agents_path = repo_root / "AGENTS.md"
            loaded_skill = SkillService([str(repo_root / "skills")]).load_skill(
                "provider-timeout-recovery"
            )
            self.assertTrue(result["ok"])
            self.assertEqual(updated.status, "promoted")
            self.assertEqual(updated.promoted_skill_id, "provider-timeout-recovery")
            self.assertTrue(skill_path.exists())
            self.assertIn("Keep the path narrow.", skill_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded_skill.meta.skill_id, "provider-timeout-recovery")
            self.assertEqual(loaded_skill.meta.name, "Provider Timeout Recovery")
            self.assertFalse(lessons_path.exists())
            self.assertFalse(agents_path.exists())

    def test_promote_skill_candidate_preserves_candidate_agent_scope(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            store = SQLiteSelfImproveStore(repo_root / "self_improve.sqlite3")
            store.save_skill_candidate(
                SkillCandidate(
                    candidate_id="skillcand_1",
                    agent_id="coding",
                    status="accepted",
                    title="Provider Timeout Recovery",
                    slug="provider-timeout-recovery",
                    summary="Narrow the path after repeated timeout.",
                    trigger_conditions=["repeated timeout"],
                    body_markdown="# Provider Timeout Recovery\n\n- Keep the path narrow.",
                    rationale="Observed repeated timeout followed by recovery",
                    source_run_ids=["run_1"],
                    source_fingerprints=["coding|timeout"],
                    confidence=0.92,
                    semantic_fingerprint="coding|provider-timeout-recovery",
                )
            )

            promote_skill_candidate(
                store=store,
                candidate_id="skillcand_1",
                repo_root=repo_root,
            )

            skill_path = repo_root / "skills" / "provider-timeout-recovery" / "SKILL.md"
            self.assertIn("agents: [coding]", skill_path.read_text(encoding="utf-8"))

    def test_promote_skill_candidate_rejects_invalid_slug(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            store = SQLiteSelfImproveStore(repo_root / "self_improve.sqlite3")
            store.save_skill_candidate(
                SkillCandidate(
                    candidate_id="skillcand_1",
                    agent_id="main",
                    status="accepted",
                    title="Bad Skill",
                    slug="../escape",
                    summary="bad",
                    trigger_conditions=[],
                    body_markdown="# Bad Skill",
                    rationale="bad",
                    source_run_ids=["run_1"],
                    source_fingerprints=["main|timeout"],
                    confidence=0.2,
                    semantic_fingerprint="main|bad-skill",
                )
            )

            with self.assertRaisesRegex(
                ValueError, "skill candidate slug must be lowercase kebab-case"
            ):
                promote_skill_candidate(
                    store=store,
                    candidate_id="skillcand_1",
                    repo_root=repo_root,
                )

    def test_promote_skill_candidate_rejects_existing_skill_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            store = SQLiteSelfImproveStore(repo_root / "self_improve.sqlite3")
            existing_skill_root = repo_root / "skills" / "provider-timeout-recovery"
            existing_skill_root.mkdir(parents=True)
            (existing_skill_root / "SKILL.md").write_text(
                "---\nskill_id: provider-timeout-recovery\nname: Existing\n---\n",
                encoding="utf-8",
            )
            store.save_skill_candidate(
                SkillCandidate(
                    candidate_id="skillcand_1",
                    agent_id="main",
                    status="accepted",
                    title="Provider Timeout Recovery",
                    slug="provider-timeout-recovery",
                    summary="Narrow the path after repeated timeout.",
                    trigger_conditions=["repeated timeout"],
                    body_markdown="# Provider Timeout Recovery",
                    rationale="Observed repeated timeout followed by recovery",
                    source_run_ids=["run_1"],
                    source_fingerprints=["main|timeout"],
                    confidence=0.92,
                    semantic_fingerprint="main|provider-timeout-recovery",
                )
            )

            with self.assertRaisesRegex(
                ValueError, "skill already exists: provider-timeout-recovery"
            ):
                promote_skill_candidate(
                    store=store,
                    candidate_id="skillcand_1",
                    repo_root=repo_root,
                )


if __name__ == "__main__":
    unittest.main()
