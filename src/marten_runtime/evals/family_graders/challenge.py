from __future__ import annotations

from typing import Any

from marten_runtime.evals.family_graders.common import (
    build_blocked_result,
    evaluate_text_evidence,
    finalize_component_case_result,
    normalize_anchor_groups,
)
from marten_runtime.evals.models import EvalCaseObservation, EvalCaseResult, EvalCaseSpec, EvalComponentScore

_COMPONENT_LABELS = {
    "task_success": "任务完成",
    "reasoning_quality": "证据质量",
    "tool_path_quality": "工具路径质量",
    "state_continuity": "状态连续性",
    "efficiency": "效率",
}
_TERMINAL_SUBAGENT_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}


def grade_challenge_case_result(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
    eval_run_id: str,
) -> EvalCaseResult:
    if observation.blocked_reason:
        return build_blocked_result(case, observation, eval_run_id)

    grader_case = dict(case.grader_case or {})
    final_text = str(observation.final_text or "")
    evidence_texts = _collect_evidence_texts(observation)
    components = [
        _grade_component(
            key=key,
            weight=weight,
            rules=_rules_for_component(grader_case, key),
            case=case,
            observation=observation,
            final_text=final_text,
            evidence_texts=evidence_texts,
        )
        for key, weight in case.component_weights.items()
    ]
    return finalize_component_case_result(
        case,
        observation,
        eval_run_id,
        grader_id="challenge",
        component_items=components,
        final_text=final_text,
    )


def _grade_component(
    *,
    key: str,
    weight: int,
    rules: dict[str, object],
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
    final_text: str,
    evidence_texts: list[str],
) -> EvalComponentScore:
    if key in {"task_success", "reasoning_quality"}:
        return _grade_text_component(key, weight, rules, final_text, evidence_texts)
    if key == "tool_path_quality":
        return _grade_tool_path_component(key, weight, rules, observation)
    if key == "state_continuity":
        return _grade_state_continuity_component(key, weight, rules, observation)
    if key == "efficiency":
        return _grade_efficiency_component(key, weight, rules, observation)
    if rules:
        return _grade_text_component(key, weight, rules, final_text, evidence_texts)
    return EvalComponentScore(
        key=key,
        label=_label(key),
        weight=weight,
        ratio=1.0,
        score=float(weight),
        passed=True,
        details={"rules": {}, "default_pass": True, "case_id": case.case_id},
    )


def _rules_for_component(grader_case: dict[str, object], key: str) -> dict[str, object]:
    raw = grader_case.get(key)
    return dict(raw) if isinstance(raw, dict) else {}


def _grade_text_component(
    key: str,
    weight: int,
    rules: dict[str, object],
    final_text: str,
    evidence_texts: list[str],
) -> EvalComponentScore:
    base = _evaluate_text_rules(rules, final_text, evidence_texts)
    rubric = _grade_rubric_items(
        rules.get("rubric_items"),
        lambda item: _evaluate_text_rules(item, final_text, evidence_texts),
    )
    ratio = _component_ratio(base["passed"], rubric)
    details = {
        **base["details"],
        "prerequisite_passed": base["passed"],
    }
    if rubric is not None:
        details["rubric_items"] = rubric["items"]
        details["rubric_points"] = {
            "earned": rubric["earned_points"],
            "total": rubric["total_points"],
        }
    return EvalComponentScore(
        key=key,
        label=_label(key),
        weight=weight,
        ratio=round(ratio, 4),
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details=details,
    )

def _grade_tool_path_component(
    key: str,
    weight: int,
    rules: dict[str, object],
    observation: EvalCaseObservation,
) -> EvalComponentScore:
    context = _tool_path_context(observation)
    base = _evaluate_tool_path_rules(rules, context)
    rubric = _grade_rubric_items(
        rules.get("rubric_items"),
        lambda item: _evaluate_tool_path_rules(item, context),
    )
    ratio = _component_ratio(base["passed"], rubric)
    details = {
        **base["details"],
        "prerequisite_passed": base["passed"],
    }
    if rubric is not None:
        details["rubric_items"] = rubric["items"]
        details["rubric_points"] = {
            "earned": rubric["earned_points"],
            "total": rubric["total_points"],
        }
    return EvalComponentScore(
        key=key,
        label=_label(key),
        weight=weight,
        ratio=round(ratio, 4),
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details=details,
    )


