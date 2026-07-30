from __future__ import annotations

from marten_runtime.bazi.retrieval_query import (
    build_bazi_retrieval_plan,
    current_bazi_result_from_context,
)
from marten_runtime.bazi_cases.service import BaziCaseError, BaziCaseService, owner_key_from_context
from marten_runtime.tools.builtins.bazi_tool import CURRENT_RESULT_STATE_KEY


def run_bazi_case_tool(
    payload: dict,
    *,
    case_service: BaziCaseService,
    tool_context: dict | None = None,
) -> dict[str, object]:
    action = str(payload.get("action") or "").strip().lower()
    try:
        owner_key = owner_key_from_context(tool_context)
        if action == "save_current":
            current = _current_result(tool_context)
            return case_service.save_current(
                owner_key=owner_key,
                run_id=str((tool_context or {}).get("run_id") or ""),
                session_id=str((tool_context or {}).get("session_id") or ""),
                bazi_result=current,
                question=str(payload.get("question") or ""),
                analysis_summary=str(payload.get("analysis_summary") or ""),
                raw_case_text=str(payload.get("raw_case_text") or ""),
                interpretation=dict(payload.get("interpretation") or {}),
                topic_conclusions=list(payload.get("topic_conclusions") or []),
                predictions=list(payload.get("predictions") or []),
                events=list(payload.get("events") or []),
                reviews=list(payload.get("reviews") or []),
            )
        if action == "import_text":
            return case_service.import_text(
                owner_key=owner_key,
                text=str(payload.get("text") or ""),
                run_id=str((tool_context or {}).get("run_id") or ""),
                session_id=str((tool_context or {}).get("session_id") or ""),
            )
        if action == "get":
            return case_service.get(owner_key=owner_key, case_id=str(payload.get("case_id") or ""))
        if action == "list":
            return case_service.list(
                owner_key=owner_key,
                include_archived=bool(payload.get("include_archived", False)),
            )
        if action == "update_events":
            return case_service.update_events(
                owner_key=owner_key,
                case_id=str(payload.get("case_id") or ""),
                events=list(payload.get("events") or []),
                question=str(payload["question"]) if "question" in payload else None,
                analysis_summary=str(payload["analysis_summary"]) if "analysis_summary" in payload else None,
                predictions=list(payload["predictions"]) if "predictions" in payload else None,
                reviews=list(payload["reviews"]) if "reviews" in payload else None,
            )
        if action == "archive":
            return case_service.archive(owner_key=owner_key, case_id=str(payload.get("case_id") or ""))
        if action == "delete":
            return case_service.delete(owner_key=owner_key, case_id=str(payload.get("case_id") or ""))
        if action == "search":
            current = _current_result(tool_context, required=False)
            supplied = payload.get("current_chart")
            current_chart = current or dict(supplied or {})
            plan = build_bazi_retrieval_plan(
                current_chart,
                user_message=str((tool_context or {}).get("message") or ""),
            )
            result = case_service.search(
                owner_key=owner_key,
                query=plan.case_query if plan is not None else str(payload.get("query") or ""),
                top_k=int(payload.get("top_k") or 3),
                current_chart=current_chart,
                event_category=str(payload.get("event_category") or ""),
            )
            if plan is not None:
                result["query_plan"] = {
                    "strategy": "bazi_chart_case_v1",
                    "facts": list(plan.facts),
                }
            return result
        raise BaziCaseError("BAZI_CASE_ACTION_UNSUPPORTED", "unsupported bazi_case action")
    except BaziCaseError as exc:
        return {
            "ok": False,
            "is_error": True,
            "error_code": exc.code,
            "message": str(exc),
            "retryable": exc.retryable,
            "action": action or None,
        }


def _current_result(tool_context: dict | None, *, required: bool = True) -> dict[str, object]:
    selected = current_bazi_result_from_context(tool_context)
    if selected:
        return selected
    state = (tool_context or {}).get("turn_tool_state")
    current = state.get(CURRENT_RESULT_STATE_KEY) if isinstance(state, dict) else None
    if not required and isinstance(current, dict) and current.get("ok") is True:
        return current
    if required:
        raise BaziCaseError(
            "BAZI_CASE_CURRENT_RUN_REQUIRED",
            "run a Bazi chart with four pillars successfully in this turn first",
        )
    return {}
