import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.automation.models import AutomationJob
from marten_runtime.automation.sqlite_store import SQLiteAutomationStore


class SQLiteAutomationStoreTests(unittest.TestCase):
    def test_save_and_reload_enabled_automation_definition(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nested" / "automation.sqlite3"
            store = SQLiteAutomationStore(db_path)
            self.assertTrue(db_path.parent.exists())
            store.save(
                AutomationJob(
                    automation_id="daily_hot",
                    name="Daily GitHub Hot Repos",
                    app_id="main_agent",
                    agent_id="main",
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

    def test_registration_reuses_existing_equivalent_automation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "automation.sqlite3"
            store = SQLiteAutomationStore(db_path)
            first = store.create_from_registration(
                {
                    "automation_id": "daily_hot_a",
                    "name": "Daily Hot A",
                    "app_id": "main_agent",
                    "agent_id": "main",
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
                    "app_id": "main_agent",
                    "agent_id": "main",
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

    def test_update_pause_resume_and_delete_automation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "automation.sqlite3"
            store = SQLiteAutomationStore(db_path)
            store.save(
                AutomationJob(
                    automation_id="daily_hot",
                    name="Daily GitHub Hot Repos",
                    app_id="main_agent",
                    agent_id="main",
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
                    app_id="main_agent",
                    agent_id="main",
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

    def test_legacy_assistant_agent_id_is_canonicalized_and_fingerprint_is_recomputed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "automation.sqlite3"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE automations (
                        automation_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        app_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        prompt_template TEXT NOT NULL,
                        schedule_kind TEXT NOT NULL,
                        schedule_expr TEXT NOT NULL,
                        timezone TEXT NOT NULL,
                        session_target TEXT NOT NULL,
                        delivery_channel TEXT NOT NULL,
                        delivery_target TEXT NOT NULL,
                        skill_id TEXT NOT NULL,
                        enabled INTEGER NOT NULL,
                        internal INTEGER NOT NULL DEFAULT 0,
                        semantic_fingerprint TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO automations (
                        automation_id, name, app_id, agent_id, prompt_template,
                        schedule_kind, schedule_expr, timezone, session_target,
                        delivery_channel, delivery_target, skill_id, enabled, internal, semantic_fingerprint
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "daily_hot",
                        "Daily GitHub Hot Repos",
                        "main_agent",
                        "assistant",
                        "Summarize today's hot repositories.",
                        "daily",
                        "09:30",
                        "Asia/Shanghai",
                        "isolated",
                        "feishu",
                        "oc_test_chat",
                        "github_trending_digest",
                        1,
                        0,
                        "legacy_fingerprint",
                    ),
                )

            reloaded = SQLiteAutomationStore(db_path)
            job = reloaded.get("daily_hot")
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT agent_id, semantic_fingerprint FROM automations WHERE automation_id = ?",
                    ("daily_hot",),
                ).fetchone()

        self.assertEqual(job.agent_id, "main")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(str(row[0]), "main")
        self.assertNotEqual(str(row[1]), "legacy_fingerprint")


if __name__ == "__main__":
    unittest.main()
