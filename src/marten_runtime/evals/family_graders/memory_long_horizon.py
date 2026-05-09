from __future__ import annotations

from marten_runtime.evals.family_graders.common import (
    build_blocked_result,
    evaluate_text_evidence,
    finalize_component_case_result,
    normalize_anchor_groups,
)
from marten_runtime.evals.models import EvalCaseObservation, EvalCaseResult, EvalCaseSpec, EvalComponentScore

_COMPONENT_LABELS = {
    "capture": "记忆写入",
    "delayed_recall": "延迟召回",
    "overwrite_correctness": "覆盖正确性",
    "stale_rejection": "陈旧拒斥",
    "utility_gain": "收益应用",
}


def grade_memory_long_horizon_case_result(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
    eval_run_id: str,
) -> EvalCaseResult:
    if observation.blocked_reason:
        return build_blocked_result(case, observation, eval_run_id)

    grader_case = dict(case.grader_case)
    memory_calls = [
        item for item in observation.tool_calls if str(item.get("tool_name") or "").strip() == "memory"
    ]
    final_text = str(observation.final_text or "")
    turn_count = len(list((observation.diagnostics_json or {}).get("turns") or []))
    interference_turns = max(0, turn_count - 2)

    builders = {
        "capture": lambda weight: _grade_capture(weight, grader_case, memory_calls),
        "delayed_recall": lambda weight: _grade_delayed_recall(
            weight,
            grader_case,
            final_text,
            memory_calls,
            interference_turns,
        ),
        "overwrite_correctness": lambda weight: _grade_overwrite_correctness(
            weight,
            grader_case,
            final_text,
            memory_calls,
        ),
        "stale_rejection": lambda weight: _grade_stale_rejection(weight, grader_case, final_text),
        "utility_gain": lambda weight: _grade_utility_gain(weight, grader_case, final_text, memory_calls),
    }
    component_items = [builders[key](weight) for key, weight in case.component_weights.items()]
    return finalize_component_case_result(
        case,
        observation,
        eval_run_id,
        grader_id="memory_long_horizon",
        component_items=component_items,
        final_text=final_text,
    )


def _grade_capture(weight: int, grader_case: dict[str, object], memory_calls: list[dict[str, object]]) -> EvalComponentScore:
    expected_action = str(grader_case.get("expected_memory_action") or "").strip()
    expected_section = str(grader_case.get("expected_section") or "").strip()
    expected_content = [str(item) for item in list(grader_case.get("expected_content_contains") or [])]
    matched_call = None
    for item in memory_calls:
        payload = item.get("tool_payload") if isinstance(item.get("tool_payload"), dict) else {}
        action = str(payload.get("action") or "").strip()
        section = str(payload.get("section") or "").strip()
        content = str(payload.get("content") or "")
        if expected_action and action != expected_action:
            continue
        if expected_section and section != expected_section:
            continue
        if any(token not in content for token in expected_content):
            continue
        matched_call = {"action": action, "section": section, "content": content}
        break
    passed = matched_call is not None
    ratio = 1.0 if passed else 0.0
    return EvalComponentScore(
        key="capture",
        label=_COMPONENT_LABELS["capture"],
        weight=weight,
        ratio=ratio,
        score=round(weight * ratio, 4),
        passed=passed,
        details={
            "expected_action": expected_action,
            "expected_section": expected_section,
            "expected_content_contains": expected_content,
            "memory_call_count": len(memory_calls),
            "matched_call": matched_call,
        },
    )


def _grade_delayed_recall(
    weight: int,
    grader_case: dict[str, object],
    final_text: str,
    memory_calls: list[dict[str, object]],
    interference_turns: int,
) -> EvalComponentScore:
    required = [str(item) for item in list(grader_case.get("recall_contains_all") or [])]
    forbidden = [str(item) for item in list(grader_case.get("recall_forbid_all") or [])]
    anchor_groups = normalize_anchor_groups(grader_case.get("recall_anchor_groups"))
    max_memory_calls = grader_case.get("max_memory_calls")
    min_interference_turns = int(grader_case.get("min_interference_turns") or 0)
    text_evidence = evaluate_text_evidence(
        final_text=final_text,
        evidence_texts=[final_text, *_memory_evidence_texts(memory_calls)],
        required=required,
        forbidden=forbidden,
        anchor_groups=anchor_groups,
    )
    checks = [text_evidence["passed"]]
    if max_memory_calls is not None:
        checks.append(len(memory_calls) <= int(max_memory_calls))
    if min_interference_turns:
        checks.append(interference_turns >= min_interference_turns)
    ratio = 1.0 if checks and all(checks) else 0.0
    return EvalComponentScore(
        key="delayed_recall",
        label=_COMPONENT_LABELS["delayed_recall"],
        weight=weight,
        ratio=ratio,
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details={
            "required": required,
            "forbidden": forbidden,
            "anchor_groups": anchor_groups,
            "max_memory_calls": max_memory_calls,
            "memory_call_count": len(memory_calls),
            "min_interference_turns": min_interference_turns,
            "actual_interference_turns": interference_turns,
            "final_text": final_text,
            "text_evidence": text_evidence,
        },
    )


