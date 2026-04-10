from contextvars import ContextVar, Token
import re

from marten_runtime.automation.skill_ids import canonicalize_automation_skill_id
from marten_runtime.automation.store import AutomationStore
from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.tools.builtins.automation_view import (
    normalize_schedule_input,
    present_automation,
    sort_presented_automations,
)


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


def run_delete_automation_tool(payload: dict, adapter: DomainDataAdapter) -> dict:
    automation_id = str(payload.get("automation_id", "")).strip()
    if not automation_id:
        raise ValueError("automation_id is required")
    try:
        item = adapter.get_item("automation", item_id=automation_id)
    except KeyError:
        return {"ok": False, "automation_id": automation_id}
    if bool(item.get("internal", False)):
        return {"ok": False, "automation_id": automation_id}
    deleted = adapter.delete_item("automation", item_id=automation_id)
    return {"ok": bool(deleted["ok"]), "automation_id": automation_id}


def run_get_automation_detail_tool(
    payload: dict,
    adapter: DomainDataAdapter,
) -> dict:
    automation_id = str(payload.get("automation_id", "")).strip()
    if not automation_id:
        raise ValueError("automation_id is required")
    item = adapter.get_item("automation", item_id=automation_id)
    if bool(item.get("internal", False)):
        raise KeyError(automation_id)
    return {"ok": True, "automation": item}


def run_list_automations_tool(payload: dict, adapter: DomainDataAdapter) -> dict:
    channel = str(payload.get("delivery_channel", "")).strip()
    target = str(payload.get("delivery_target", "")).strip()
    include_disabled = bool(payload.get("include_disabled", False))
    filters: dict[str, object] = {}
    if channel:
        filters["delivery_channel"] = channel
    if target:
        filters["delivery_target"] = target
    if include_disabled:
        filters["include_disabled"] = True
    items = adapter.list_items("automation", filters=filters, limit=100)
    presented = sort_presented_automations([present_automation(item) for item in items])
    return {"ok": True, "items": presented, "count": len(presented)}


def run_pause_automation_tool(payload: dict, adapter: DomainDataAdapter) -> dict:
    automation_id = str(payload.get("automation_id", "")).strip()
    if not automation_id:
        raise ValueError("automation_id is required")
    item = adapter.get_item("automation", item_id=automation_id)
    if bool(item.get("internal", False)):
        raise KeyError(automation_id)
    updated = adapter.update_item(
        "automation",
        item_id=automation_id,
        values={"enabled": False},
    )
    return {"ok": True, "automation": updated}


def run_register_automation_tool(
    payload: dict,
    store: AutomationStore,
    adapter: DomainDataAdapter | None = None,
) -> dict:
    normalized = _normalize_payload(payload, _REGISTRATION_CONTEXT.get() or {})
    missing = [
        field for field in REQUIRED_FIELDS if not str(normalized.get(field, "")).strip()
    ]
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
    if str(normalized.get("skill_id", "")).strip():
        normalized["skill_id"] = canonicalize_automation_skill_id(
            str(normalized["skill_id"])
        )
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


def run_resume_automation_tool(payload: dict, adapter: DomainDataAdapter) -> dict:
    automation_id = str(payload.get("automation_id", "")).strip()
    if not automation_id:
        raise ValueError("automation_id is required")
    item = adapter.get_item("automation", item_id=automation_id)
    if bool(item.get("internal", False)):
        raise KeyError(automation_id)
    updated = adapter.update_item(
        "automation",
        item_id=automation_id,
        values={"enabled": True},
    )
    return {"ok": True, "automation": updated}


