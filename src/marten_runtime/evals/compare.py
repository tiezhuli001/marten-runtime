from __future__ import annotations

import math

from marten_runtime.evals.models import (
    EvalCaseSpec,
    EvalCaseComparison,
    EvalCaseResult,
    EvalComponentComparison,
    EvalComponentSummary,
    EvalRunComparison,
    EvalRunStabilitySummary,
    EvalRunSummary,
    EvalStabilityCaseSummary,
    EvalStabilityComponentSummary,
    EvalStabilityStats,
)


def compare_eval_runs(
    current_summary: EvalRunSummary,
    current_cases: list[EvalCaseResult],
    baseline_summary: EvalRunSummary,
    baseline_cases: list[EvalCaseResult],
    *,
    baseline_source: str,
) -> EvalRunComparison:
    current_index = {item.case_id: item for item in current_cases}
    baseline_index = {item.case_id: item for item in baseline_cases}
    comparisons: list[EvalCaseComparison] = []
    regressions: list[EvalCaseComparison] = []
    improvements: list[EvalCaseComparison] = []
    for case_id in sorted(set(current_index) | set(baseline_index)):
        current = current_index.get(case_id)
        baseline = baseline_index.get(case_id)
        current_score = current.total_score if current is not None else None
        baseline_score = baseline.total_score if baseline is not None else None
        delta = round((current_score or 0.0) - (baseline_score or 0.0), 4)
        current_status = current.status if current is not None else None
        baseline_status = baseline.status if baseline is not None else None
        comparison = EvalCaseComparison(
            case_id=case_id,
            current_status=current_status,
            baseline_status=baseline_status,
            current_total_score=current_score,
            baseline_total_score=baseline_score,
            total_score_delta=delta,
            change_kind=_change_kind(current_status, baseline_status, delta),
            components=_compare_case_components(current, baseline),
        )
        comparisons.append(comparison)
        if comparison.change_kind in {"regression", "removed_case"}:
            regressions.append(comparison)
        if comparison.change_kind in {"improvement", "new_case"}:
            improvements.append(comparison)
    regressions.sort(key=lambda item: (item.total_score_delta, item.case_id))
    improvements.sort(key=lambda item: (-item.total_score_delta, item.case_id))
    return EvalRunComparison(
        baseline_eval_run_id=baseline_summary.eval_run_id,
        baseline_source=baseline_source,
        total_score_delta=round(current_summary.total_score - baseline_summary.total_score, 4),
        pass_rate_delta=round(current_summary.pass_rate - baseline_summary.pass_rate, 4),
        token_total_delta=_delta_or_none(_sum_case_tokens(current_cases), _sum_case_tokens(baseline_cases)),
        tool_calls_delta=round(_sum_tool_calls(current_cases) - _sum_tool_calls(baseline_cases), 4),
        llm_requests_delta=round(_sum_llm_requests(current_cases) - _sum_llm_requests(baseline_cases), 4),
        regressions=regressions,
        improvements=improvements,
        cases=comparisons,
        component_summary=_build_component_summary(current_cases, baseline_cases),
    )


def resolve_compare_baseline(
    store,
    *,
    suite_id: str,
    baseline_name: str | None,
    baseline_run_id: str | None,
) -> tuple[str | None, str | None]:
    if baseline_run_id:
        return baseline_run_id, "explicit_run"
    if baseline_name:
        resolved = store.resolve_baseline(suite_id, baseline_name)
        if resolved is not None:
            source = "latest_passed" if baseline_name == "latest_passed" else f"named:{baseline_name}"
            return resolved, source
        source = "latest_passed" if baseline_name == "latest_passed" else f"named:{baseline_name}"
        return None, source
    resolved = store.resolve_baseline(suite_id, "latest_passed")
    if resolved is not None:
        return resolved, "latest_passed"
    return None, None


