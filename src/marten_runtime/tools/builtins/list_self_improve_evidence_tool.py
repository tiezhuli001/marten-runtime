from __future__ import annotations

from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


def run_list_self_improve_evidence_tool(
    payload: dict,
    store: SQLiteSelfImproveStore,
) -> dict:
    agent_id = str(payload.get("agent_id", "assistant"))
    limit = int(payload.get("limit", 20))
    failures = store.list_recent_failures(agent_id=agent_id, limit=limit)
    recoveries = store.list_recent_recoveries(agent_id=agent_id, limit=limit)
    return {
        "ok": True,
        "agent_id": agent_id,
        "failure_count": len(failures),
        "recovery_count": len(recoveries),
        "failures": [item.model_dump(mode="json") for item in failures],
        "recoveries": [item.model_dump(mode="json") for item in recoveries],
    }