def _grade_state_continuity_component(
    key: str,
    weight: int,
    rules: dict[str, object],
    observation: EvalCaseObservation,
) -> EvalComponentScore:
    context = _state_continuity_context(observation)
    base = _evaluate_state_continuity_rules(rules, context)
    rubric = _grade_rubric_items(
        rules.get("rubric_items"),
        lambda item: _evaluate_state_continuity_rules(item, context),
    )
    ratio = _component_ratio(base["passed"], rubric)
    details = {
        **base["details"],
        "prerequisite_passed": base["passed"],
    }
    if rubric is not None:
        details["rubric_items"] = rubric["items"]
        details["rubric_points"] = {
            "earned": rubric["earned_points"],
            "total": rubric["total_points"],
        }
    return EvalComponentScore(
        key=key,
        label=_label(key),
        weight=weight,
        ratio=round(ratio, 4),
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details=details,
    )

def _grade_efficiency_component(
    key: str,
    weight: int,
    rules: dict[str, object],
    observation: EvalCaseObservation,
) -> EvalComponentScore:
    total_tokens = _extract_total_tokens(observation.diagnostics_json or {})
    repair_attempts = _extract_repair_attempts(observation.diagnostics_json or {})
    failover_used = _used_failover(observation.diagnostics_json or {})
    checks: list[bool] = []
    max_llm_requests = _optional_int(rules.get("max_llm_requests"))
    max_tool_calls = _optional_int(rules.get("max_tool_calls"))
    max_total_tokens = _optional_float(rules.get("max_total_tokens"))
    max_repair_attempts = _optional_int(rules.get("max_repair_attempts"))
    if max_llm_requests is not None:
        checks.append(observation.llm_request_count <= max_llm_requests)
    if max_tool_calls is not None:
        checks.append(observation.tool_calls_count <= max_tool_calls)
    if max_total_tokens is not None:
        checks.append(total_tokens is not None and total_tokens <= max_total_tokens)
    if max_repair_attempts is not None:
        checks.append(repair_attempts <= max_repair_attempts)
    if rules.get("allow_failover") is not None and not _as_bool(rules.get("allow_failover")):
        checks.append(not failover_used)
    ratio = 1.0 if all(checks) else 0.0
    return EvalComponentScore(
        key=key,
        label=_label(key),
        weight=weight,
        ratio=round(ratio, 4),
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details={
            "llm_request_count": observation.llm_request_count,
            "tool_calls_count": observation.tool_calls_count,
            "total_tokens": total_tokens,
            "repair_attempts": repair_attempts,
            "failover_used": failover_used,
            "max_llm_requests": max_llm_requests,
            "max_tool_calls": max_tool_calls,
            "max_total_tokens": max_total_tokens,
            "max_repair_attempts": max_repair_attempts,
            "allow_failover": rules.get("allow_failover"),
        },
    )



def _evaluate_text_rules(
    rules: dict[str, object],
    final_text: str,
    evidence_texts: list[str],
) -> dict[str, object]:
    required = _strings(rules.get("contains_all"))
    contains_any = _strings(rules.get("contains_any"))
    forbidden = _strings(rules.get("forbid_all"))
    anchor_groups = normalize_anchor_groups(rules.get("anchor_groups"))
    evidence_source = str(rules.get("evidence_source") or "combined").strip().lower()
    selected_evidence_texts = [final_text] if evidence_source == "final" else [final_text, *evidence_texts]
    text_evidence = evaluate_text_evidence(
        final_text=final_text,
        evidence_texts=selected_evidence_texts,
        required=required,
        forbidden=forbidden,
        anchor_groups=anchor_groups,
    )
    evaluation_text = "\n".join(selected_evidence_texts)
    contains_any_hits = {token: token in evaluation_text for token in contains_any}
    passed = bool(text_evidence["passed"])
    if contains_any:
        passed = passed and any(contains_any_hits.values())
    return {
        "passed": passed,
        "details": {
            "contains_all": required,
            "contains_any": contains_any,
            "forbid_all": forbidden,
            "anchor_groups": anchor_groups,
            "final_text": final_text,
            "text_evidence": text_evidence,
            "contains_any_hits": contains_any_hits,
            "evidence_source": evidence_source,
        },
    }


def _tool_path_context(observation: EvalCaseObservation) -> dict[str, object]:
    tool_calls = list(observation.tool_calls or [])
    tool_names = [str(item.get("tool_name") or "").strip() for item in tool_calls if isinstance(item, dict)]
    return {
        "tool_calls": tool_calls,
        "tool_names": tool_names,
        "skill_ids": _extract_skill_ids(tool_calls),
    }


