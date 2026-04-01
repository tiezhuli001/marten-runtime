from __future__ import annotations

from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


def run_list_system_lessons_tool(
    payload: dict,
    store: SQLiteSelfImproveStore,
) -> dict:
    agent_id = str(payload.get("agent_id", "assistant"))
    items = store.list_active_lessons(agent_id=agent_id)
    return {
        "ok": True,
        "agent_id": agent_id,
        "count": len(items),
        "items": [item.model_dump(mode="json") for item in items],
    }
