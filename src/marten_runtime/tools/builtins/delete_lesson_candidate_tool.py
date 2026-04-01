from __future__ import annotations

from marten_runtime.data_access.adapter import DomainDataAdapter


def run_delete_lesson_candidate_tool(
    payload: dict,
    adapter: DomainDataAdapter,
) -> dict:
    candidate_id = str(payload["candidate_id"])
    deleted = adapter.delete_item("lesson_candidate", item_id=candidate_id)
    if not deleted["ok"]:
        return {
            "ok": False,
            "error": "LESSON_CANDIDATE_NOT_FOUND",
            "candidate_id": candidate_id,
        }
    return deleted