def _evaluate_tool_path_rules(rules: dict[str, object], context: dict[str, object]) -> dict[str, object]:
    tool_calls = list(context.get("tool_calls") or [])
    tool_names = list(context.get("tool_names") or [])
    skill_ids = list(context.get("skill_ids") or [])
    required_tools = _strings(rules.get("required_tools"))
    forbidden_tools = _strings(rules.get("forbidden_tools"))
    required_skill_ids = _strings(rules.get("required_skill_ids"))
    forbidden_skill_ids = _strings(rules.get("forbidden_skill_ids"))
    min_tool_calls = _optional_int(rules.get("min_tool_calls"))
    max_tool_calls = _optional_int(rules.get("max_tool_calls"))
    checks: list[bool] = []
    checks.extend(tool in tool_names for tool in required_tools)
    checks.extend(tool not in tool_names for tool in forbidden_tools)
    checks.extend(skill_id in skill_ids for skill_id in required_skill_ids)
    checks.extend(skill_id not in skill_ids for skill_id in forbidden_skill_ids)
    if min_tool_calls is not None:
        checks.append(len(tool_calls) >= min_tool_calls)
    if max_tool_calls is not None:
        checks.append(len(tool_calls) <= max_tool_calls)
    return {
        "passed": all(checks),
        "details": {
            "tool_names": tool_names,
            "required_tools": required_tools,
            "forbidden_tools": forbidden_tools,
            "min_tool_calls": min_tool_calls,
            "max_tool_calls": max_tool_calls,
            "actual_tool_calls": len(tool_calls),
            "skill_ids": skill_ids,
            "required_skill_ids": required_skill_ids,
            "forbidden_skill_ids": forbidden_skill_ids,
        },
    }


def _state_continuity_context(observation: EvalCaseObservation) -> dict[str, object]:
    tool_calls = list(observation.tool_calls or [])
    diagnostics = dict(observation.diagnostics_json or {})
    subagent_tasks = _subagent_tasks(diagnostics)
    return {
        "memory_texts": _memory_evidence_texts(tool_calls, diagnostics),
        "memory_sections": _memory_sections(tool_calls, diagnostics),
        "skill_ids": _extract_skill_ids(tool_calls),
        "subagent_tasks": subagent_tasks,
        "task_labels": [str(item.get("label") or "").strip() for item in subagent_tasks],
        "child_tool_names": _subagent_child_tool_names(subagent_tasks),
        "subagent_task_prompts": _subagent_task_prompts(subagent_tasks),
        "subagent_result_texts": _subagent_result_texts(subagent_tasks),
        "final_text": str(observation.final_text or ""),
    }


