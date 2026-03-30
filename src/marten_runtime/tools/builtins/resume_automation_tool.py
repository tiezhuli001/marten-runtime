from __future__ import annotations

from marten_runtime.automation.store import AutomationStore


def run_resume_automation_tool(payload: dict, store: AutomationStore) -> dict:
    automation_id = str(payload.get("automation_id", "")).strip()
    if not automation_id:
        raise ValueError("automation_id is required")
    job = store.set_enabled(automation_id, True)
    return {"ok": True, "automation": job.model_dump(mode="json")}
