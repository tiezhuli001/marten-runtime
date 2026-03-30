from __future__ import annotations

from marten_runtime.automation.store import AutomationStore


def run_list_automations_tool(payload: dict, store: AutomationStore) -> dict:
    channel = str(payload.get("delivery_channel", "")).strip()
    target = str(payload.get("delivery_target", "")).strip()
    include_disabled = bool(payload.get("include_disabled", False))
    items = []
    source = store.list_all() if include_disabled else store.list_enabled()
    for job in source:
        if channel and job.delivery_channel != channel:
            continue
        if target and job.delivery_target != target:
            continue
        items.append(
            {
                "automation_id": job.automation_id,
                "name": job.name,
                "schedule_kind": job.schedule_kind,
                "schedule_expr": job.schedule_expr,
                "timezone": job.timezone,
                "delivery_channel": job.delivery_channel,
                "delivery_target": job.delivery_target,
                "skill_id": job.skill_id,
                "enabled": job.enabled,
            }
        )
    return {"ok": True, "items": items, "count": len(items)}
