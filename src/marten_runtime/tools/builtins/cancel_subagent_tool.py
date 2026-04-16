from __future__ import annotations


def run_cancel_subagent_tool(
    payload: dict,
    *,
    subagent_service,
    tool_context: dict | None = None,
) -> dict:
    task_id = str(payload.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("task_id is required")
    task = subagent_service.cancel_task(
        task_id,
        requester_session_id=(
            str((tool_context or {}).get("session_id") or "").strip() or None
        ),
    )
    return {
        "ok": True,
        "task_id": task_id,
        "status": task.status,
        "cancelled": task.status == "cancelled",
    }
