from __future__ import annotations

from marten_runtime.subagents.policy import (
    latest_user_message_text,
    resolve_requested_subagent_tool_profile,
)


def run_spawn_subagent_tool(
    payload: dict,
    *,
    subagent_service,
    session_store=None,
    tool_context: dict | None = None,
) -> dict:
    task = str(payload.get("task") or "").strip()
    if not task:
        raise ValueError("task is required")
    session_id = str((tool_context or {}).get("session_id") or "").strip()
    run_id = str((tool_context or {}).get("run_id") or "").strip()
    agent_id = str((tool_context or {}).get("agent_id") or "main").strip() or "main"
    app_id = str((tool_context or {}).get("app_id") or "main_agent").strip() or "main_agent"
    if not session_id:
        raise ValueError("tool_context.session_id is required")
    if not run_id:
        raise ValueError("tool_context.run_id is required")
    latest_user_message = latest_user_message_text(session_store, session_id) if session_store is not None else None
    requested_tool_profile = resolve_requested_subagent_tool_profile(
        task=task,
        latest_user_message=latest_user_message,
        requested_tool_profile=str(payload.get("tool_profile") or "").strip() or None,
    )

    result = subagent_service.spawn(
        task=task,
        label=str(payload.get("label") or "").strip() or None,
        parent_session_id=session_id,
        parent_run_id=run_id,
        parent_agent_id=agent_id,
        app_id=app_id,
        agent_id=str(payload.get("agent_id") or agent_id).strip() or agent_id,
        requested_tool_profile=requested_tool_profile,
        parent_allowed_tools=list((tool_context or {}).get("allowed_tools") or []),
        origin_channel_id=str((tool_context or {}).get("channel_id") or "").strip() or None,
        context_mode=str(payload.get("context_mode") or "brief_only").strip() or "brief_only",
        notify_on_finish=bool(payload.get("notify_on_finish", True)),
    )
    return {"ok": True, **result}
