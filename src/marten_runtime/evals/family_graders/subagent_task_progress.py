from __future__ import annotations

from marten_runtime.evals.family_graders.common import (
    build_blocked_result,
    evaluate_text_evidence,
    finalize_component_case_result,
    normalize_anchor_groups,
)
from marten_runtime.evals.models import EvalCaseObservation, EvalCaseResult, EvalCaseSpec, EvalComponentScore

_COMPONENT_LABELS = {
    "delegation_quality": "委派质量",
    "child_progress": "子任务推进",
    "child_completion": "子任务完成",
    "parent_integration": "父会话吸收",
    "duplicate_dispatch_penalty": "重复派发控制",
}
_TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}


def grade_subagent_task_progress_case_result(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
    eval_run_id: str,
) -> EvalCaseResult:
    if observation.blocked_reason:
        return build_blocked_result(case, observation, eval_run_id)

    grader_case = dict(case.grader_case)
    subagent_diag = dict((observation.diagnostics_json or {}).get("subagent") or {})
    tasks = _visible_subagent_tasks(list(subagent_diag.get("tasks") or []))
    parent_session = (
        subagent_diag.get("parent_session") if isinstance(subagent_diag.get("parent_session"), dict) else {}
    )
    final_text = str(observation.final_text or "")
    expected_spawn_count = int(grader_case.get("expected_spawn_count") or 0)
    max_spawn_count = int(grader_case.get("max_spawn_count") or expected_spawn_count)
    expected_labels = [str(item) for item in list(grader_case.get("expected_task_labels") or [])]
    integration_contains = [str(item) for item in list(grader_case.get("integration_contains_all") or [])]
    integration_anchor_groups = normalize_anchor_groups(grader_case.get("integration_anchor_groups"))

    builders = {
        "delegation_quality": lambda weight: _grade_delegation_quality(
            weight,
            tasks,
            expected_spawn_count,
            max_spawn_count,
            final_text,
        ),
        "child_progress": lambda weight: _grade_child_progress(weight, tasks, expected_labels),
        "child_completion": lambda weight: _grade_child_completion(weight, tasks),
        "parent_integration": lambda weight: _grade_parent_integration(
            weight,
            tasks,
            parent_session,
            final_text,
            integration_contains,
            integration_anchor_groups,
        ),
        "duplicate_dispatch_penalty": lambda weight: _grade_duplicate_dispatch(
            weight,
            tasks,
            expected_spawn_count,
            max_spawn_count,
            expected_labels,
        ),
    }
    component_items = [builders[key](weight) for key, weight in case.component_weights.items()]
    return finalize_component_case_result(
        case,
        observation,
        eval_run_id,
        grader_id="subagent_task_progress",
        component_items=component_items,
        final_text=final_text,
    )


def _grade_delegation_quality(
    weight: int,
    tasks: list[dict[str, object]],
    expected_spawn_count: int,
    max_spawn_count: int,
    final_text: str,
) -> EvalComponentScore:
    spawn_count = len(tasks)
    checks = [spawn_count == expected_spawn_count, spawn_count <= max_spawn_count]
    if expected_spawn_count == 0:
        checks.append("后台" not in final_text and "子任务" not in final_text)
    ratio = 1.0 if all(checks) else 0.0
    return EvalComponentScore(
        key="delegation_quality",
        label=_COMPONENT_LABELS["delegation_quality"],
        weight=weight,
        ratio=ratio,
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details={
            "expected_spawn_count": expected_spawn_count,
            "max_spawn_count": max_spawn_count,
            "actual_spawn_count": spawn_count,
            "final_text": final_text,
        },
    )


def _grade_child_progress(weight: int, tasks: list[dict[str, object]], expected_labels: list[str]) -> EvalComponentScore:
    checks = []
    labels = [str(item.get("label") or "") for item in tasks]
    for label in expected_labels:
        checks.append(label in labels)
    for item in tasks:
        checks.append(bool(item.get("child_session_id")))
        checks.append(bool(item.get("child_run_id")))
        checks.append(str(item.get("status") or "") in {"running", *sorted(_TERMINAL)})
    ratio = 1.0 if all(checks) else 0.0
    return EvalComponentScore(
        key="child_progress",
        label=_COMPONENT_LABELS["child_progress"],
        weight=weight,
        ratio=ratio,
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details={"labels": labels, "task_count": len(tasks), "tasks": tasks},
    )


