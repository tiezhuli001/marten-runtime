from datetime import datetime, timezone

from marten_runtime.execution.models import JobRecord


class InMemoryExecutionQueue:
    def __init__(self) -> None:
        self._items: list[JobRecord] = []

    def push(self, job: JobRecord) -> None:
        self._items.append(job)

    def pop(self) -> JobRecord:
        job = next(item for item in self._items if item.state == "queued")
        job.state = "running"
        job.updated_at = datetime.now(timezone.utc)
        return job

    def peek_all(self) -> list[JobRecord]:
        return self._items
