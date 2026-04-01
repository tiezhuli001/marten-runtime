import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.self_improve.models import LessonCandidate
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


class DomainDataAdapterTests(unittest.TestCase):
    def _build_adapter(self, tmpdir: str) -> DomainDataAdapter:
        return DomainDataAdapter(
            self_improve_store=SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3"),
            automation_store=SQLiteAutomationStore(Path(tmpdir) / "automations.sqlite3"),
        )

    def test_adapter_lists_gets_and_deletes_lesson_candidates(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter = self._build_adapter(tmpdir)
            store = adapter.self_improve_store
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_pending",
                    agent_id="assistant",
                    source_fingerprints=["fp_one", "fp_one"],
                    candidate_text="pending lesson",
                    rationale="pending rationale",
                    status="pending",
                    score=0.8,
                )
            )
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_rejected",
                    agent_id="assistant",
                    source_fingerprints=["fp_two", "fp_two"],
                    candidate_text="rejected lesson",
                    rationale="rejected rationale",
                    status="rejected",
                    score=0.4,
                )
            )

            pending = adapter.list_items(
                "lesson_candidate",
                filters={"agent_id": "assistant", "status": "pending"},
                limit=10,
            )
            item = adapter.get_item("lesson_candidate", item_id="cand_pending")
            deleted = adapter.delete_item("lesson_candidate", item_id="cand_pending")
            remaining = store.list_candidates(agent_id="assistant", limit=10)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["candidate_id"], "cand_pending")
        self.assertEqual(item["candidate_id"], "cand_pending")
        self.assertTrue(deleted["ok"])
        self.assertEqual([candidate.candidate_id for candidate in remaining], ["cand_rejected"])

    def test_adapter_rejects_unknown_or_out_of_scope_entities(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter = self._build_adapter(tmpdir)

            with self.assertRaises(KeyError):
                adapter.list_items("system_lesson", filters={"agent_id": "assistant"}, limit=10)
            with self.assertRaises(KeyError):
                adapter.get_item("unknown_entity", item_id="whatever")

    def test_adapter_supports_automation_crud(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter = self._build_adapter(tmpdir)

            created = adapter.create_item(
                "automation",
                values={
                    "automation_id": "daily_digest",
                    "name": "Daily Digest",
                    "app_id": "assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize hot repos",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:00",
                    "timezone": "Asia/Shanghai",
                    "session_target": "chat-1",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_xxx",
                    "skill_id": "github_hot_repos_digest",
                    "enabled": True,
                    "internal": False,
                },
            )
            listed = adapter.list_items(
                "automation",
                filters={"delivery_channel": "feishu", "enabled": True},
                limit=10,
            )
            fetched = adapter.get_item("automation", item_id="daily_digest")
            updated = adapter.update_item(
                "automation",
                item_id="daily_digest",
                values={
                    "schedule_expr": "10:30",
                    "enabled": False,
                },
            )
            deleted = adapter.delete_item("automation", item_id="daily_digest")

        self.assertEqual(created["automation_id"], "daily_digest")
        self.assertEqual([item["automation_id"] for item in listed], ["daily_digest"])
        self.assertEqual(fetched["name"], "Daily Digest")
        self.assertEqual(updated["schedule_expr"], "10:30")
        self.assertFalse(updated["enabled"])
        self.assertTrue(deleted["ok"])

    def test_adapter_rejects_unsupported_filters_and_mutations(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter = self._build_adapter(tmpdir)
            adapter.self_improve_store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_pending",
                    agent_id="assistant",
                    source_fingerprints=["fp_one", "fp_one"],
                    candidate_text="pending lesson",
                    rationale="pending rationale",
                    status="pending",
                    score=0.8,
                )
            )

            with self.assertRaises(KeyError):
                adapter.list_items("automation", filters={"status": "enabled"}, limit=10)
            with self.assertRaises(KeyError):
                adapter.create_item(
                    "lesson_candidate",
                    values={
                        "candidate_id": "cand_created",
                        "agent_id": "assistant",
                    },
                )
            with self.assertRaises(KeyError):
                adapter.update_item(
                    "lesson_candidate",
                    item_id="cand_pending",
                    values={"status": "accepted"},
                )


if __name__ == "__main__":
    unittest.main()
