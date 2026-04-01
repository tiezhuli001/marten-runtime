from __future__ import annotations

from marten_runtime.data_access.adapter import DomainDataAdapter


def run_list_lesson_candidates_tool(
    payload: dict,
    adapter: DomainDataAdapter,
) -> dict:
    agent_id = str(payload.get("agent_id", "assistant"))
    status = payload.get("status")
    filters = {"agent_id": agent_id}
    if status is not None:
        filters["status"] = str(status)
    items = adapter.list_items(
        "lesson_candidate",
        filters=filters,
        limit=int(payload.get("limit", 20)),
    )
    return {
        "ok": True,
        "agent_id": agent_id,
        "count": len(items),
        "items": items,
    }
