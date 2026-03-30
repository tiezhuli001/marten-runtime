from __future__ import annotations

from contextvars import ContextVar, Token
import re

from marten_runtime.automation.store import AutomationStore


REQUIRED_FIELDS = (
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

_REGISTRATION_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar(
    "registration_context",
    default=None,
)


def push_registration_context(context: dict[str, str]) -> Token:
    return _REGISTRATION_CONTEXT.set(context)


def pop_registration_context(token: Token) -> None:
    _REGISTRATION_CONTEXT.reset(token)


def run_register_automation_tool(payload: dict, store: AutomationStore) -> dict:
    normalized = _normalize_payload(payload, _REGISTRATION_CONTEXT.get() or {})
    missing = [field for field in REQUIRED_FIELDS if not str(normalized.get(field, "")).strip()]
    if missing:
        return {
            "ok": False,
            "error_code": "INVALID_AUTOMATION_REGISTRATION",
            "missing_fields": missing,
        }

    job = store.create_from_registration(
        {
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
    )
    return {
        "ok": True,
        "automation_id": job.automation_id,
        "semantic_fingerprint": job.semantic_fingerprint,
        "schedule_kind": job.schedule_kind,
        "schedule_expr": job.schedule_expr,
        "timezone": job.timezone,
        "delivery_channel": job.delivery_channel,
        "delivery_target": job.delivery_target,
        "skill_id": job.skill_id,
    }


def _normalize_payload(payload: dict, context: dict[str, str]) -> dict[str, object]:
    normalized = dict(payload)
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
    schedule_kind, schedule_expr = _normalize_schedule(
        str(payload.get("schedule_kind", "")),
        str(payload.get("schedule_expr", "")),
    )
    normalized["schedule_kind"] = schedule_kind
    normalized["schedule_expr"] = schedule_expr
    return normalized


def _resolve_alias(value: object, fallback: str, aliases: set[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if text.lower() in aliases:
        return fallback
    return text


def _normalize_schedule(schedule_kind: str, schedule_expr: str) -> tuple[str, str]:
    kind = schedule_kind.strip().lower()
    expr = schedule_expr.strip()
    daily_cron = re.fullmatch(r"(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*", expr)
    if daily_cron is not None and kind in {"", "cron", "daily"}:
        minute = int(daily_cron.group(1))
        hour = int(daily_cron.group(2))
        return "daily", f"{hour:02d}:{minute:02d}"
    return kind or "daily", expr