def _evaluate_state_continuity_rules(rules: dict[str, object], context: dict[str, object]) -> dict[str, object]:
    memory_texts = list(context.get("memory_texts") or [])
    memory_sections = set(context.get("memory_sections") or set())
    skill_ids = list(context.get("skill_ids") or [])
    subagent_tasks = list(context.get("subagent_tasks") or [])
    task_labels = list(context.get("task_labels") or [])
    child_tool_names = list(context.get("child_tool_names") or [])
    required_memory_sections = _strings(rules.get("required_memory_sections"))
    forbidden_memory_tokens = _strings(rules.get("forbidden_memory_tokens"))
    required_subagent_labels = _strings(rules.get("required_subagent_labels"))
    required_skill_ids = _strings(rules.get("required_skill_ids"))
    required_child_tools = _strings(rules.get("required_child_tools"))
    required_subagent_prompt_tokens = _strings(rules.get("required_subagent_prompt_tokens"))
    required_child_result_tokens_in_final = _strings(rules.get("required_child_result_tokens_in_final"))
    subagent_task_prompt_text = "\n".join(str(item or "") for item in list(context.get("subagent_task_prompts") or []))
    child_result_text = "\n".join(str(item or "") for item in list(context.get("subagent_result_texts") or []))
    final_text = str(context.get("final_text") or "")
    min_subagent_tasks = _optional_int(rules.get("min_subagent_tasks"))
    max_subagent_tasks = _optional_int(rules.get("max_subagent_tasks"))
    checks: list[bool] = []
    checks.extend(section in memory_sections for section in required_memory_sections)
    checks.extend(token not in "\n".join(memory_texts) for token in forbidden_memory_tokens)
    checks.extend(label in task_labels for label in required_subagent_labels)
    if min_subagent_tasks is not None:
        checks.append(len(subagent_tasks) >= min_subagent_tasks)
    if max_subagent_tasks is not None:
        checks.append(len(subagent_tasks) <= max_subagent_tasks)
    checks.extend(tool in child_tool_names for tool in required_child_tools)
    checks.extend(token in subagent_task_prompt_text for token in required_subagent_prompt_tokens)
    checks.extend(token in child_result_text and token in final_text for token in required_child_result_tokens_in_final)
    if _as_bool(rules.get("require_subagent_completion")):
        checks.append(_subagent_completion_passed(subagent_tasks))
    checks.extend(skill_id in skill_ids for skill_id in required_skill_ids)
    return {
        "passed": all(checks),
        "details": {
            "memory_sections": sorted(memory_sections),
            "required_memory_sections": required_memory_sections,
            "forbidden_memory_tokens": forbidden_memory_tokens,
            "subagent_labels": task_labels,
            "required_subagent_labels": required_subagent_labels,
            "min_subagent_tasks": min_subagent_tasks,
            "max_subagent_tasks": max_subagent_tasks,
            "child_tool_names": child_tool_names,
            "required_child_tools": required_child_tools,
            "subagent_task_prompts": list(context.get("subagent_task_prompts") or []),
            "required_subagent_prompt_tokens": required_subagent_prompt_tokens,
            "subagent_result_texts": list(context.get("subagent_result_texts") or []),
            "required_child_result_tokens_in_final": required_child_result_tokens_in_final,
            "require_subagent_completion": _as_bool(rules.get("require_subagent_completion")),
            "skill_ids": skill_ids,
            "required_skill_ids": required_skill_ids,
        },
    }


def _subagent_completion_passed(subagent_tasks: list[dict[str, object]]) -> bool:
    return (
        bool(subagent_tasks)
        and all(str(item.get("status") or "").strip() in _TERMINAL_SUBAGENT_STATUSES for item in subagent_tasks)
        and all(bool(item.get("result_summary") or (item.get("child_run") or {}).get("final_text")) for item in subagent_tasks)
    )


def _grade_rubric_items(value: object, evaluator) -> dict[str, object] | None:  # noqa: ANN001
    raw_items = [item for item in list(value or []) if isinstance(item, dict)]
    if not raw_items:
        return None
    details: list[dict[str, object]] = []
    total_points = 0.0
    earned_points = 0.0
    for index, item in enumerate(raw_items, start=1):
        points = _rubric_points(item.get("points"))
        result = evaluator(item)
        passed = bool(result.get("passed"))
        earned = points if passed else 0.0
        total_points += points
        earned_points += earned
        details.append({
            "id": str(item.get("id") or f"item_{index}"),
            "points": points,
            "earned": earned,
            "passed": passed,
            "details": result.get("details"),
        })
    ratio = earned_points / total_points if total_points > 0 else 1.0
    return {
        "items": details,
        "earned_points": round(earned_points, 4),
        "total_points": round(total_points, 4),
        "ratio": ratio,
    }


def _rubric_points(value: object) -> float:
    try:
        points = float(value)
    except (TypeError, ValueError):
        return 1.0
    return points if points > 0 else 1.0


def _component_ratio(prerequisite_passed: bool, rubric: dict[str, object] | None) -> float:
    if not prerequisite_passed:
        return 0.0
    if rubric is None:
        return 1.0
    return float(rubric.get("ratio") or 0.0)

def _collect_evidence_texts(observation: EvalCaseObservation) -> list[str]:
    texts: list[str] = []
    for item in list(observation.tool_calls or []):
        if not isinstance(item, dict):
            continue
        for key in ("tool_payload", "tool_result"):
            payload = item.get(key)
            if isinstance(payload, dict):
                texts.extend(_dict_text_values(payload))
    for turn in list((observation.diagnostics_json or {}).get("turns") or []):
        if isinstance(turn, dict):
            texts.extend(_dict_text_values(turn))
    return [text for text in texts if text]


