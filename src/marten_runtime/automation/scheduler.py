from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.automation.clock import scheduled_day_if_due
from marten_runtime.automation.dispatch import AutomationDispatch, build_dispatch
from marten_runtime.automation.store import AutomationStore


class Scheduler:
    def __init__(self, store: AutomationStore) -> None:
        self.store = store

    def tick(self, *, now: datetime | None = None) -> list[AutomationDispatch]:
        current_time = now or datetime.now(timezone.utc)
        created: list[AutomationDispatch] = []
        for item in self.store.list_enabled():
            scheduled_for = scheduled_day_if_due(item, current_time)
            if scheduled_for is None:
                continue
            if not self.store.record_dispatched_window(
                automation_id=item.automation_id,
                scheduled_for=scheduled_for,
                delivery_target=item.delivery_target,
                dedupe_key=f"{item.automation_id}:{scheduled_for}",
            ):
                continue
            created.append(
                build_dispatch(
                    item,
                    scheduled_for=scheduled_for,
                    trace_id=f"trace_auto_{uuid4().hex[:8]}",
                )
            )
        return created
