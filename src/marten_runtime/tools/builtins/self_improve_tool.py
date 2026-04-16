from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.self_improve.models import LessonCandidate
from marten_runtime.self_improve.promotion import promote_skill_candidate, _validate_skill_slug
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


def _require_skill_candidate_status(current, *, allowed_statuses: set[str], action: str) -> None:  # noqa: ANN001
    if current.status not in allowed_statuses:
        allowed = ", ".join(sorted(allowed_statuses))
        raise ValueError(
            f"skill candidate must be in status [{allowed}] before {action}"
        )


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
    agent_id = str(payload.get("agent_id", "main"))
    pending = store.list_candidates(agent_id=agent_id, limit=100, status="pending")
    accepted = store.list_candidates(agent_id=agent_id, limit=100, status="accepted")
    rejected = store.list_candidates(agent_id=agent_id, limit=100, status="rejected")
    lessons = store.list_active_lessons(agent_id=agent_id)
    skill_candidates = store.list_skill_candidates(
        agent_id=agent_id, limit=100, status="pending"
    )
    return {
        "ok": True,
        "agent_id": agent_id,
        "candidate_counts": {
            "pending": len(pending),
            "accepted": len(accepted),
            "rejected": len(rejected),
        },
        "skill_candidate_counts": {
            "pending": len(skill_candidates),
        },
        "active_lessons_count": len(lessons),
        "latest_active_lesson": lessons[0].lesson_text if lessons else None,
        "latest_skill_candidate": skill_candidates[0].slug if skill_candidates else None,
    }


def run_list_lesson_candidates_tool(
    payload: dict,
    adapter: DomainDataAdapter,
) -> dict:
    agent_id = str(payload.get("agent_id", "main"))
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
    agent_id = str(payload.get("agent_id", "main"))
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
    agent_id = str(payload.get("agent_id", "main"))
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
    *,
    repo_root=None,
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
    elif action == "list_skill_candidates":
        agent_id = str(request.get("agent_id", "main"))
        status = request.get("status")
        items = store.list_skill_candidates(
            agent_id=agent_id,
            limit=int(request.get("limit", 20)),
            status=str(status) if status is not None else None,
        )
        result = {
            "ok": True,
            "agent_id": agent_id,
            "count": len(items),
            "items": [item.model_dump(mode="json") for item in items],
        }
    elif action == "skill_candidate_detail":
        candidate_id = str(request["candidate_id"])
        result = {"ok": True, "candidate": store.get_skill_candidate(candidate_id).model_dump(mode="json")}
    elif action == "accept_skill_candidate":
        candidate_id = str(request["candidate_id"])
        current = store.get_skill_candidate(candidate_id)
        _require_skill_candidate_status(
            current,
            allowed_statuses={"pending"},
            action="accept",
        )
        updated = store.update_skill_candidate_status(candidate_id, status="accepted")
        result = {"ok": True, "candidate": updated.model_dump(mode="json")}
    elif action == "edit_skill_candidate":
        candidate_id = str(request["candidate_id"])
        current = store.get_skill_candidate(candidate_id)
        if current.status != "pending":
            raise ValueError("only pending skill candidates may be edited")
        slug = (
            _validate_skill_slug(str(request["slug"]))
            if "slug" in request and request.get("slug") is not None
            else current.slug
        )
        semantic_fingerprint = slug
        existing = store.latest_skill_candidate_by_semantic_fingerprint(
            agent_id=current.agent_id,
            semantic_fingerprint=semantic_fingerprint,
            status="pending",
        )
        if existing is not None and existing.candidate_id != current.candidate_id:
            raise ValueError("pending skill candidate with the same slug already exists")
        updated = store.update_skill_candidate(
            candidate_id,
            title=str(request["title"]) if "title" in request else None,
            slug=slug,
            summary=str(request["summary"]) if "summary" in request else None,
            trigger_conditions=(
                [str(item) for item in request.get("trigger_conditions", [])]
                if "trigger_conditions" in request
                else None
            ),
            body_markdown=(
                str(request["body_markdown"]) if "body_markdown" in request else None
            ),
            rationale=str(request["rationale"]) if "rationale" in request else None,
            semantic_fingerprint=semantic_fingerprint,
        )
        result = {"ok": True, "candidate": updated.model_dump(mode="json")}
    elif action == "reject_skill_candidate":
        candidate_id = str(request["candidate_id"])
        current = store.get_skill_candidate(candidate_id)
        _require_skill_candidate_status(
            current,
            allowed_statuses={"pending"},
            action="reject",
        )
        updated = store.update_skill_candidate_status(candidate_id, status="rejected")
        result = {"ok": True, "candidate": updated.model_dump(mode="json")}
    elif action == "promote_skill_candidate":
        if repo_root is None:
            raise ValueError("repo_root is required for skill promotion")
        candidate_id = str(request["candidate_id"])
        result = promote_skill_candidate(
            store=store,
            candidate_id=candidate_id,
            repo_root=repo_root,
        )
    else:
        raise ValueError("unsupported self_improve action")
    return {"action": action, **result}
