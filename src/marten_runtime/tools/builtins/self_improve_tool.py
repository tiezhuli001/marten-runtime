from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.self_improve.models import LessonCandidate
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


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


def run_get_lesson_candidate_detail_tool(
    payload: dict,
    adapter: DomainDataAdapter,
) -> dict:
    candidate_id = str(payload["candidate_id"])
    item = adapter.get_item("lesson_candidate", item_id=candidate_id)
    return {"ok": True, "candidate": item}


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


def run_save_lesson_candidate_tool(
    payload: dict,
    store: SQLiteSelfImproveStore,
) -> dict:
    candidate = LessonCandidate(
        candidate_id=str(payload["candidate_id"]),
        agent_id=str(payload["agent_id"]),
        source_fingerprints=[
            str(item) for item in payload.get("source_fingerprints", [])
        ],
        candidate_text=str(payload["candidate_text"]),
        rationale=str(payload["rationale"]),
        status=str(payload.get("status", "pending")),
        score=float(payload.get("score", 0.0)),
    )
    store.save_candidate(candidate)
    return {"ok": True, "candidate": candidate.model_dump(mode="json")}


def run_self_improve_tool(
    payload: dict,
    adapter: DomainDataAdapter,
    store: SQLiteSelfImproveStore,
) -> dict:
    action = str(payload.get("action", "")).strip().lower()
    request = {key: value for key, value in payload.items() if key != "action"}
    if action == "list_candidates":
        result = run_list_lesson_candidates_tool(request, adapter)
    elif action == "candidate_detail":
        result = run_get_lesson_candidate_detail_tool(request, adapter)
    elif action == "delete_candidate":
        result = run_delete_lesson_candidate_tool(request, adapter)
    elif action == "summary":
        result = run_get_self_improve_summary_tool(request, store)
    elif action == "list_evidence":
        result = run_list_self_improve_evidence_tool(request, store)
    elif action == "list_system_lessons":
        result = run_list_system_lessons_tool(request, store)
    elif action == "save_candidate":
        result = run_save_lesson_candidate_tool(request, store)
    else:
        raise ValueError("unsupported self_improve action")
    return {"action": action, **result}
