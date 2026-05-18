from __future__ import annotations

from marten_runtime.evals.models import (
    EvalCaseObservation,
    EvalCaseResult,
    EvalCaseSpec,
    EvalComponentScore,
)


def build_blocked_result(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
    eval_run_id: str,
) -> EvalCaseResult:
    return EvalCaseResult(
        eval_run_id=eval_run_id,
        case_id=case.case_id,
        family=case.family,
        status="blocked",
        total_score=0.0,
        outcome_score=0.0,
        tool_path_score=0.0,
        efficiency_score=0.0,
        context_score=0.0,
        llm_request_count=observation.llm_request_count,
        tool_calls_count=observation.tool_calls_count,
        duration_ms=observation.duration_ms,
        run_id=observation.run_id,
        trace_id=observation.trace_id,
        langfuse_url=observation.langfuse_url,
        final_text=observation.final_text,
        diagnostics_json=dict(observation.diagnostics_json),
        score_breakdown_json={"blocked_reason": observation.blocked_reason, "components": []},
        blocked_reason=observation.blocked_reason,
    )


def finalize_component_case_result(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
    eval_run_id: str,
    *,
    grader_id: str,
    component_items: list[EvalComponentScore],
    final_text: str,
) -> EvalCaseResult:
    total_score = 0.0
    gate = set(case.gate_components)
    gate_passed = True
    for component in component_items:
        total_score = round(total_score + float(component.score), 4)
        if component.key in gate:
            gate_passed = gate_passed and component.passed

    status = "passed" if gate_passed and observation.error_code is None else "failed"
    if not case.required and status != "passed":
        status = "warning"
    if observation.error_code is not None and status == "passed":
        status = "failed"

    return EvalCaseResult(
        eval_run_id=eval_run_id,
        case_id=case.case_id,
        family=case.family,
        status=status,
        total_score=total_score,
        outcome_score=total_score,
        tool_path_score=0.0,
        efficiency_score=0.0,
        context_score=0.0,
        llm_request_count=observation.llm_request_count,
        tool_calls_count=observation.tool_calls_count,
        duration_ms=observation.duration_ms,
        run_id=observation.run_id,
        trace_id=observation.trace_id,
        langfuse_url=observation.langfuse_url,
        final_text=final_text,
        diagnostics_json=dict(observation.diagnostics_json),
        score_breakdown_json={
            "grader_id": grader_id,
            "case_meta": {
                "description": case.description,
                "tags": list(case.tags),
                "source_path": case.source_path,
            },
            "components": [item.model_dump(mode="json") for item in component_items],
            "gate": {"passed": gate_passed, "gate_components": list(case.gate_components)},
        },
    )


def normalize_anchor_groups(value: object) -> list[list[str]]:
    groups: list[list[str]] = []
    for raw_group in list(value or []):
        if isinstance(raw_group, (list, tuple)):
            tokens = [str(item).strip() for item in raw_group if str(item).strip()]
        else:
            token = str(raw_group).strip()
            tokens = [token] if token else []
        if tokens:
            groups.append(tokens)
    return groups


def evaluate_text_evidence(
    *,
    final_text: str,
    evidence_texts: list[str],
    required: list[str] | None = None,
    forbidden: list[str] | None = None,
    anchor_groups: list[list[str]] | None = None,
) -> dict[str, object]:
    required = list(required or [])
    forbidden = list(forbidden or [])
    anchor_groups = list(anchor_groups or [])
    combined_text = "\n".join(item for item in evidence_texts if item)
    required_final_hits = {token: token in final_text for token in required}
    required_combined_hits = {token: token in combined_text for token in required}
    group_final_hits = [_group_hit(final_text, group) for group in anchor_groups]
    group_combined_hits = [_group_hit(combined_text, group) for group in anchor_groups]
    content_hit = (
        (bool(required) and all(required_combined_hits.values()))
        or (bool(anchor_groups) and all(group_combined_hits))
        or (not required and not anchor_groups)
    )
    surface_hit = (
        any(required_final_hits.values())
        or any(group_final_hits)
        or (not required and not anchor_groups)
    )
    forbidden_hits = {token: token in combined_text for token in forbidden}
    forbidden_ok = not any(forbidden_hits.values())
    return {
        "passed": bool(content_hit and surface_hit and forbidden_ok),
        "required_final_hits": required_final_hits,
        "required_combined_hits": required_combined_hits,
        "group_final_hits": group_final_hits,
        "group_combined_hits": group_combined_hits,
        "forbidden_hits": forbidden_hits,
    }


def _group_hit(text: str, group: list[str]) -> bool:
    return any(token in text for token in group)
