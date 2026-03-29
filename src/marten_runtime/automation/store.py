from marten_runtime.automation.models import AutomationJob


class AutomationStore:
    def __init__(self) -> None:
        self._items: dict[str, AutomationJob] = {}

    def save(self, job: AutomationJob) -> None:
        self._items[job.automation_id] = job

    def list_enabled(self) -> list[AutomationJob]:
        return [item for item in self._items.values() if item.enabled]
