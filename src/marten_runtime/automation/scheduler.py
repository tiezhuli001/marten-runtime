from uuid import uuid4

from marten_runtime.automation.store import AutomationStore
from marten_runtime.execution.models import JobRecord
from marten_runtime.execution.queue import InMemoryExecutionQueue


class Scheduler:
    def __init__(self, store: AutomationStore, queue: InMemoryExecutionQueue) -> None:
        self.store = store
        self.queue = queue

    def tick(self) -> list[str]:
        created: list[str] = []
        for item in self.store.list_enabled():
            job_id = f"{item.automation_id}:{uuid4().hex[:8]}"
            job = JobRecord(
                job_id=job_id,
                job_type="automation",
                session_id=item.automation_id,
                app_id=item.app_id,
                agent_id=item.agent_id,
                dedupe_key=job_id,
                prompt_mode="child" if item.session_target == "isolated" else "full",
            )
            self.queue.push(job)
            created.append(job_id)
        return created
