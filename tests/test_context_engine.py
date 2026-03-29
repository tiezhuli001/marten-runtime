import unittest
from unittest.mock import patch

from marten_runtime.session.compaction import compact_context
from marten_runtime.session.manifest import build_context_manifest
from marten_runtime.session.rehydration import build_child_handoff, rehydrate_context


class ContextEngineTests(unittest.TestCase):
    def test_compaction_manifest_and_rehydration_preserve_working_context(self) -> None:
        snapshot = compact_context(
            session_id="sess_1",
            active_goal="finish phase 3",
            token_budget=2048,
            compaction_level="auto",
            recent_files=["README.md"],
            open_todos=["wire queue"],
            recent_decisions=["use child handoff"],
            pending_risks=["provider missing"],
            source_message_range=[10, 42],
            skill_snapshot_id="skill_1",
            tool_snapshot_id="tool_1",
        )
        manifest = build_context_manifest(
            run_id="run_1",
            config_snapshot_id="cfg_1",
            bootstrap_manifest_id="boot_1",
            prompt_mode="child",
            bootstrap_sources=["apps/example_assistant/AGENTS.md"],
            working_context={
                "active_goal": "finish phase 3",
                "recent_files": ["README.md"],
                "open_todos": ["wire queue"],
            },
            recalled_memory_ids=["mem_1"],
            skill_snapshot_id="skill_1",
            tool_snapshot_id="tool_1",
            token_estimate_by_layer={"working_context": 120},
            truncated_sources=["tool_output:1"],
        )
        handoff = build_child_handoff(
            snapshot,
            task_scope="review patch",
            relevant_constraints=["keep runtime boundary"],
        )
        rehydrated = rehydrate_context(snapshot)

        self.assertEqual(snapshot.active_goal, "finish phase 3")
        self.assertEqual(snapshot.compaction_level, "auto")
        self.assertEqual(snapshot.skill_snapshot_id, "skill_1")
        self.assertEqual(snapshot.tool_snapshot_id, "tool_1")
        self.assertEqual(snapshot.continuation_hint, "finish phase 3")
        self.assertEqual(snapshot.source_message_range, [10, 42])
        self.assertEqual(manifest.config_snapshot_id, "cfg_1")
        self.assertEqual(manifest.bootstrap_manifest_id, "boot_1")
        self.assertEqual(manifest.prompt_mode, "child")
        self.assertEqual(manifest.recalled_memory_ids, ["mem_1"])
        self.assertEqual(manifest.truncated_sources, ["tool_output:1"])
        self.assertEqual(snapshot.manifest_id, rehydrated["manifest_id"])
        self.assertEqual(rehydrated["recent_files"], ["README.md"])
        self.assertEqual(rehydrated["open_todos"], ["wire queue"])
        self.assertEqual(rehydrated["continuation_hint"], "finish phase 3")
        self.assertEqual(handoff.parent_session_id, "sess_1")
        self.assertEqual(handoff.prompt_mode, "child")
        self.assertEqual(handoff.recent_files, ["README.md"])

    def test_auto_compaction_flushes_memory_before_snapshot(self) -> None:
        with patch("marten_runtime.session.compaction.memory_flush", return_value="semantic export") as flush:
            snapshot = compact_context(
                session_id="sess_2",
                active_goal="stabilize context",
                token_budget=1024,
                compaction_level="auto",
            )

        flush.assert_called_once()
        self.assertEqual(snapshot.compaction_level, "auto")


if __name__ == "__main__":
    unittest.main()
