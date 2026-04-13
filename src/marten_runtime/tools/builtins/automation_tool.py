from contextvars import ContextVar, Token

from marten_runtime.automation.store import AutomationStore
from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.tools.builtins.automation_tool_support import (
    REGISTRATION_REQUIRED_FIELDS,
    build_list_filters,
    build_registration_values,
    extract_update_values,
    normalize_registration_payload,
)
from marten_runtime.tools.builtins.automation_view import (
    present_automation,
    sort_presented_automations,
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
        deleted = adapter.delete_item("automation", item_id=automation_id)
    except KeyError:
        return {"ok": False, "automation_id": automation_id}
    return {"ok": bool(deleted["ok"]), "automation_id": automation_id}


def run_get_automation_detail_tool(
    payload: dict,
    adapter: DomainDataAdapter,
) -> dict:
    automation_id = str(payload.get("automation_id", "")).strip()
    if not automation_id:
        raise ValueError("automation_id is required")
    item = adapter.get_item("automation", item_id=automation_id)
    return {"ok": True, "automation": item}


def run_list_automations_tool(payload: dict, adapter: DomainDataAdapter) -> dict:
    filters = build_list_filters(payload)
    items = adapter.list_items("automation", filters=filters, limit=100)
    presented = sort_presented_automations([present_automation(item) for item in items])
    return {"ok": True, "items": presented, "count": len(presented)}


def run_pause_automation_tool(payload: dict, adapter: DomainDataAdapter) -> dict:
    automation_id = str(payload.get("automation_id", "")).strip()
    if not automation_id:
        raise ValueError("automation_id is required")
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
    normalized = normalize_registration_payload(payload, _REGISTRATION_CONTEXT.get() or {})
    missing = [
        field
        for field in REGISTRATION_REQUIRED_FIELDS
        if not str(normalized.get(field, "")).strip()
    ]
    if missing:
        return {
            "ok": False,
            "error_code": "INVALID_AUTOMATION_REGISTRATION",
            "missing_fields": missing,
        }

    values = build_registration_values(normalized)
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

def run_resume_automation_tool(payload: dict, adapter: DomainDataAdapter) -> dict:
    automation_id = str(payload.get("automation_id", "")).strip()
    if not automation_id:
        raise ValueError("automation_id is required")
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
    updates = extract_update_values(payload)
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
