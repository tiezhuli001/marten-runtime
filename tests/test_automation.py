import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.automation.models import AutomationJob
from marten_runtime.config.automations_loader import load_automations
from marten_runtime.automation.scheduler import Scheduler
from marten_runtime.automation.store import AutomationStore


class AutomationTests(unittest.TestCase):
    def test_store_reads_enabled_daily_job(self) -> None:
        store = AutomationStore()
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
                skill_id="github_hot_repos_digest",
                enabled=True,
            )
        )

        enabled = store.list_enabled()

        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].schedule_kind, "daily")
        self.assertEqual(enabled[0].schedule_expr, "09:30")
        self.assertEqual(enabled[0].delivery_target, "oc_test_chat")
        self.assertEqual(enabled[0].skill_id, "github_hot_repos_digest")
        self.assertTrue(enabled[0].semantic_fingerprint)

    def test_loader_supports_seed_data(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            example = root / "config" / "automations.example.toml"
            example.parent.mkdir(parents=True, exist_ok=True)
            example.write_text(
                """
[[automations]]
automation_id = "daily_hot"
name = "Daily GitHub Hot Repos"
app_id = "example_assistant"
agent_id = "assistant"
prompt_template = "Summarize today's hot repositories."
schedule_kind = "daily"
schedule_expr = "10:00"
timezone = "Asia/Shanghai"
session_target = "isolated"
delivery_channel = "feishu"
delivery_target = "oc_test_chat"
skill_id = "github_hot_repos_digest"
enabled = true
""".strip(),
                encoding="utf-8",
            )

            jobs = load_automations(str(root / "config" / "automations.toml"))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].automation_id, "daily_hot")
        self.assertEqual(jobs[0].schedule_expr, "10:00")
        self.assertEqual(jobs[0].delivery_channel, "feishu")
        self.assertEqual(jobs[0].skill_id, "github_hot_repos_digest")

    def test_scheduler_creates_dispatch_and_preserves_isolated_target(self) -> None:
        store = AutomationStore()
        store.save(
            AutomationJob(
                automation_id="auto_1",
                app_id="example_assistant",
                agent_id="assistant",
                prompt_template="daily check",
                schedule_kind="daily",
                schedule_expr="10:00",
                session_target="isolated",
                delivery_channel="feishu",
                delivery_target="oc_test_chat",
                skill_id="github_hot_repos_digest",
            )
        )
        scheduler = Scheduler(store)

        created = scheduler.tick(now=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc))

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].session_target, "isolated")
        self.assertEqual(created[0].delivery_target, "oc_test_chat")
        self.assertEqual(created[0].skill_id, "github_hot_repos_digest")

    def test_scheduler_includes_internal_self_improve_job(self) -> None:
        store = AutomationStore()
        store.save(
            AutomationJob(
                automation_id="self_improve_internal",
                app_id="example_assistant",
                agent_id="assistant",
                prompt_template="Summarize repeated failures and later recoveries.",
                schedule_kind="daily",
                schedule_expr="03:00",
                session_target="isolated",
                delivery_channel="http",
                delivery_target="internal",
                skill_id="self_improve",
                internal=True,
            )
        )
        scheduler = Scheduler(store)

        created = scheduler.tick(now=datetime(2026, 3, 30, 3, 0, tzinfo=timezone.utc))

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].skill_id, "self_improve")
        self.assertEqual(created[0].delivery_channel, "http")
        self.assertEqual(created[0].delivery_target, "internal")


if __name__ == "__main__":
    unittest.main()