def run_update_automation_tool(payload: dict, adapter: DomainDataAdapter) -> dict:
    automation_id = str(payload.get("automation_id", "")).strip()
    if not automation_id:
        raise ValueError("automation_id is required")
    existing = adapter.get_item("automation", item_id=automation_id)
    if bool(existing.get("internal", False)):
        raise KeyError(automation_id)
    updates = {
        key: value
        for key, value in payload.items()
        if key
        in {
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
        and value is not None
    }
    if "skill_id" in updates:
        updates["skill_id"] = canonicalize_automation_skill_id(str(updates["skill_id"]))
    item = adapter.update_item("automation", item_id=automation_id, values=updates)
    return {"ok": True, "automation": item}


def run_automation_tool(
    payload: dict,
    store: AutomationStore,
    adapter: DomainDataAdapter,
) -> dict:
    action = str(payload.get("action", "")).strip().lower()
    if not action and not payload:
        action = "list"
    request = {key: value for key, value in payload.items() if key != "action"}
    if action == "list" and "include_disabled" not in request:
        request["include_disabled"] = True
    if action == "register":
        result = run_register_automation_tool(request, store, adapter)
    elif action == "list":
        result = run_list_automations_tool(request, adapter)
    elif action == "detail":
        result = run_get_automation_detail_tool(request, adapter)
    elif action == "update":
        result = run_update_automation_tool(request, adapter)
    elif action == "delete":
        result = run_delete_automation_tool(request, adapter)
    elif action == "pause":
        result = run_pause_automation_tool(request, adapter)
    elif action == "resume":
        result = run_resume_automation_tool(request, adapter)
    else:
        raise ValueError("unsupported automation action")
    return {"action": action, **result}


def render_automation_tool_text(result: dict) -> str:
    action = str(result.get("action", "")).strip().lower()
    if action == "list":
        items = list(result.get("items") or [])
        count = int(result.get("count") or len(items))
        enabled_count = sum(1 for item in items if bool(item.get("enabled", True)))
        paused_count = max(0, count - enabled_count)
        lines = [
            f"当前共有 {count} 个定时任务，其中 {enabled_count} 个已启用，{paused_count} 个已暂停。"
        ]
        if items:
            for item in items:
                lines.append(
                    f"- {_automation_name(item)}｜{_automation_enabled_text(item)}｜{_automation_schedule_text(item)}"
                )
        return "\n".join(lines)
    if action == "detail":
        item = _automation_result_item(result)
        if not item:
            return ""
        return "\n".join(
            _render_automation_lines(
                item,
                heading=f"定时任务 {_automation_name(item)} 的当前配置如下：",
            )
        )
    if action == "register":
        item = _automation_result_item(result)
        if not item or result.get("ok") is False:
            return ""
        return "\n".join(
            _render_automation_lines(
                item,
                heading=f"已创建定时任务 {_automation_name(item)}。",
            )
        )
    if action == "update":
        item = _automation_result_item(result)
        if not item or result.get("ok") is False:
            return ""
        return "\n".join(
            _render_automation_lines(
                item,
                heading=f"已更新定时任务 {_automation_name(item)}。",
            )
        )
    if action == "pause":
        item = _automation_result_item(result)
        if not item or result.get("ok") is False:
            return ""
        return "\n".join(
            _render_automation_lines(
                item,
                heading=f"已暂停定时任务 {_automation_name(item)}。",
            )
        )
    if action == "resume":
        item = _automation_result_item(result)
        if not item or result.get("ok") is False:
            return ""
        return "\n".join(
            _render_automation_lines(
                item,
                heading=f"已恢复定时任务 {_automation_name(item)}。",
            )
        )
    if action == "delete":
        if result.get("ok") is False:
            return ""
        automation_id = str(result.get("automation_id", "")).strip()
        if not automation_id:
            return ""
        return f"已删除定时任务 {automation_id}。"
    return ""


def _automation_result_item(result: dict) -> dict[str, object]:
    nested = result.get("automation")
    if isinstance(nested, dict) and nested:
        return dict(nested)
    item = {
        key: value
        for key, value in result.items()
        if key
        not in {"action", "ok", "semantic_fingerprint", "error_code", "missing_fields"}
    }
    return item if item else {}


def _automation_name(item: dict[str, object]) -> str:
    return str(item.get("name", "")).strip() or str(item.get("automation_id", "")).strip()


def _automation_enabled_text(item: dict[str, object]) -> str:
    return "已启用" if bool(item.get("enabled", True)) else "已暂停"


def _automation_schedule_text(item: dict[str, object]) -> str:
    return str(item.get("schedule_expr", "")).strip() or str(
        item.get("schedule_text", "")
    ).strip()


def _render_automation_lines(
    item: dict[str, object],
    *,
    heading: str,
) -> list[str]:
    schedule_kind = str(item.get("schedule_kind", "")).strip()
    schedule_expr = str(item.get("schedule_expr", "")).strip()
    timezone = str(item.get("timezone", "")).strip()
    delivery_channel = str(item.get("delivery_channel", "")).strip()
    delivery_target = str(item.get("delivery_target", "")).strip()
    skill_id = str(item.get("skill_id", "")).strip()
    lines = [
        heading,
        "",
        f"- automation_id：{str(item.get('automation_id', '')).strip()}",
        f"- 状态：{_automation_enabled_text(item)}",
    ]
    if schedule_kind or schedule_expr:
        lines.append(f"- 调度：{schedule_kind or 'unknown'} {schedule_expr}".rstrip())
    if timezone:
        lines.append(f"- 时区：{timezone}")
    if delivery_channel:
        lines.append(f"- 投递渠道：{delivery_channel}")
    if delivery_target:
        lines.append(f"- 投递目标：{delivery_target}")
    if skill_id:
        lines.append(f"- skill_id：{skill_id}")
    return lines
