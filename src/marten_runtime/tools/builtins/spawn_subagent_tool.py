from __future__ import annotations

from marten_runtime.agents.ids import canonicalize_runtime_agent_id
from marten_runtime.subagents.tool_profiles import normalize_tool_profile_name

ALLOWED_CONTEXT_MODES = {"brief_only", "brief_plus_snapshot"}


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
    agent_id = canonicalize_runtime_agent_id(
        (tool_context or {}).get("agent_id"),
        default="main",
    ) or "main"
    app_id = str((tool_context or {}).get("app_id") or "main_agent").strip() or "main_agent"
    if not session_id:
        raise ValueError("tool_context.session_id is required")
    if not run_id:
        raise ValueError("tool_context.run_id is required")
    del session_store
    raw_tool_profile = str(payload.get("tool_profile") or "").strip()
    if not raw_tool_profile:
        requested_tool_profile = "standard"
    else:
        normalized_tool_profile = normalize_tool_profile_name(raw_tool_profile)
        requested_tool_profile = normalized_tool_profile
    requested_agent_id = canonicalize_runtime_agent_id(payload.get("agent_id")) or ""
    if requested_agent_id.lower() == "default":
        requested_agent_id = ""
    context_mode = str(payload.get("context_mode") or "").strip()
    if not context_mode:
        context_mode = "brief_only"
    elif context_mode not in ALLOWED_CONTEXT_MODES:
        raise ValueError(f"unknown context mode: {context_mode}")
    channel_id = str((tool_context or {}).get("channel_id") or "").strip()
    conversation_id = str((tool_context or {}).get("conversation_id") or "").strip()
    source_transport = str((tool_context or {}).get("source_transport") or "").strip()
    origin_delivery_target = None
    if (
        channel_id == "feishu"
        and conversation_id
        and source_transport == "feishu_websocket"
    ):
        origin_delivery_target = conversation_id

    result = subagent_service.spawn(
        task=task,
        label=str(payload.get("label") or "").strip() or None,
        parent_session_id=session_id,
        parent_run_id=run_id,
        parent_agent_id=agent_id,
        app_id=app_id,
        agent_id=requested_agent_id or agent_id,
        requested_tool_profile=requested_tool_profile,
        parent_allowed_tools=list((tool_context or {}).get("allowed_tools") or []),
        origin_channel_id=channel_id or None,
        origin_delivery_target=origin_delivery_target,
        context_mode=context_mode,
        notify_on_finish=bool(payload.get("notify_on_finish", True)),
    )
    return {"ok": True, **result}
