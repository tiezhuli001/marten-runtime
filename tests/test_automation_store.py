import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.automation.models import AutomationJob
from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.automation.skill_ids import GITHUB_TRENDING_DIGEST_SKILL_ID


class SQLiteAutomationStoreTests(unittest.TestCase):
    def test_store_init_migrates_legacy_github_digest_rows_to_canonical_ids(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "automation.sqlite3"
            legacy_skill_id = GITHUB_TRENDING_DIGEST_SKILL_ID.replace("trending", "hot_repos")
            legacy_automation_id = f"{legacy_skill_id}_2200"
            store = SQLiteAutomationStore(db_path)
            store.save(
                AutomationJob(
                    automation_id=legacy_automation_id,
                    name="GitHub热榜推荐",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="Summarize today's hot repositories.",
                    schedule_kind="daily",
                    schedule_expr="22:00",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id=legacy_skill_id,
                    enabled=True,
                )
            )
            store.record_dispatched_window(
                automation_id=legacy_automation_id,
                scheduled_for="2026-04-05",
                delivery_target="oc_test_chat",
                dedupe_key=f"{legacy_automation_id}:2026-04-05",
            )

            migrated = SQLiteAutomationStore(db_path)
            items = migrated.list_all()

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].automation_id, "github_trending_digest_2200")
            self.assertEqual(items[0].skill_id, GITHUB_TRENDING_DIGEST_SKILL_ID)
            self.assertTrue(migrated.has_dispatched_window("github_trending_digest_2200", "2026-04-05"))
            with self.assertRaises(KeyError):
                migrated.get(legacy_automation_id)

    def test_save_and_reload_enabled_automation_definition(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "automation.sqlite3"
            store = SQLiteAutomationStore(db_path)
            store.save(
                AutomationJob(
                    automation_id="daily_hot",
                    name="Daily GitHub Hot Repos",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="Summarize today's hot repositories.",
                    schedule_kind="daily",
                    schedule_expr="09:30",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id="github_trending_digest",
                    enabled=True,
                )
            )

            reloaded = SQLiteAutomationStore(db_path)
            enabled = reloaded.list_enabled()

        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].automation_id, "daily_hot")
        self.assertEqual(enabled[0].schedule_expr, "09:30")
        self.assertEqual(enabled[0].delivery_target, "oc_test_chat")

    def test_dispatch_window_is_persisted_and_idempotent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "automation.sqlite3"
            store = SQLiteAutomationStore(db_path)

            first = store.record_dispatched_window(
                automation_id="daily_hot",
                scheduled_for="2026-03-30",
                delivery_target="oc_test_chat",
                dedupe_key="daily_hot:2026-03-30",
            )
            second = store.record_dispatched_window(
                automation_id="daily_hot",
                scheduled_for="2026-03-30",
                delivery_target="oc_test_chat",
                dedupe_key="daily_hot:2026-03-30",
            )
            reloaded = SQLiteAutomationStore(db_path)
            persisted = reloaded.has_dispatched_window("daily_hot", "2026-03-30")

            self.assertTrue(first)
            self.assertFalse(second)
            self.assertTrue(persisted)

    def test_registration_reuses_existing_equivalent_automation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "automation.sqlite3"
            store = SQLiteAutomationStore(db_path)
            first = store.create_from_registration(
                {
                    "automation_id": "daily_hot_a",
                    "name": "Daily Hot A",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize hot repos.",
                    "schedule_kind": "daily",
                    "schedule_expr": "23:31",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                    "enabled": True,
                }
            )

            second = store.create_from_registration(
                {
                    "automation_id": "daily_hot_b",
                    "name": "Daily Hot B",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize hot repos.",
                    "schedule_kind": "daily",
                    "schedule_expr": "23:31",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                    "enabled": True,
                }
            )

            reloaded = SQLiteAutomationStore(db_path)
            enabled = reloaded.list_enabled()

        self.assertEqual(first.automation_id, "daily_hot_a")
        self.assertEqual(second.automation_id, "daily_hot_a")
        self.assertEqual(len(enabled), 1)
        self.assertEqual(first.semantic_fingerprint, second.semantic_fingerprint)

    def test_registration_treats_repeated_canonical_digest_skill_ids_as_equivalent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "automation.sqlite3"
            store = SQLiteAutomationStore(db_path)
            first = store.create_from_registration(
                {
                    "automation_id": "daily_hot_a",
                    "name": "Daily Hot A",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize hot repos.",
                    "schedule_kind": "daily",
                    "schedule_expr": "23:31",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                    "enabled": True,
                }
            )

            second = store.create_from_registration(
                {
                    "automation_id": "daily_hot_b",
                    "name": "Daily Hot B",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize hot repos.",
                    "schedule_kind": "daily",
                    "schedule_expr": "23:31",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                    "enabled": True,
                }
            )

        self.assertEqual(first.automation_id, "daily_hot_a")
        self.assertEqual(second.automation_id, "daily_hot_a")

    def test_update_pause_resume_and_delete_automation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "automation.sqlite3"
            store = SQLiteAutomationStore(db_path)
            store.save(
                AutomationJob(
                    automation_id="daily_hot",
                    name="Daily GitHub Hot Repos",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="Summarize today's hot repositories.",
                    schedule_kind="daily",
                    schedule_expr="09:30",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id="github_trending_digest",
                    enabled=True,
                )
            )

            updated = store.update(
                "daily_hot",
                {
                    "name": "GitHub每日热榜Top10",
                    "schedule_expr": "23:50",
                },
            )
            paused = store.set_enabled("daily_hot", False)
            resumed = store.set_enabled("daily_hot", True)
            deleted = store.delete("daily_hot")
            reloaded = SQLiteAutomationStore(db_path)
            items = reloaded.list_all()

        self.assertEqual(updated.name, "GitHub每日热榜Top10")
        self.assertEqual(updated.schedule_expr, "23:50")
        self.assertFalse(paused.enabled)
        self.assertTrue(resumed.enabled)
        self.assertTrue(deleted)
        self.assertEqual(items, [])

    def test_update_recomputes_fingerprint_when_digest_skill_is_canonicalized(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "automation.sqlite3"
            store = SQLiteAutomationStore(db_path)
            store.save(
                AutomationJob(
                    automation_id="daily_hot",
                    name="Daily GitHub Hot Repos",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="Summarize today's hot repositories.",
                    schedule_kind="daily",
                    schedule_expr="09:30",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id="github_trending_digest",
                    enabled=True,
                )
            )
            before = store.get("daily_hot")

            updated = store.update(
                "daily_hot",
                {
                    "skill_id": "github_trending_digest",
                    "schedule_expr": "22:10",
                },
            )

        self.assertEqual(updated.skill_id, "github_trending_digest")
        self.assertEqual(updated.schedule_expr, "22:10")
        self.assertNotEqual(before.semantic_fingerprint, updated.semantic_fingerprint)


if __name__ == "__main__":
    unittest.main()
