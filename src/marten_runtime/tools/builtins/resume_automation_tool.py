from __future__ import annotations

from marten_runtime.data_access.adapter import DomainDataAdapter


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
