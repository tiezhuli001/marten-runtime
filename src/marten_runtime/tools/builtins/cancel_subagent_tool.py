from __future__ import annotations


def run_cancel_subagent_tool(payload: dict, *, subagent_service) -> dict:
    task_id = str(payload.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("task_id is required")
    task = subagent_service.cancel_task(task_id)
    return {
        "ok": True,
        "task_id": task_id,
        "status": task.status,
        "cancelled": task.status == "cancelled",
    }
