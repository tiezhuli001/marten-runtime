import unittest

from marten_runtime.automation.models import AutomationJob
from marten_runtime.automation.scheduler import Scheduler
from marten_runtime.automation.store import AutomationStore
from marten_runtime.execution.queue import InMemoryExecutionQueue


class AutomationTests(unittest.TestCase):
    def test_scheduler_creates_jobs_and_isolated_target_uses_child_prompt_mode(self) -> None:
        store = AutomationStore()
        store.save(
            AutomationJob(
                automation_id="auto_1",
                app_id="example_assistant",
                agent_id="assistant",
                prompt="daily check",
                schedule_type="every",
                schedule_value="1h",
                session_target="isolated",
                delivery_mode="announce",
            )
        )
        queue = InMemoryExecutionQueue()
        scheduler = Scheduler(store, queue)

        created = scheduler.tick()
        queued = queue.peek_all()

        self.assertEqual(len(created), 1)
        self.assertEqual(queued[0].prompt_mode, "child")
        self.assertEqual(queued[0].resolved_config_snapshot_id, None)


if __name__ == "__main__":
    unittest.main()
