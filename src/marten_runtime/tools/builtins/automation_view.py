from __future__ import annotations

import re
from collections.abc import Mapping

from marten_runtime.automation.skill_ids import display_name_for_automation_skill_id
from marten_runtime.tools.builtins.automation_tool_support import normalize_schedule_input


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


def sort_presented_automations(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(items, key=_automation_sort_key)


def _present_name(raw_name: str, automation_id: str, skill_id: str) -> str:
    display_name = display_name_for_automation_skill_id(skill_id)
    if display_name is not None and raw_name in {automation_id, skill_id}:
        return display_name
    if raw_name and raw_name != automation_id:
        return raw_name
    if display_name is not None:
        return display_name
    if raw_name:
        return raw_name
    return automation_id


def _automation_sort_key(item: Mapping[str, object]) -> tuple[int, str, str, str]:
    schedule_kind = str(item.get("schedule_kind", "")).strip().lower()
    schedule_expr = str(item.get("schedule_expr", "")).strip()
    schedule_group, schedule_value = _sortable_schedule_value(schedule_kind, schedule_expr)
    name = str(item.get("name", "")).strip()
    automation_id = str(item.get("automation_id", "")).strip()
    return (schedule_group, schedule_value, name, automation_id)


def _sortable_schedule_value(schedule_kind: str, schedule_expr: str) -> tuple[int, str]:
    normalized_kind, normalized_expr = normalize_schedule_input(schedule_kind, schedule_expr)
    if normalized_kind == "daily" and re.fullmatch(r"\d{2}:\d{2}", normalized_expr):
        return 0, normalized_expr
    return 1, f"{normalized_kind}:{normalized_expr}"
