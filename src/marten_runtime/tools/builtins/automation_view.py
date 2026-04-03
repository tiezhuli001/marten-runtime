from __future__ import annotations

import re
from collections.abc import Mapping

_SKILL_DISPLAY_NAMES = {
    "github_hot_repos_digest": "GitHub Top10",
}


def normalize_schedule_input(
    schedule_kind: str,
    schedule_expr: str,
    *,
    trigger_time: str = "",
) -> tuple[str, str]:
    kind = schedule_kind.strip().lower()
    expr = schedule_expr.strip()
    trigger = trigger_time.strip()
    if not expr and re.fullmatch(r"\d{1,2}:\d{2}", trigger):
        hour, minute = [int(part) for part in trigger.split(":", 1)]
        return "daily", f"{hour:02d}:{minute:02d}"
    daily_cron = re.fullmatch(r"(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*", expr)
    if daily_cron is not None and kind in {"", "cron", "daily"}:
        minute = int(daily_cron.group(1))
        hour = int(daily_cron.group(2))
        return "daily", f"{hour:02d}:{minute:02d}"
    daily_cron_with_seconds = re.fullmatch(r"(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*", expr)
    if daily_cron_with_seconds is not None and kind in {"", "cron", "daily"}:
        minute = int(daily_cron_with_seconds.group(2))
        hour = int(daily_cron_with_seconds.group(3))
        return "daily", f"{hour:02d}:{minute:02d}"
    return kind or "daily", expr


def build_schedule_text(schedule_kind: str, schedule_expr: str) -> str:
    kind = schedule_kind.strip().lower()
    expr = schedule_expr.strip()
    if kind == "daily" and re.fullmatch(r"\d{2}:\d{2}", expr):
        return f"每天 {expr}"
    return expr


def present_automation(item: Mapping[str, object]) -> dict[str, object]:
    raw_schedule_kind = str(item.get("schedule_kind", "")).strip()
    raw_schedule_expr = str(item.get("schedule_expr", "")).strip()
    schedule_kind, schedule_expr = normalize_schedule_input(raw_schedule_kind, raw_schedule_expr)
    automation_id = str(item.get("automation_id", "")).strip()
    skill_id = str(item.get("skill_id", "")).strip()
    raw_name = str(item.get("name", "")).strip()
    name = _present_name(raw_name, automation_id, skill_id)
    return {
        "automation_id": automation_id,
        "name": name,
        "schedule_kind": schedule_kind,
        "schedule_expr": schedule_expr,
        "schedule_text": build_schedule_text(schedule_kind, schedule_expr),
        "timezone": str(item.get("timezone", "")).strip(),
        "enabled": bool(item.get("enabled", True)),
    }


def _present_name(raw_name: str, automation_id: str, skill_id: str) -> str:
    if raw_name and raw_name != automation_id:
        return raw_name
    if skill_id in _SKILL_DISPLAY_NAMES:
        return _SKILL_DISPLAY_NAMES[skill_id]
    if raw_name:
        return raw_name
    return automation_id
