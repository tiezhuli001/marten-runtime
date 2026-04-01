from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.tools.builtins.delete_lesson_candidate_tool import run_delete_lesson_candidate_tool
from marten_runtime.tools.builtins.get_lesson_candidate_detail_tool import run_get_lesson_candidate_detail_tool
from marten_runtime.tools.builtins.get_self_improve_summary_tool import run_get_self_improve_summary_tool
from marten_runtime.tools.builtins.list_lesson_candidates_tool import run_list_lesson_candidates_tool
from marten_runtime.tools.builtins.list_self_improve_evidence_tool import run_list_self_improve_evidence_tool
from marten_runtime.tools.builtins.list_system_lessons_tool import run_list_system_lessons_tool
from marten_runtime.tools.builtins.save_lesson_candidate_tool import run_save_lesson_candidate_tool


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
