from __future__ import annotations

from marten_runtime.automation.store import AutomationStore


def run_delete_automation_tool(payload: dict, store: AutomationStore) -> dict:
    automation_id = str(payload.get("automation_id", "")).strip()
    if not automation_id:
        raise ValueError("automation_id is required")
    deleted = store.delete(automation_id)
    return {"ok": deleted, "automation_id": automation_id}