def build_eval_run_stability_summary(
    *,
    suite_id: str,
    profile_name: str,
    eval_mode: str,
    run_summaries: list[EvalRunSummary],
    case_results_by_run_id: dict[str, list[EvalCaseResult]],
    case_specs: list[EvalCaseSpec] | None = None,
    window_size: int = 5,
) -> EvalRunStabilitySummary:
    case_spec_index = {item.case_id: item for item in list(case_specs or [])}
    ordered_runs = [item for item in run_summaries if item.eval_run_id in case_results_by_run_id]
    total_scores = [item.total_score for item in ordered_runs]
    pass_rates = [item.pass_rate for item in ordered_runs]
    token_totals = []
    failover_hits = 0
    case_buckets: dict[str, list[EvalCaseResult]] = {}
    component_scores_by_run: dict[str, list[float]] = {}
    component_labels: dict[str, str] = {}
    for summary in ordered_runs:
        run_cases = list(case_results_by_run_id.get(summary.eval_run_id) or [])
        run_token_total = 0.0
        run_has_tokens = False
        run_case_failovers = 0
        for result in run_cases:
            case_buckets.setdefault(result.case_id, []).append(result)
            case_token_total = _extract_total_tokens_from_result(result)
            if case_token_total is not None:
                run_has_tokens = True
                run_token_total += case_token_total
            if _result_used_failover(result):
                run_case_failovers += 1
                failover_hits += 1
            for component in _result_components(result).values():
                key = str(component.get("key") or "")
                score = _as_float(component.get("score"))
                if not key or score is None:
                    continue
                component_scores_by_run.setdefault(f"{summary.eval_run_id}:{key}", []).append(score)
                component_labels.setdefault(key, str(component.get("label") or key))
        if run_has_tokens:
            token_totals.append(run_token_total)
    case_summaries = [
        _build_case_stability_summary(case_id, results, case_spec_index.get(case_id))
        for case_id, results in case_buckets.items()
    ]
    case_summaries.sort(key=lambda item: (not item.unstable, -(item.score.range or 0.0), item.case_id))

    suite_component_scores: dict[str, list[float]] = {}
    for compound_key, scores in component_scores_by_run.items():
        _, key = compound_key.split(":", 1)
        if scores:
            suite_component_scores.setdefault(key, []).append(round(sum(scores) / len(scores), 4))
    component_summaries = [
        EvalStabilityComponentSummary(
            key=key,
            label=component_labels.get(key, key),
            score=_build_stats(scores),
            unstable=bool((_build_stats(scores).range or 0.0) > 0.0),
        )
        for key, scores in sorted(suite_component_scores.items())
    ]
    return EvalRunStabilitySummary(
        suite_id=suite_id,
        profile_name=profile_name,
        eval_mode=eval_mode,
        window_size=window_size,
        sample_size=len(ordered_runs),
        history_eval_run_ids=[item.eval_run_id for item in ordered_runs],
        total_score=_build_stats(total_scores),
        pass_rate=_build_stats(pass_rates),
        token_total=_build_stats(token_totals),
        failover_rate=round(
            failover_hits / max(1, sum(len(case_results_by_run_id.get(item.eval_run_id) or []) for item in ordered_runs)),
            4,
        ),
        unstable_case_count=sum(1 for item in case_summaries if item.unstable),
        unstable_component_count=sum(1 for item in component_summaries if item.unstable),
        cases=case_summaries,
        components=component_summaries,
    )


def _sum_case_tokens(cases: list[EvalCaseResult]) -> float | None:
    values = [_extract_total_tokens_from_result(item) for item in cases]
    numeric = [float(item) for item in values if item is not None]
    if not numeric:
        return None
    return round(sum(numeric), 4)


def _sum_tool_calls(cases: list[EvalCaseResult]) -> float:
    return float(sum(int(item.tool_calls_count or 0) for item in cases))


def _sum_llm_requests(cases: list[EvalCaseResult]) -> float:
    return float(sum(int(item.llm_request_count or 0) for item in cases))


