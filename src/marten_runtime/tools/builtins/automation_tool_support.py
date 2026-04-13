from __future__ import annotations

import re


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


REGISTRATION_REQUIRED_FIELDS = (
    "automation_id",
    "app_id",
    "agent_id",
    "schedule_kind",
    "schedule_expr",
    "timezone",
    "delivery_channel",
    "delivery_target",
    "skill_id",
)

_UPDATE_FIELDS = {
    "name",
    "prompt_template",
    "schedule_kind",
    "schedule_expr",
    "timezone",
    "session_target",
    "delivery_channel",
    "delivery_target",
    "skill_id",
}


def normalize_registration_payload(
    payload: dict,
    context: dict[str, str],
) -> dict[str, object]:
    normalized = dict(payload)
    if not str(normalized.get("name", "")).strip():
        normalized["name"] = str(payload.get("task_name", "")).strip()
    if not str(normalized.get("skill_id", "")).strip():
        normalized["skill_id"] = str(payload.get("skill", "")).strip()
    if "skill_id" in normalized:
        normalized["skill_id"] = str(normalized.get("skill_id", "")).strip()
    normalized["app_id"] = _resolve_alias(
        payload.get("app_id"),
        context.get("app_id", ""),
        {"default_app", "current_app"},
    )
    normalized["agent_id"] = _resolve_alias(
        payload.get("agent_id"),
        context.get("agent_id", ""),
        {"default_agent", "current_agent"},
    )
    normalized["delivery_channel"] = _resolve_alias(
        payload.get("delivery_channel"),
        context.get("channel_id", ""),
        {"current_channel", "same_channel"},
    )
    normalized["delivery_target"] = _resolve_alias(
        payload.get("delivery_target"),
        context.get("conversation_id", ""),
        {"current_channel", "current_chat", "current_conversation"},
    )
    schedule_kind, schedule_expr = normalize_schedule_input(
        str(payload.get("schedule_kind", "")),
        str(payload.get("schedule_expr", "")),
        trigger_time=str(payload.get("trigger_time", "")),
    )
    normalized["schedule_kind"] = schedule_kind
    normalized["schedule_expr"] = schedule_expr
    if not str(normalized.get("automation_id", "")).strip():
        normalized["automation_id"] = _build_default_automation_id(normalized)
    return normalized


def build_registration_values(normalized: dict[str, object]) -> dict[str, object]:
    return {
        "automation_id": str(normalized["automation_id"]),
        "name": str(normalized.get("name", normalized["automation_id"])),
        "app_id": str(normalized["app_id"]),
        "agent_id": str(normalized["agent_id"]),
        "prompt_template": str(normalized.get("prompt_template", "")),
        "schedule_kind": str(normalized["schedule_kind"]),
        "schedule_expr": str(normalized["schedule_expr"]),
        "timezone": str(normalized["timezone"]),
        "session_target": str(normalized.get("session_target", "isolated")),
        "delivery_channel": str(normalized["delivery_channel"]),
        "delivery_target": str(normalized["delivery_target"]),
        "skill_id": str(normalized["skill_id"]),
        "enabled": bool(normalized.get("enabled", True)),
    }


def build_list_filters(payload: dict) -> dict[str, object]:
    channel = str(payload.get("delivery_channel", "")).strip()
    target = str(payload.get("delivery_target", "")).strip()
    filters: dict[str, object] = {}
    if channel:
        filters["delivery_channel"] = channel
    if target:
        filters["delivery_target"] = target
    if "include_disabled" in payload:
        filters["include_disabled"] = bool(payload.get("include_disabled"))
    if "enabled" in payload:
        filters["enabled"] = bool(payload.get("enabled"))
    return filters


def extract_update_values(payload: dict) -> dict[str, object]:
    updates = {
        key: value
        for key, value in payload.items()
        if key in _UPDATE_FIELDS and value is not None
    }
    if "skill_id" in updates:
        updates["skill_id"] = str(updates["skill_id"])
    return updates


def _resolve_alias(value: object, fallback: str, aliases: set[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if text.lower() in aliases:
        return fallback
    return text


def _build_default_automation_id(normalized: dict[str, object]) -> str:
    skill_id = _slugify(str(normalized.get("skill_id", "")).strip() or "automation")
    schedule_expr = str(normalized.get("schedule_expr", "")).strip()
    hhmm = "".join(ch for ch in schedule_expr if ch.isdigit())[:4]
    if hhmm:
        return f"{skill_id}_{hhmm}"
    return skill_id


def _slugify(text: str) -> str:
    collapsed = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return collapsed or "automation"