def _grade_child_completion(weight: int, tasks: list[dict[str, object]]) -> EvalComponentScore:
    checks = []
    terminal_details = []
    for item in tasks:
        status = str(item.get("status") or "")
        child_run = item.get("child_run") if isinstance(item.get("child_run"), dict) else {}
        completed = status in _TERMINAL and bool(
            item.get("result_summary") or child_run.get("final_text") or child_run.get("final_text_preview")
        )
        checks.append(completed)
        terminal_details.append(
            {
                "task_id": item.get("task_id"),
                "status": status,
                "result_summary": item.get("result_summary"),
                "child_run_id": item.get("child_run_id"),
            }
        )
    ratio = 1.0 if tasks and all(checks) else 0.0
    return EvalComponentScore(
        key="child_completion",
        label=_COMPONENT_LABELS["child_completion"],
        weight=weight,
        ratio=ratio,
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details={"tasks": terminal_details},
    )


def _grade_parent_integration(
    weight: int,
    tasks: list[dict[str, object]],
    parent_session: dict[str, object],
    final_text: str,
    integration_contains: list[str],
    integration_anchor_groups: list[list[str]],
) -> EvalComponentScore:
    history = list(parent_session.get("history") or [])
    checks = []
    completion_hits = []
    completion_texts: list[str] = []
    child_evidence_texts: list[str] = []
    for item in tasks:
        label = str(item.get("label") or "")
        result_summary = str(item.get("result_summary") or "").strip()
        if result_summary:
            child_evidence_texts.append(result_summary)
        child_run = item.get("child_run") if isinstance(item.get("child_run"), dict) else {}
        child_final_text = str(child_run.get("final_text") or child_run.get("final_text_preview") or "").strip()
        if child_final_text:
            child_evidence_texts.append(child_final_text)
        matched_entries = [
            entry
            for entry in history
            if str(entry.get("role") or "") == "system"
            and "subagent task completed" in str(entry.get("content") or "")
            and label in str(entry.get("content") or "")
        ]
        matched = bool(matched_entries) or bool(result_summary or child_final_text)
        checks.append(matched)
        completion_hits.append({"label": label, "matched": matched})
        completion_texts.extend(
            str(entry.get("content") or "").strip()
            for entry in matched_entries
            if str(entry.get("content") or "").strip()
        )
    text_evidence = evaluate_text_evidence(
        final_text=final_text,
        evidence_texts=[final_text, *child_evidence_texts, *completion_texts],
        required=integration_contains,
        anchor_groups=integration_anchor_groups,
    )
    checks.append(bool(text_evidence["passed"]))
    ratio = 1.0 if all(checks) else 0.0
    return EvalComponentScore(
        key="parent_integration",
        label=_COMPONENT_LABELS["parent_integration"],
        weight=weight,
        ratio=ratio,
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details={
            "integration_contains_all": integration_contains,
            "integration_anchor_groups": integration_anchor_groups,
            "completion_hits": completion_hits,
            "final_text": final_text,
            "text_evidence": text_evidence,
        },
    )


def _grade_duplicate_dispatch(
    weight: int,
    tasks: list[dict[str, object]],
    expected_spawn_count: int,
    max_spawn_count: int,
    expected_labels: list[str],
) -> EvalComponentScore:
    labels = [str(item.get("label") or "") for item in tasks]
    unique_task_ids = {str(item.get("task_id") or "") for item in tasks if item.get("task_id")}
    checks = [len(tasks) <= max_spawn_count, len(unique_task_ids) == len(tasks)]
    if expected_labels:
        checks.append(sorted(labels) == sorted(expected_labels))
    else:
        checks.append(len(tasks) == expected_spawn_count)
    ratio = 1.0 if all(checks) else 0.0
    return EvalComponentScore(
        key="duplicate_dispatch_penalty",
        label=_COMPONENT_LABELS["duplicate_dispatch_penalty"],
        weight=weight,
        ratio=ratio,
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details={
            "expected_spawn_count": expected_spawn_count,
            "max_spawn_count": max_spawn_count,
            "labels": labels,
            "unique_task_ids": sorted(unique_task_ids),
        },
    )


def _visible_subagent_tasks(tasks: list[dict[str, object]]) -> list[dict[str, object]]:
    visible: list[dict[str, object]] = []
    for item in tasks:
        label = str(item.get("label") or "").strip()
        if label.startswith("self-improve-review:"):
            continue
        visible.append(item)
    return visible