def _dict_text_values(value: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(value, dict):
        for raw in value.values():
            texts.extend(_dict_text_values(raw))
    elif isinstance(value, list):
        for raw in value:
            texts.extend(_dict_text_values(raw))
    elif isinstance(value, str):
        text = value.strip()
        if text:
            texts.append(text)
    return texts


def _extract_skill_ids(tool_calls: list[dict[str, object]]) -> list[str]:
    ids: list[str] = []
    for item in tool_calls:
        if not isinstance(item, dict) or str(item.get("tool_name") or "").strip() != "skill":
            continue
        for key in ("tool_payload", "tool_result"):
            payload = item.get(key)
            if not isinstance(payload, dict):
                continue
            skill_id = str(payload.get("skill_id") or "").strip()
            if skill_id and skill_id not in ids:
                ids.append(skill_id)
    return ids


def _memory_sections(tool_calls: list[dict[str, object]], diagnostics: dict[str, object]) -> set[str]:
    sections: set[str] = set()
    for item in tool_calls:
        if not isinstance(item, dict) or str(item.get("tool_name") or "").strip() != "memory":
            continue
        for key in ("tool_payload", "tool_result"):
            payload = item.get(key)
            if not isinstance(payload, dict):
                continue
            section = str(payload.get("section") or "").strip()
            if section:
                sections.add(section)
            result_sections = payload.get("sections")
            if isinstance(result_sections, dict):
                sections.update(str(raw).strip() for raw in result_sections if str(raw).strip())
    memory = diagnostics.get("memory")
    if isinstance(memory, dict):
        result_sections = memory.get("sections")
        if isinstance(result_sections, dict):
            sections.update(str(raw).strip() for raw in result_sections if str(raw).strip())
    return sections


def _memory_evidence_texts(tool_calls: list[dict[str, object]], diagnostics: dict[str, object]) -> list[str]:
    texts: list[str] = []
    for item in tool_calls:
        if not isinstance(item, dict) or str(item.get("tool_name") or "").strip() != "memory":
            continue
        texts.extend(_dict_text_values(item))
    memory = diagnostics.get("memory")
    if isinstance(memory, dict):
        texts.extend(_dict_text_values(memory))
    return texts


def _subagent_tasks(diagnostics: dict[str, object]) -> list[dict[str, object]]:
    subagent = diagnostics.get("subagent") if isinstance(diagnostics, dict) else {}
    if not isinstance(subagent, dict):
        return []
    return [item for item in list(subagent.get("tasks") or []) if isinstance(item, dict)]



def _subagent_task_prompts(subagent_tasks: list[dict[str, object]]) -> list[str]:
    prompts: list[str] = []
    for task in subagent_tasks:
        prompt = str(task.get("task_prompt") or "").strip()
        if prompt:
            prompts.append(prompt)
    return prompts


def _subagent_result_texts(subagent_tasks: list[dict[str, object]]) -> list[str]:
    texts: list[str] = []
    for task in subagent_tasks:
        for key in ("result_summary", "error_text"):
            text = str(task.get(key) or "").strip()
            if text:
                texts.append(text)
        child_run = task.get("child_run") if isinstance(task, dict) else {}
        if isinstance(child_run, dict):
            text = str(child_run.get("final_text") or "").strip()
            if text:
                texts.append(text)
    return texts


def _subagent_child_tool_names(subagent_tasks: list[dict[str, object]]) -> list[str]:
    names: list[str] = []
    for task in subagent_tasks:
        child_run = task.get("child_run") if isinstance(task, dict) else {}
        if not isinstance(child_run, dict):
            continue
        for call in list(child_run.get("tool_calls") or []):
            if not isinstance(call, dict):
                continue
            name = str(call.get("tool_name") or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def _extract_total_tokens(diagnostics: dict[str, object]) -> float | None:
    totals: list[float] = []
    for turn in list(diagnostics.get("turns") or []):
        run = turn.get("run") if isinstance(turn, dict) else {}
        if isinstance(run, dict):
            value = _extract_total_tokens_from_mapping(run)
            if value is not None:
                totals.append(value)
    if totals:
        return round(sum(totals), 4)
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


def _extract_repair_attempts(diagnostics: dict[str, object]) -> int:
    values: list[int] = []
    for payload in [diagnostics, *[turn.get("run") for turn in list(diagnostics.get("turns") or []) if isinstance(turn, dict)]]:
        if not isinstance(payload, dict):
            continue
        for key in ("contract_repair_count", "repair_attempts"):
            value = _optional_int(payload.get(key))
            if value is not None:
                values.append(value)
    return sum(values)


def _used_failover(diagnostics: dict[str, object]) -> bool:
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


def _strings(value: object) -> list[str]:
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _as_bool(value: object) -> bool:
    return bool(value)


def _label(key: str) -> str:
    return _COMPONENT_LABELS.get(key, key)
