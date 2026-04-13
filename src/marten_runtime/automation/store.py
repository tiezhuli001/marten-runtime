from marten_runtime.automation.models import AutomationJob, build_automation_semantic_fingerprint
from marten_runtime.automation.skill_ids import canonicalize_automation_skill_id


class AutomationStore:
    def __init__(self) -> None:
        self._items: dict[str, AutomationJob] = {}
        self._dispatch_windows: set[tuple[str, str]] = set()

    def save(self, job: AutomationJob) -> None:
        self._items[job.automation_id] = job

    def create_job(self, values: dict[str, object]) -> AutomationJob:
        job = AutomationJob(**_normalize_automation_values(values))
        self.save(job)
        return job

    def list_enabled(self) -> list[AutomationJob]:
        return [item for item in self.list_all() if item.enabled]

    def list_all(self) -> list[AutomationJob]:
        return list(self._items.values())

    def list_public(self, *, include_disabled: bool = False) -> list[AutomationJob]:
        source = self.list_all() if include_disabled else self.list_enabled()
        return [item for item in source if not item.internal]

    def get(self, automation_id: str) -> AutomationJob:
        return self._items[automation_id]

    def update(self, automation_id: str, updates: dict[str, object]) -> AutomationJob:
        current = self.get(automation_id)
        merged = current.model_copy(update=_normalize_automation_values(updates))
        merged.semantic_fingerprint = build_automation_semantic_fingerprint(merged)
        self.save(merged)
        return merged

    def set_enabled(self, automation_id: str, enabled: bool) -> AutomationJob:
        return self.update(automation_id, {"enabled": enabled})

    def delete(self, automation_id: str) -> bool:
        if automation_id not in self._items:
            return False
        del self._items[automation_id]
        return True

    def create_from_registration(self, payload: dict[str, str]) -> AutomationJob:
        existing = self.find_equivalent_registration(payload)
        if existing is not None:
            return existing
        return self.create_job(payload)

    def find_equivalent_registration(self, payload: dict[str, str]) -> AutomationJob | None:
        for item in self.list_enabled():
            if _is_equivalent_registration(item, payload):
                return item
        return None

    def record_dispatched_window(
        self,
        *,
        automation_id: str,
        scheduled_for: str,
        delivery_target: str,
        dedupe_key: str,
    ) -> bool:
        window = (automation_id, scheduled_for)
        if window in self._dispatch_windows:
            return False
        self._dispatch_windows.add(window)
        return True

    def has_dispatched_window(self, automation_id: str, scheduled_for: str) -> bool:
        return (automation_id, scheduled_for) in self._dispatch_windows


def _is_equivalent_registration(job: AutomationJob, payload: dict[str, str]) -> bool:
    if not job.enabled:
        return False
    return job.semantic_fingerprint == build_automation_semantic_fingerprint(payload)


def _normalize_automation_values(values: dict[str, object]) -> dict[str, object]:
    normalized = dict(values)
    if "skill_id" in normalized:
        normalized["skill_id"] = canonicalize_automation_skill_id(str(normalized["skill_id"]))
    return normalized
