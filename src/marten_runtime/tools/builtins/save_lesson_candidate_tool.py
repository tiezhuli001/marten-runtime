from __future__ import annotations

from marten_runtime.self_improve.models import LessonCandidate
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


def run_save_lesson_candidate_tool(
    payload: dict,
    store: SQLiteSelfImproveStore,
) -> dict:
    candidate = LessonCandidate(
        candidate_id=str(payload["candidate_id"]),
        agent_id=str(payload["agent_id"]),
        source_fingerprints=[str(item) for item in payload.get("source_fingerprints", [])],
        candidate_text=str(payload["candidate_text"]),
        rationale=str(payload["rationale"]),
        status=str(payload.get("status", "pending")),
        score=float(payload.get("score", 0.0)),
    )
    store.save_candidate(candidate)
    return {"ok": True, "candidate": candidate.model_dump(mode="json")}
