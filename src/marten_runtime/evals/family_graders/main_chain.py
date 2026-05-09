from __future__ import annotations

from marten_runtime.evals.family_graders.common import build_blocked_result
from marten_runtime.evals.models import (
    EvalCaseObservation,
    EvalCaseResult,
    EvalCaseSpec,
    EvalComponentScore,
)

_LEGACY_COMPONENT_LABELS = {
    "outcome": "结果",
    "tool_path": "工具路径",
    "efficiency": "效率",
    "context": "上下文",
}


def grade_main_chain_case_result(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
    eval_run_id: str,
) -> EvalCaseResult:
    if observation.blocked_reason:
        return build_blocked_result(case, observation, eval_run_id)

    outcome_ratio, outcome_breakdown = _grade_outcome(case, observation)
    tool_ratio, tool_breakdown = _grade_tool_path(case, observation)
    efficiency_ratio, efficiency_breakdown = _grade_efficiency(case, observation)
    context_ratio, context_breakdown = _grade_context(case, observation)

    weights = case.weights
    if weights is None:
        raise ValueError("main chain cases require legacy weights")

    outcome_score = _round(weights.outcome * outcome_ratio)
    tool_path_score = _round(weights.tool_path * tool_ratio)
    efficiency_score = _round(weights.efficiency * efficiency_ratio)
    context_score = _round(weights.context * context_ratio)
    total_score = _round(
        outcome_score + tool_path_score + efficiency_score + context_score
    )

    gate_passed = bool(outcome_score > 0.0) and bool(tool_breakdown["required_calls_ok"])
    if case.required:
        status = "passed" if gate_passed and observation.error_code is None else "failed"
    else:
        status = "passed" if gate_passed else "warning"

    components = [
        EvalComponentScore(
            key="outcome",
            label=_LEGACY_COMPONENT_LABELS["outcome"],
            weight=weights.outcome,
            ratio=outcome_ratio,
            score=outcome_score,
            passed=outcome_score > 0.0,
            details=outcome_breakdown,
        ).model_dump(mode="json"),
        EvalComponentScore(
            key="tool_path",
            label=_LEGACY_COMPONENT_LABELS["tool_path"],
            weight=weights.tool_path,
            ratio=tool_ratio,
            score=tool_path_score,
            passed=bool(tool_breakdown["required_calls_ok"]),
            details=tool_breakdown,
        ).model_dump(mode="json"),
        EvalComponentScore(
            key="efficiency",
            label=_LEGACY_COMPONENT_LABELS["efficiency"],
            weight=weights.efficiency,
            ratio=efficiency_ratio,
            score=efficiency_score,
            passed=efficiency_ratio >= 1.0,
            details=efficiency_breakdown,
        ).model_dump(mode="json"),
        EvalComponentScore(
            key="context",
            label=_LEGACY_COMPONENT_LABELS["context"],
            weight=weights.context,
            ratio=context_ratio,
            score=context_score,
            passed=context_ratio >= 1.0,
            details=context_breakdown,
        ).model_dump(mode="json"),
    ]

    return EvalCaseResult(
        eval_run_id=eval_run_id,
        case_id=case.case_id,
        family=case.family,
        status=status,
        total_score=total_score,
        outcome_score=outcome_score,
        tool_path_score=tool_path_score,
        efficiency_score=efficiency_score,
        context_score=context_score,
        llm_request_count=observation.llm_request_count,
        tool_calls_count=observation.tool_calls_count,
        duration_ms=observation.duration_ms,
        run_id=observation.run_id,
        trace_id=observation.trace_id,
        langfuse_url=observation.langfuse_url,
        final_text=observation.final_text,
        diagnostics_json=dict(observation.diagnostics_json),
        score_breakdown_json={
            "components": components,
            "outcome": outcome_breakdown,
            "tool_path": tool_breakdown,
            "efficiency": efficiency_breakdown,
            "context": context_breakdown,
            "gate": {
                "passed": gate_passed,
                "required": case.required,
                "error_code": observation.error_code,
            },
        },
    )


def _grade_outcome(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
) -> tuple[float, dict[str, object]]:
    final_text = str(observation.final_text or "")
    checks: list[bool] = []
    contains_all = []
    for item in case.expectations.final_text.contains_all:
        matched = item in final_text
        contains_all.append({"value": item, "matched": matched})
        checks.append(matched)
    contains_any_expected = list(case.expectations.final_text.contains_any)
    contains_any_matched = (
        True
        if not contains_any_expected
        else any(item in final_text for item in contains_any_expected)
    )
    if contains_any_expected:
        checks.append(contains_any_matched)
    forbid_all = []
    for item in case.expectations.final_text.forbid_all:
        matched = item not in final_text
        forbid_all.append({"value": item, "matched": matched})
        checks.append(matched)
    ratio = _ratio(checks)
    return ratio, {
        "contains_all": contains_all,
        "contains_any": {
            "expected": contains_any_expected,
            "matched": contains_any_matched,
        },
        "forbid_all": forbid_all,
        "final_text": final_text,
        "ratio": ratio,
    }