def _delta_or_none(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None:
        return None
    return round(float(current) - float(baseline), 4)


def _change_kind(
    current_status: str | None,
    baseline_status: str | None,
    total_score_delta: float,
) -> str:
    if baseline_status is None:
        return "new_case"
    if current_status is None:
        return "removed_case"
    if total_score_delta < 0 or (baseline_status == "passed" and current_status != "passed"):
        return "regression"
    if total_score_delta > 0 or (baseline_status != "passed" and current_status == "passed"):
        return "improvement"
    return "unchanged"


def _result_components(result: EvalCaseResult | None) -> dict[str, dict[str, object]]:
    if result is None:
        return {}
    raw_components = result.score_breakdown_json.get("components")
    if isinstance(raw_components, list) and raw_components:
        return {
            str(item.get("key")): item
            for item in raw_components
            if isinstance(item, dict) and item.get("key") is not None
        }
    return {
        "outcome": {
            "key": "outcome",
            "label": "结果",
            "score": result.outcome_score,
            "passed": result.outcome_score > 0.0,
        },
        "tool_path": {
            "key": "tool_path",
            "label": "工具路径",
            "score": result.tool_path_score,
            "passed": result.tool_path_score > 0.0,
        },
        "efficiency": {
            "key": "efficiency",
            "label": "效率",
            "score": result.efficiency_score,
            "passed": result.efficiency_score > 0.0,
        },
        "context": {
            "key": "context",
            "label": "上下文",
            "score": result.context_score,
            "passed": result.context_score > 0.0,
        },
    }


def _compare_case_components(
    current: EvalCaseResult | None,
    baseline: EvalCaseResult | None,
) -> list[EvalComponentComparison]:
    current_components = _result_components(current)
    baseline_components = _result_components(baseline)
    comparisons: list[EvalComponentComparison] = []
    for key in sorted(set(current_components) | set(baseline_components)):
        current_item = current_components.get(key) or {}
        baseline_item = baseline_components.get(key) or {}
        current_score = _as_float(current_item.get("score"))
        baseline_score = _as_float(baseline_item.get("score"))
        comparisons.append(
            EvalComponentComparison(
                key=key,
                label=str(current_item.get("label") or baseline_item.get("label") or key),
                current_score=current_score,
                baseline_score=baseline_score,
                delta=round((current_score or 0.0) - (baseline_score or 0.0), 4),
                current_passed=_as_bool(current_item.get("passed")),
                baseline_passed=_as_bool(baseline_item.get("passed")),
            )
        )
    return comparisons


def _build_component_summary(
    current_cases: list[EvalCaseResult],
    baseline_cases: list[EvalCaseResult],
) -> list[EvalComponentSummary]:
    current_index = {item.case_id: item for item in current_cases}
    baseline_index = {item.case_id: item for item in baseline_cases}
    bucket: dict[str, dict[str, object]] = {}
    for case_id in sorted(set(current_index) | set(baseline_index)):
        for item in _compare_case_components(current_index.get(case_id), baseline_index.get(case_id)):
            record = bucket.setdefault(
                item.key,
                {
                    "label": item.label or item.key,
                    "current_scores": [],
                    "baseline_scores": [],
                    "count": 0,
                },
            )
            if item.current_score is not None:
                record["current_scores"].append(item.current_score)
            if item.baseline_score is not None:
                record["baseline_scores"].append(item.baseline_score)
            record["count"] = int(record["count"]) + 1
    summaries: list[EvalComponentSummary] = []
    for key in sorted(bucket):
        item = bucket[key]
        current_score = _average(item["current_scores"])
        baseline_score = _average(item["baseline_scores"])
        summaries.append(
            EvalComponentSummary(
                key=key,
                label=str(item["label"]),
                current_score=current_score,
                baseline_score=baseline_score,
                delta=round((current_score or 0.0) - (baseline_score or 0.0), 4),
                case_count=int(item["count"]),
            )
        )
    return summaries


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _build_stats(values: list[float]) -> EvalStabilityStats:
    if not values:
        return EvalStabilityStats(sample_size=0)
    numeric = [float(item) for item in values]
    mean = sum(numeric) / len(numeric)
    min_value = min(numeric)
    max_value = max(numeric)
    variance = sum((item - mean) ** 2 for item in numeric) / len(numeric)
    return EvalStabilityStats(
        sample_size=len(numeric),
        mean=round(mean, 4),
        min=round(min_value, 4),
        max=round(max_value, 4),
        range=round(max_value - min_value, 4),
        stddev=round(math.sqrt(variance), 4),
    )


def _build_case_stability_summary(
    case_id: str,
    results: list[EvalCaseResult],
    case_spec: EvalCaseSpec | None,
) -> EvalStabilityCaseSummary:
    statuses = [item.status for item in results]
    score_values = [item.total_score for item in results]
    token_values = [value for value in (_extract_total_tokens_from_result(item) for item in results) if value is not None]
    failover_hits = sum(1 for item in results if _result_used_failover(item))
    component_scores: dict[str, list[float]] = {}
    component_labels: dict[str, str] = {}
    for result in results:
        for component in _result_components(result).values():
            key = str(component.get("key") or "")
            score = _as_float(component.get("score"))
            if not key or score is None:
                continue
            component_scores.setdefault(key, []).append(score)
            component_labels.setdefault(key, str(component.get("label") or key))
    component_summaries = []
    for key, scores in sorted(component_scores.items()):
        score_stats = _build_stats(scores)
        component_summaries.append(
            EvalStabilityComponentSummary(
                key=key,
                label=component_labels.get(key, key),
                score=score_stats,
                unstable=bool((score_stats.range or 0.0) > 0.0),
            )
        )
    anchor_signal_count, anchor_strength = _anchor_signal_summary(case_spec)
    score_stats = _build_stats(score_values)
    token_stats = _build_stats(token_values)
    status_values = sorted(set(statuses))
    unstable_reasons: list[str] = []
    if len(status_values) > 1:
        unstable_reasons.append("status_flap")
    if (score_stats.range or 0.0) > 0.0:
        unstable_reasons.append("score_range")
    if (token_stats.range or 0.0) >= 500 and (token_stats.mean or 0.0) > 0:
        unstable_reasons.append("token_range")
    if any(item.unstable for item in component_summaries):
        unstable_reasons.append("component_range")
    if 0.0 < failover_hits < len(results):
        unstable_reasons.append("intermittent_failover")
    return EvalStabilityCaseSummary(
        case_id=case_id,
        run_count=len(results),
        status_values=status_values,
        pass_rate=round(sum(1 for item in statuses if item == "passed") / max(1, len(statuses)), 4),
        score=score_stats,
        token_total=token_stats,
        failover_rate=round(failover_hits / max(1, len(results)), 4),
        anchor_signal_count=anchor_signal_count,
        anchor_strength=anchor_strength,
        unstable=bool(unstable_reasons),
        unstable_reasons=unstable_reasons,
        components=component_summaries,
    )


def _anchor_signal_summary(case_spec: EvalCaseSpec | None) -> tuple[int, str]:
    if case_spec is None:
        return 0, "weak"
    signal_count = 0
    final_text = case_spec.expectations.final_text
    signal_count += len(final_text.contains_all)
    signal_count += len(final_text.contains_any)
    signal_count += len(final_text.forbid_all)
    signal_count += len(case_spec.expectations.tool_path.required_calls)
    signal_count += len(case_spec.expectations.tool_path.forbidden_calls)
    for value in (
        case_spec.expectations.efficiency.max_llm_requests,
        case_spec.expectations.efficiency.max_tool_calls,
        case_spec.expectations.context.expect_compaction,
        case_spec.expectations.context.expect_preserved_tail_user_turns,
        case_spec.expectations.diagnostics.expect_provider_ref,
        case_spec.expectations.diagnostics.expect_final_provider_ref,
    ):
        if value not in (None, ""):
            signal_count += 1
    for key, value in case_spec.grader_case.items():
        if value in (None, "", [], {}):
            continue
        if key.endswith("_anchor_groups") and isinstance(value, list):
            signal_count += sum(1 for item in value if item)
            continue
        if key.endswith("_contains_all") or key.endswith("_contains_any") or key.endswith("_forbid_all"):
            if isinstance(value, list):
                signal_count += len(value)
            else:
                signal_count += 1
            continue
        if key.startswith("expected_") or key.startswith("max_") or key.startswith("min_") or key.endswith("_count"):
            if isinstance(value, list):
                signal_count += len(value)
            else:
                signal_count += 1
    if signal_count >= 4:
        return signal_count, "strong"
    if signal_count >= 3:
        return signal_count, "medium"
    return signal_count, "weak"


def _extract_total_tokens_from_result(result: EvalCaseResult) -> float | None:
    diagnostics = result.diagnostics_json if isinstance(result.diagnostics_json, dict) else {}
    turn_totals: list[float] = []
    for turn in list(diagnostics.get("turns") or []):
        run = turn.get("run") if isinstance(turn, dict) else {}
        total = _extract_total_tokens_from_mapping(run if isinstance(run, dict) else {})
        if total is not None:
            turn_totals.append(total)
    if turn_totals:
        return round(sum(turn_totals), 4)
    return _extract_total_tokens_from_mapping(diagnostics)


def _extract_total_tokens_from_mapping(mapping: dict[str, object]) -> float | None:
    for key in ("latest_actual_usage", "last_actual_usage", "usage_summary"):
        payload = mapping.get(key)
        if isinstance(payload, dict) and payload.get("total_tokens") is not None:
            return float(payload["total_tokens"])
    for key in ("actual_cumulative_total_tokens", "actual_peak_total_tokens"):
        value = mapping.get(key)
        if value is not None:
            return float(value)
    current_run = mapping.get("current_run")
    if isinstance(current_run, dict):
        for key in ("actual_cumulative_total_tokens", "actual_peak_total_tokens"):
            value = current_run.get(key)
            if value is not None:
                return float(value)
    return None


def _result_used_failover(result: EvalCaseResult) -> bool:
    diagnostics = result.diagnostics_json if isinstance(result.diagnostics_json, dict) else {}
    for turn in list(diagnostics.get("turns") or []):
        run = turn.get("run") if isinstance(turn, dict) else {}
        if not isinstance(run, dict):
            continue
        attempted_profiles = list(run.get("attempted_profiles") or [])
        provider_ref = str(run.get("provider_ref") or "").strip()
        final_provider_ref = str(run.get("final_provider_ref") or "").strip()
        if run.get("failover_trigger"):
            return True
        if len(attempted_profiles) > 1:
            return True
        if provider_ref and final_provider_ref and provider_ref != final_provider_ref:
            return True
    return False


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _as_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)
