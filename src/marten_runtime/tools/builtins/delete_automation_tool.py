from __future__ import annotations

from marten_runtime.data_access.adapter import DomainDataAdapter


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
