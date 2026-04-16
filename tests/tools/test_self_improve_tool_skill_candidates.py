import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.self_improve.models import SkillCandidate
from marten_runtime.tools.builtins.self_improve_tool import run_self_improve_tool
from tests.support.domain_builders import build_self_improve_adapter


class SelfImproveSkillCandidateToolTests(unittest.TestCase):
    def test_self_improve_tool_manages_skill_candidate_lifecycle(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = build_self_improve_adapter(Path(tmpdir))
            store.save_skill_candidate(
                SkillCandidate(
                    candidate_id="skillcand_1",
                    agent_id="main",
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

            listed = run_self_improve_tool(
                {"action": "list_skill_candidates", "agent_id": "main"},
                adapter,
                store,
            )
            detail = run_self_improve_tool(
                {"action": "skill_candidate_detail", "candidate_id": "skillcand_1"},
                adapter,
                store,
            )
            edited = run_self_improve_tool(
                {
                    "action": "edit_skill_candidate",
                    "candidate_id": "skillcand_1",
                    "title": "Provider Timeout Recovery v2",
                    "slug": "provider-timeout-recovery-v2",
                    "summary": "Edited summary",
                    "trigger_conditions": ["repeated timeout", "narrow retry"],
                    "body_markdown": "# Provider Timeout Recovery v2",
                    "rationale": "Edited rationale",
                },
                adapter,
                store,
            )
            accepted = run_self_improve_tool(
                {"action": "accept_skill_candidate", "candidate_id": "skillcand_1"},
                adapter,
                store,
            )
        self.assertEqual(listed["count"], 1)
        self.assertEqual(detail["candidate"]["slug"], "provider-timeout-recovery")
        self.assertEqual(edited["candidate"]["slug"], "provider-timeout-recovery-v2")
        self.assertEqual(edited["candidate"]["title"], "Provider Timeout Recovery v2")
        self.assertEqual(accepted["candidate"]["status"], "accepted")

    def test_self_improve_tool_rejects_status_transition_for_non_pending_candidate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = build_self_improve_adapter(Path(tmpdir))
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
                ValueError, "skill candidate must be in status \\[pending\\] before reject"
            ):
                run_self_improve_tool(
                    {"action": "reject_skill_candidate", "candidate_id": "skillcand_1"},
                    adapter,
                    store,
                )

    def test_self_improve_tool_rejects_edit_for_non_pending_candidate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = build_self_improve_adapter(Path(tmpdir))
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
                ValueError, "only pending skill candidates may be edited"
            ):
                run_self_improve_tool(
                    {
                        "action": "edit_skill_candidate",
                        "candidate_id": "skillcand_1",
                        "title": "Edited",
                    },
                    adapter,
                    store,
                )

    def test_self_improve_tool_promotes_accepted_skill_candidate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            adapter, store = build_self_improve_adapter(repo_root)
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

            promoted = run_self_improve_tool(
                {"action": "promote_skill_candidate", "candidate_id": "skillcand_1"},
                adapter,
                store,
                repo_root=repo_root,
            )
            skill_path = repo_root / "skills" / "provider-timeout-recovery" / "SKILL.md"
            self.assertTrue(promoted["ok"])
            self.assertEqual(promoted["candidate"]["status"], "promoted")
            self.assertTrue(skill_path.exists())
            self.assertIn("Keep the path narrow.", skill_path.read_text(encoding="utf-8"))

    def test_self_improve_tool_promotes_skill_candidate_with_original_agent_scope(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            adapter, store = build_self_improve_adapter(repo_root)
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

            run_self_improve_tool(
                {"action": "promote_skill_candidate", "candidate_id": "skillcand_1"},
                adapter,
                store,
                repo_root=repo_root,
            )
            skill_path = repo_root / "skills" / "provider-timeout-recovery" / "SKILL.md"
            self.assertIn("agents: [coding]", skill_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
