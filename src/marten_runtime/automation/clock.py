from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from marten_runtime.automation.models import AutomationJob


def scheduled_day_if_due(job: AutomationJob, now: datetime) -> str | None:
    if job.schedule_kind != "daily":
        return None
    local_now = now.astimezone(ZoneInfo(job.timezone))
    hour_text, minute_text = job.schedule_expr.split(":", maxsplit=1)
    scheduled_hour = int(hour_text)
    scheduled_minute = int(minute_text)
    if (local_now.hour, local_now.minute) < (scheduled_hour, scheduled_minute):
        return None
    return local_now.date().isoformat()