def _grade_tool_path(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
) -> tuple[float, dict[str, object]]:
    tool_names = [str(item.get("tool_name") or "").strip() for item in observation.tool_calls]
    checks: list[bool] = []
    required_results = []
    required_calls_ok = True
    for rule in case.expectations.tool_path.required_calls:
        count = sum(1 for name in tool_names if name == rule.tool_name)
        matched = rule.min_calls <= count <= rule.max_calls
        required_results.append(
            {
                "tool_name": rule.tool_name,
                "count": count,
                "min_calls": rule.min_calls,
                "max_calls": rule.max_calls,
                "matched": matched,
            }
        )
        checks.append(matched)
        required_calls_ok = required_calls_ok and matched
    forbidden_results = []
    for rule in case.expectations.tool_path.forbidden_calls:
        matched = all(name != rule for name in tool_names)
        forbidden_results.append({"tool_name": rule, "matched": matched})
        checks.append(matched)
    ratio = 0.0 if not required_calls_ok else _ratio(checks)
    return ratio, {
        "tool_calls": tool_names,
        "required_calls": required_results,
        "forbidden_calls": forbidden_results,
        "required_calls_ok": required_calls_ok,
        "ratio": ratio,
    }


def _grade_efficiency(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
) -> tuple[float, dict[str, object]]:
    checks: list[bool] = []
    breakdown: dict[str, object] = {
        "llm_request_count": observation.llm_request_count,
        "tool_calls_count": observation.tool_calls_count,
    }
    max_llm_requests = case.expectations.efficiency.max_llm_requests
    if max_llm_requests is not None:
        matched = observation.llm_request_count <= max_llm_requests
        breakdown["max_llm_requests"] = max_llm_requests
        breakdown["llm_requests_ok"] = matched
        checks.append(matched)
    max_tool_calls = case.expectations.efficiency.max_tool_calls
    if max_tool_calls is not None:
        matched = observation.tool_calls_count <= max_tool_calls
        breakdown["max_tool_calls"] = max_tool_calls
        breakdown["tool_calls_ok"] = matched
        checks.append(matched)
    ratio = _ratio(checks)
    breakdown["ratio"] = ratio
    return ratio, breakdown


def _grade_context(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
) -> tuple[float, dict[str, object]]:
    diagnostics = dict(observation.diagnostics_json)
    compaction = diagnostics.get("compaction") if isinstance(diagnostics.get("compaction"), dict) else {}
    checks: list[bool] = []
    breakdown: dict[str, object] = {
        "diagnostics": diagnostics,
    }
    expected_compaction = case.expectations.context.expect_compaction
    if expected_compaction is not None:
        decision = str(compaction.get("decision") or "").strip().lower()
        actual = bool(compaction.get("used_compacted_context", False)) or decision in {
            "proactive",
            "reactive",
        }
        matched = actual is expected_compaction
        breakdown["expect_compaction"] = expected_compaction
        breakdown["actual_compaction"] = actual
        breakdown["compaction_decision"] = decision
        breakdown["compaction_ok"] = matched
        checks.append(matched)
    expected_provider = case.expectations.diagnostics.expect_provider_ref
    if expected_provider is not None:
        actual = str(diagnostics.get("provider_ref") or "")
        matched = actual == expected_provider
        breakdown["expect_provider_ref"] = expected_provider
        breakdown["actual_provider_ref"] = actual
        breakdown["provider_ref_ok"] = matched
        checks.append(matched)
    expected_final_provider = case.expectations.diagnostics.expect_final_provider_ref
    if expected_final_provider is not None:
        actual = str(diagnostics.get("final_provider_ref") or "")
        matched = actual == expected_final_provider
        breakdown["expect_final_provider_ref"] = expected_final_provider
        breakdown["actual_final_provider_ref"] = actual
        breakdown["final_provider_ref_ok"] = matched
        checks.append(matched)
    expected_tail_turns = case.expectations.context.expect_preserved_tail_user_turns
    if expected_tail_turns is not None:
        actual = diagnostics.get("preserved_tail_user_turns")
        matched = actual == expected_tail_turns
        breakdown["expect_preserved_tail_user_turns"] = expected_tail_turns
        breakdown["actual_preserved_tail_user_turns"] = actual
        breakdown["preserved_tail_user_turns_ok"] = matched
        checks.append(matched)
    ratio = _ratio(checks)
    breakdown["ratio"] = ratio
    return ratio, breakdown


def _ratio(checks: list[bool]) -> float:
    if not checks:
        return 1.0
    return sum(1 for item in checks if item) / len(checks)


def _round(value: float) -> float:
    return round(float(value), 4)
