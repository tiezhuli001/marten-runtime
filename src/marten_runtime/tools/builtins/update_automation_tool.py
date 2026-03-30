from __future__ import annotations

from marten_runtime.automation.store import AutomationStore


def run_update_automation_tool(payload: dict, store: AutomationStore) -> dict:
    automation_id = str(payload.get("automation_id", "")).strip()
    if not automation_id:
        raise ValueError("automation_id is required")
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
    job = store.update(automation_id, updates)
    return {"ok": True, "automation": job.model_dump(mode="json")}
