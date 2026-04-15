import unittest
from datetime import datetime, timezone

from marten_runtime.automation.dispatch import AutomationDispatch
from marten_runtime.automation.models import AutomationJob
from marten_runtime.automation.scheduler import Scheduler
from marten_runtime.automation.store import AutomationStore


class AutomationDispatchTests(unittest.TestCase):
    def test_not_due_before_configured_window(self) -> None:
        store = AutomationStore()
        store.save(
            AutomationJob(
                automation_id="daily_hot",
                name="Daily GitHub Hot Repos",
                app_id="main_agent",
                agent_id="main",
                prompt_template="Summarize today's hot repositories.",
                schedule_kind="daily",
                schedule_expr="10:00",
                timezone="Asia/Shanghai",
                session_target="isolated",
                delivery_channel="feishu",
                delivery_target="oc_test_chat",
                skill_id="github_trending_digest",
            )
        )
        scheduler = Scheduler(store)

        dispatches = scheduler.tick(now=datetime(2026, 3, 30, 1, 59, tzinfo=timezone.utc))

        self.assertEqual(dispatches, [])

    def test_dispatches_once_for_due_window(self) -> None:
        store = AutomationStore()
        store.save(
            AutomationJob(
                automation_id="daily_hot",
                name="Daily GitHub Hot Repos",
                app_id="main_agent",
                agent_id="main",
                prompt_template="Summarize today's hot repositories.",
                schedule_kind="daily",
                schedule_expr="10:00",
                timezone="Asia/Shanghai",
                session_target="isolated",
                delivery_channel="feishu",
                delivery_target="oc_test_chat",
                skill_id="github_trending_digest",
            )
        )
        scheduler = Scheduler(store)

        dispatches = scheduler.tick(now=datetime(2026, 3, 30, 2, 0, tzinfo=timezone.utc))

        self.assertEqual(len(dispatches), 1)
        self.assertIsInstance(dispatches[0], AutomationDispatch)
        self.assertEqual(dispatches[0].automation_id, "daily_hot")
        self.assertEqual(dispatches[0].scheduled_for, "2026-03-30")
        self.assertEqual(dispatches[0].delivery_target, "oc_test_chat")
        self.assertEqual(dispatches[0].skill_id, "github_trending_digest")

    def test_same_day_window_is_idempotent(self) -> None:
        store = AutomationStore()
        store.save(
            AutomationJob(
                automation_id="daily_hot",
                name="Daily GitHub Hot Repos",
                app_id="main_agent",
                agent_id="main",
                prompt_template="Summarize today's hot repositories.",
                schedule_kind="daily",
                schedule_expr="10:00",
                timezone="Asia/Shanghai",
                session_target="isolated",
                delivery_channel="feishu",
                delivery_target="oc_test_chat",
                skill_id="github_trending_digest",
            )
        )
        scheduler = Scheduler(store)
        now = datetime(2026, 3, 30, 2, 0, tzinfo=timezone.utc)

        first = scheduler.tick(now=now)
        second = scheduler.tick(now=now)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])


if __name__ == "__main__":
    unittest.main()
