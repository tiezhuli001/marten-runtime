from __future__ import annotations

from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


def run_get_self_improve_summary_tool(
    payload: dict,
    store: SQLiteSelfImproveStore,
) -> dict:
    agent_id = str(payload.get("agent_id", "assistant"))
    pending = store.list_candidates(agent_id=agent_id, limit=100, status="pending")
    accepted = store.list_candidates(agent_id=agent_id, limit=100, status="accepted")
    rejected = store.list_candidates(agent_id=agent_id, limit=100, status="rejected")
    lessons = store.list_active_lessons(agent_id=agent_id)
    return {
        "ok": True,
        "agent_id": agent_id,
        "candidate_counts": {
            "pending": len(pending),
            "accepted": len(accepted),
            "rejected": len(rejected),
        },
        "active_lessons_count": len(lessons),
        "latest_active_lesson": lessons[0].lesson_text if lessons else None,
    }
