from __future__ import annotations

from contextvars import ContextVar, Token
import re

from marten_runtime.automation.store import AutomationStore
from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.tools.builtins.automation_view import normalize_schedule_input, present_automation


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


def run_register_automation_tool(
    payload: dict,
    store: AutomationStore,
    adapter: DomainDataAdapter | None = None,
) -> dict:
    normalized = _normalize_payload(payload, _REGISTRATION_CONTEXT.get() or {})
    missing = [field for field in REQUIRED_FIELDS if not str(normalized.get(field, "")).strip()]
    if missing:
        return {
            "ok": False,
            "error_code": "INVALID_AUTOMATION_REGISTRATION",
            "missing_fields": missing,
        }

    values = {
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
    existing = store.find_equivalent_registration(values)
    if existing is not None:
        job = existing
    elif adapter is not None:
        created = adapter.create_item("automation", values=values)
        job = store.get(str(created["automation_id"]))
    else:
        job = store.create_from_registration(values)
    return {
        "ok": True,
        **present_automation(
            {
                "automation_id": job.automation_id,
                "name": job.name,
                "schedule_kind": job.schedule_kind,
                "schedule_expr": job.schedule_expr,
                "timezone": job.timezone,
                "enabled": job.enabled,
            }
        ),
        "semantic_fingerprint": job.semantic_fingerprint,
    }


def _normalize_payload(payload: dict, context: dict[str, str]) -> dict[str, object]:
    normalized = dict(payload)
    if not str(normalized.get("name", "")).strip():
        normalized["name"] = str(payload.get("task_name", "")).strip()
    if not str(normalized.get("skill_id", "")).strip():
        normalized["skill_id"] = str(payload.get("skill", "")).strip()
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
