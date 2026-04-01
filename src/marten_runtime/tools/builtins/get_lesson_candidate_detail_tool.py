from __future__ import annotations

from marten_runtime.data_access.adapter import DomainDataAdapter


def run_get_lesson_candidate_detail_tool(
    payload: dict,
    adapter: DomainDataAdapter,
) -> dict:
    candidate_id = str(payload["candidate_id"])
    item = adapter.get_item("lesson_candidate", item_id=candidate_id)
    return {"ok": True, "candidate": item}
