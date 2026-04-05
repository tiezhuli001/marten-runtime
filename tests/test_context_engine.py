import unittest

from marten_runtime.session.compaction import compact_context
from marten_runtime.session.rehydration import rehydrate_context


class ContextEngineTests(unittest.TestCase):
    def test_compaction_manifest_and_rehydration_preserve_working_context(self) -> None:
        snapshot = compact_context(
            session_id="sess_1",
            active_goal="finish phase 3",
            recent_files=["README.md"],
            open_todos=["wire queue"],
            recent_decisions=["use small harness"],
            pending_risks=["provider missing"],
            source_message_range=[10, 42],
        )
        rehydrated = rehydrate_context(snapshot)

        self.assertEqual(snapshot.active_goal, "finish phase 3")
        self.assertEqual(snapshot.source_message_range, [10, 42])
        self.assertEqual(rehydrated["recent_files"], ["README.md"])
        self.assertEqual(rehydrated["open_todos"], ["wire queue"])
        self.assertEqual(rehydrated["recent_decisions"], ["use small harness"])
        self.assertEqual(rehydrated["pending_risks"], ["provider missing"])
        self.assertEqual(rehydrated["continuation_hint"], "finish phase 3")
        self.assertEqual(snapshot.snapshot_id, "ctx_sess_1")


if __name__ == "__main__":
    unittest.main()