def _grade_overwrite_correctness(
    weight: int,
    grader_case: dict[str, object],
    final_text: str,
    memory_calls: list[dict[str, object]],
) -> EvalComponentScore:
    required = [str(item) for item in list(grader_case.get("recall_contains_all") or [])]
    forbidden = [str(item) for item in list(grader_case.get("recall_forbid_all") or [])]
    anchor_groups = normalize_anchor_groups(grader_case.get("recall_anchor_groups"))
    expected_action = str(grader_case.get("expected_memory_action") or "replace").strip()
    text_evidence = evaluate_text_evidence(
        final_text=final_text,
        evidence_texts=[final_text, *_memory_evidence_texts(memory_calls)],
        required=required,
        anchor_groups=anchor_groups,
    )
    forbidden_hits = {token: token in final_text for token in forbidden}
    checks = [text_evidence["passed"], not any(forbidden_hits.values())]
    checks.append(
        any(
            str(
                ((item.get("tool_payload") if isinstance(item.get("tool_payload"), dict) else {}).get("action") or "")
            ).strip()
            == expected_action
            for item in memory_calls
        )
    )
    ratio = 1.0 if all(checks) else 0.0
    return EvalComponentScore(
        key="overwrite_correctness",
        label=_COMPONENT_LABELS["overwrite_correctness"],
        weight=weight,
        ratio=ratio,
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details={
            "expected_action": expected_action,
            "required": required,
            "forbidden": forbidden,
            "forbidden_hits": forbidden_hits,
            "anchor_groups": anchor_groups,
            "final_text": final_text,
            "text_evidence": text_evidence,
        },
    )


def _grade_stale_rejection(weight: int, grader_case: dict[str, object], final_text: str) -> EvalComponentScore:
    forbidden = [str(item) for item in list(grader_case.get("recall_forbid_all") or [])]
    if not forbidden:
        forbidden = [str(item) for item in list(grader_case.get("utility_forbid_all") or [])]
    checks = [token not in final_text for token in forbidden]
    ratio = 1.0 if all(checks) else 0.0
    return EvalComponentScore(
        key="stale_rejection",
        label=_COMPONENT_LABELS["stale_rejection"],
        weight=weight,
        ratio=ratio,
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details={"forbidden": forbidden, "final_text": final_text},
    )


def _grade_utility_gain(
    weight: int,
    grader_case: dict[str, object],
    final_text: str,
    memory_calls: list[dict[str, object]],
) -> EvalComponentScore:
    required = [str(item) for item in list(grader_case.get("utility_contains_all") or [])]
    forbidden = [str(item) for item in list(grader_case.get("utility_forbid_all") or [])]
    anchor_groups = normalize_anchor_groups(grader_case.get("utility_anchor_groups"))
    max_memory_calls = grader_case.get("max_memory_calls")
    text_evidence = evaluate_text_evidence(
        final_text=final_text,
        evidence_texts=[final_text, *_memory_evidence_texts(memory_calls)],
        required=required,
        forbidden=forbidden,
        anchor_groups=anchor_groups,
    )
    checks = [text_evidence["passed"]]
    if max_memory_calls is not None:
        checks.append(len(memory_calls) <= int(max_memory_calls))
    ratio = 1.0 if all(checks) else 0.0
    return EvalComponentScore(
        key="utility_gain",
        label=_COMPONENT_LABELS["utility_gain"],
        weight=weight,
        ratio=ratio,
        score=round(weight * ratio, 4),
        passed=ratio >= 1.0,
        details={
            "required": required,
            "forbidden": forbidden,
            "anchor_groups": anchor_groups,
            "max_memory_calls": max_memory_calls,
            "memory_call_count": len(memory_calls),
            "final_text": final_text,
            "text_evidence": text_evidence,
        },
    )


def _memory_evidence_texts(memory_calls: list[dict[str, object]]) -> list[str]:
    texts: list[str] = []
    for item in memory_calls:
        payload = item.get("tool_payload") if isinstance(item.get("tool_payload"), dict) else {}
        tool_result = item.get("tool_result") if isinstance(item.get("tool_result"), dict) else {}
        content = str(payload.get("content") or "").strip()
        if content:
            texts.append(content)
        sections = tool_result.get("sections")
        if not isinstance(sections, dict):
            continue
        for raw_items in sections.values():
            if not isinstance(raw_items, list):
                continue
            for raw_item in raw_items:
                text = str(raw_item).strip()
                if text:
                    texts.append(text)
    return texts
