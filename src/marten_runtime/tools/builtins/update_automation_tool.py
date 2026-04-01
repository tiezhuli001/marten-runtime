from __future__ import annotations

from marten_runtime.data_access.adapter import DomainDataAdapter


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
    item = adapter.update_item("automation", item_id=automation_id, values=updates)
    return {"ok": True, "automation": item}
