from __future__ import annotations

from marten_runtime.evals.family_graders.common import build_blocked_result, finalize_component_case_result
from marten_runtime.evals.models import EvalCaseObservation, EvalCaseResult, EvalCaseSpec, EvalComponentScore

_COMPONENT_LABELS = {
    "keyword_recall": "关键词召回",
    "semantic_recall": "语义召回",
    "rerank_improvement": "重排提升",
    "namespace_isolation": "Namespace 隔离",
    "config_mismatch": "Config mismatch 诊断",
    "large_file_progress": "大文件进度",
    "delete_recall": "删除后不召回",
}


def grade_knowledge_retrieval_case_result(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
    eval_run_id: str,
) -> EvalCaseResult:
    if observation.blocked_reason:
        return build_blocked_result(case, observation, eval_run_id)
    grader_case = dict(case.grader_case)
    search_result = _latest_knowledge_result(observation, "search")
    components = [
        _grade_component(key, weight, grader_case, observation, search_result)
        for key, weight in case.component_weights.items()
    ]
    return finalize_component_case_result(
        case,
        observation,
        eval_run_id,
        grader_id="knowledge_retrieval",
        component_items=components,
        final_text=str(observation.final_text or ""),
    )


def _grade_component(
    key: str,
    weight: int,
    grader_case: dict[str, object],
    observation: EvalCaseObservation,
    search_result: dict[str, object],
) -> EvalComponentScore:
    if key in {"keyword_recall", "semantic_recall", "delete_recall"}:
        passed = _required_chunks_present(search_result, grader_case)
        details = {"required_chunks": list(grader_case.get("required_chunks") or []), "result_chunks": _result_chunk_ids(search_result), "result_evidence": _result_evidence(search_result)}
    elif key == "namespace_isolation":
        expected = str(grader_case.get("namespace") or "").strip()
        namespaces = _knowledge_namespaces(observation)
        passed = bool(expected) and namespaces == {expected}
        details = {"expected_namespace": expected, "actual_namespaces": sorted(namespaces)}
    elif key == "config_mismatch":
        expected_status = str(grader_case.get("expected_vector_status") or "config_mismatch")
        diagnostic = str(search_result.get("degraded_reason") or "")
        required = [str(item) for item in list(grader_case.get("required_diagnostic_contains") or [])]
        passed = str(search_result.get("vector_status") or "") == expected_status and all(token in diagnostic for token in required)
        details = {"expected_vector_status": expected_status, "degraded_reason": diagnostic, "required": required}
    elif key == "large_file_progress":
        ingest_result = _latest_knowledge_result(observation, "ingest_file")
        status_results = _knowledge_results(observation, "ingest_status")
        terminal_status = str((status_results[-1] if status_results else {}).get("status") or "")
        max_total = max([int(item.get("chunks_total") or 0) for item in status_results] or [0])
        max_embedded = max([int(item.get("chunks_embedded") or 0) for item in status_results] or [0])
        max_percent = max([float(item.get("percent") or 0.0) for item in status_results] or [0.0])
        seen_statuses = {str(item.get("status") or "") for item in status_results}
        passed = (
            bool(ingest_result.get("job_id"))
            and terminal_status == "completed"
            and max_total > 0
            and max_embedded == max_total
            and max_percent == 100.0
            and bool(seen_statuses & {"embedding", "completed"})
        )
        details = {"ingest_file": ingest_result, "ingest_statuses": status_results}
    elif key == "rerank_improvement":
        required_first = str(grader_case.get("expected_first_chunk") or "")
        evidence = _result_evidence(search_result)
        top_text = str((list(search_result.get("results") or [{}])[0] if search_result.get("results") else {}).get("text") or "")
        chunks = _result_chunk_ids(search_result)
        passed = bool(required_first) and (bool(chunks) and chunks[0] == required_first or required_first in top_text)
        details = {"expected_first_chunk": required_first, "result_chunks": chunks, "result_evidence": evidence}
    else:
        passed = False
        details = {"unknown_component": key}
    ratio = 1.0 if passed else 0.0
    return EvalComponentScore(
        key=key,
        label=_COMPONENT_LABELS.get(key, key),
        weight=weight,
        ratio=ratio,
        score=round(weight * ratio, 4),
        passed=passed,
        details=details,
    )


def _latest_knowledge_result(observation: EvalCaseObservation, action: str) -> dict[str, object]:
    results = _knowledge_results(observation, action)
    return results[-1] if results else {}


def _knowledge_results(observation: EvalCaseObservation, action: str) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for call in observation.tool_calls:
        if str(call.get("tool_name") or "") != "knowledge":
            continue
        payload = call.get("tool_payload") if isinstance(call.get("tool_payload"), dict) else {}
        if str(payload.get("action") or "") == action:
            results.append(dict(call.get("tool_result") or {}) if isinstance(call.get("tool_result"), dict) else {})
    return results


def _knowledge_namespaces(observation: EvalCaseObservation) -> set[str]:
    namespaces: set[str] = set()
    for call in observation.tool_calls:
        if str(call.get("tool_name") or "") != "knowledge":
            continue
        payload = call.get("tool_payload") if isinstance(call.get("tool_payload"), dict) else {}
        namespace = str(payload.get("namespace") or "").strip()
        if namespace:
            namespaces.add(namespace)
    return namespaces


def _required_chunks_present(search_result: dict[str, object], grader_case: dict[str, object]) -> bool:
    required = {str(item) for item in list(grader_case.get("required_chunks") or [])}
    evidence_text = "\n".join(_result_evidence(search_result))
    return bool(required) and all(token in evidence_text for token in required)


def _result_chunk_ids(search_result: dict[str, object]) -> list[str]:
    return [str(item.get("chunk_id") or "") for item in list(search_result.get("results") or []) if isinstance(item, dict)]


def _result_evidence(search_result: dict[str, object]) -> list[str]:
    evidence: list[str] = []
    for item in list(search_result.get("results") or []):
        if not isinstance(item, dict):
            continue
        evidence.append(str(item.get("chunk_id") or ""))
        evidence.append(str(item.get("text") or ""))
    return evidence
