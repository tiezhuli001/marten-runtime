from __future__ import annotations

import re

from marten_runtime.evals.family_graders.common import (
    build_blocked_result,
    finalize_component_case_result,
)
from marten_runtime.evals.models import (
    EvalCaseObservation,
    EvalCaseResult,
    EvalCaseSpec,
    EvalComponentScore,
)
from marten_runtime.runtime.bazi_output_contract import bazi_timing_contract_violations


_COMPONENT_LABELS = {
    "citation_integrity": "Theory citation integrity",
    "tool_order": "Bazi tool order",
    "fingerprint_consistency": "Chart and Dayun fingerprint consistency",
    "degradation": "Knowledge degradation",
    "mismatch_stop": "Fingerprint mismatch stop",
    "risk_expression": "Risk expression",
    "output_structure": "Readable Bazi analysis structure",
}


def grade_bazi_agent_case_result(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
    eval_run_id: str,
) -> EvalCaseResult:
    if observation.blocked_reason:
        return build_blocked_result(case, observation, eval_run_id)
    components = [
        _grade_component(key, weight, case, observation)
        for key, weight in case.component_weights.items()
    ]
    return finalize_component_case_result(
        case,
        observation,
        eval_run_id,
        grader_id="bazi_agent",
        component_items=components,
        final_text=str(observation.final_text or ""),
    )


def _grade_component(
    key: str,
    weight: int,
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
) -> EvalComponentScore:
    config = dict(case.grader_case)
    final_text = str(observation.final_text or "")
    calls = list(observation.tool_calls)
    if key == "citation_integrity":
        citations = _search_citations(calls)
        expected_references = _search_reference_labels(calls)
        visible_references = _visible_reference_labels(final_text)
        passed = (
            bool(citations)
            and bool(visible_references)
            and all(reference in final_text for reference in expected_references)
            and "source_id" not in final_text
            and "chunk_id" not in final_text
        )
        details = {
            "citations": citations,
            "expected_references": expected_references,
            "readable_references": visible_references,
        }
    elif key == "tool_order":
        path = [
            (str(call.get("tool_name") or ""), _action(call))
            for call in calls
        ]
        required = [tuple(item) for item in config.get("required_tool_order") or []]
        passed = _is_subsequence(required, path)
        details = {"required": required, "actual": path}
    elif key == "fingerprint_consistency":
        fingerprints = _bazi_fingerprints(calls, {"chart", "dayun"})
        passed = len(fingerprints) >= 2 and len(set(fingerprints)) == 1
        details = {"fingerprints": fingerprints}
    elif key == "degradation":
        bazi_ok = any(
            str(call.get("tool_name") or "") == "bazi"
            and bool(_tool_result(call).get("ok"))
            for call in calls
        )
        search_results = [
            _tool_result(call)
            for call in calls
            if str(call.get("tool_name") or "") == "knowledge" and _action(call) == "search"
        ]
        degraded = bool(search_results) and any(
            not bool(item.get("ok")) or not list(item.get("results") or [])
            for item in search_results
        )
        required = [str(item) for item in config.get("required_final_contains") or []]
        passed = bazi_ok and degraded and all(item in final_text for item in required)
        details = {"bazi_ok": bazi_ok, "search_results": search_results, "required": required}
    elif key == "mismatch_stop":
        fingerprints = _bazi_fingerprints(calls, {"chart", "dayun"})
        marker = str(config.get("stop_marker") or "停止综合解释")
        passed = len(set(fingerprints)) > 1 and marker in final_text
        details = {"fingerprints": fingerprints, "stop_marker": marker}
    elif key == "risk_expression":
        required = [str(item) for item in config.get("required_final_contains") or []]
        forbidden = [str(item) for item in config.get("forbidden_final_contains") or []]
        passed = all(item in final_text for item in required) and all(
            item not in final_text for item in forbidden
        )
        details = {"required": required, "forbidden": forbidden}
    elif key == "output_structure":
        required = [
            str(item)
            for item in config.get("required_sections")
            or [
                "命盘",
                "原局格局喜用",
                "大运",
                "健康注意",
                "学历",
                "事业",
                "婚姻",
                "六亲",
                "财富等级",
                "过三关",
                "参考依据",
            ]
        ]
        forbidden = [
            "source_id",
            "chunk_id",
            '"wide_screen_mode"',
            '"elements"',
            "哪几年适合结婚",
            "哪步运财运更强",
            "是否适合创业或换城市",
            "巳巳自刑",
            "双巳自刑",
        ]
        positions = [_bazi_section_position(final_text, item) for item in required]
        require_past_event_reasoning = bool(
            config.get("require_past_event_reasoning", False)
        )
        past_event_reasoning = _has_past_event_reasoning(final_text)
        require_concrete_topics = bool(config.get("require_concrete_topics", False))
        concrete_topics = _has_concrete_topic_analysis(final_text)
        require_timing_triggers = bool(config.get("require_timing_triggers", False))
        timing_triggers = _has_concrete_timing_analysis(final_text)
        passed = (
            all(position >= 0 for position in positions)
            and positions == sorted(positions)
            and (not require_past_event_reasoning or past_event_reasoning)
            and (not require_concrete_topics or concrete_topics)
            and (not require_timing_triggers or timing_triggers)
            and all(
            item not in final_text for item in forbidden
            )
        )
        details = {
            "required": required,
            "positions": positions,
            "forbidden": forbidden,
            "require_past_event_reasoning": require_past_event_reasoning,
            "past_event_reasoning": past_event_reasoning,
            "require_concrete_topics": require_concrete_topics,
            "concrete_topics": concrete_topics,
            "require_timing_triggers": require_timing_triggers,
            "timing_triggers": timing_triggers,
        }
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


def _action(call: dict[str, object]) -> str:
    payload = call.get("tool_payload")
    return str(payload.get("action") or "") if isinstance(payload, dict) else ""


def _bazi_section_position(text: str, section: str) -> int:
    match = re.search(
        rf"(?m)^\s*(?:#{{1,6}}\s*)?(?:\*{{1,2}})?"
        rf"(?:(?:[一二三四五六七八九十]+|\d+)[、.．]\s*)?"
        rf"{re.escape(section)}(?:\*{{1,2}})?(?=\s|[（(:：]|$)",
        text,
    )
    return match.start() if match is not None else -1


def _has_past_event_reasoning(text: str) -> bool:
    for line in str(text or "").splitlines():
        if not re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", line):
            continue
        if line.count("｜") < 2 and line.count("|") < 2:
            continue
        if all(marker in line for marker in ("流年", "大运", "原局")):
            return True
    return False


def _has_concrete_topic_analysis(text: str) -> bool:
    education_text = _bazi_section_text(text, "学历")
    marriage_text = _bazi_section_text(text, "婚姻")
    wealth_text = _bazi_section_text(text, "财富等级")
    education = _contains_gregorian_year(education_text) and any(
        marker in education_text for marker in ("流年", "大运", "原局", "印星", "学习", "升学")
    )
    marriage = _contains_gregorian_year(marriage_text) and any(
        marker in marriage_text
        for marker in ("流年", "大运", "夫妻宫", "配偶星", "结婚", "合", "冲")
    )
    wealth = any(
        marker in wealth_text
        for marker in ("原局", "大运", "财星", "获取方式", "承载", "积累", "现实基线")
    ) and not any(
        "财富栏" in violation for violation in bazi_timing_contract_violations(text)
    )
    return education and marriage and wealth


def _has_concrete_timing_analysis(text: str) -> bool:
    return _has_past_event_reasoning(text) and not bazi_timing_contract_violations(text)


def _contains_gregorian_year(text: str) -> bool:
    return bool(re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text))


def _bazi_section_text(text: str, section: str) -> str:
    start = _bazi_section_position(text, section)
    if start < 0:
        return ""
    titles = (
        "命盘",
        "原局格局喜用",
        "大运",
        "健康注意",
        "学历",
        "事业",
        "婚姻",
        "六亲",
        "财富等级",
        "过三关",
        "参考依据",
    )
    following = [
        position
        for title in titles
        if title != section
        and (position := _bazi_section_position(text[start + 1 :], title)) >= 0
    ]
    end = start + 1 + min(following) if following else len(text)
    return text[start:end]


def _tool_result(call: dict[str, object]) -> dict[str, object]:
    result = call.get("tool_result")
    return dict(result) if isinstance(result, dict) else {}


def _search_citations(calls: list[dict[str, object]]) -> list[tuple[str, str]]:
    citations: list[tuple[str, str]] = []
    for call in calls:
        if str(call.get("tool_name") or "") != "knowledge" or _action(call) != "search":
            continue
        for item in _tool_result(call).get("results") or []:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "")
            chunk_id = str(item.get("chunk_id") or "")
            if source_id and chunk_id:
                citations.append((source_id, chunk_id))
    return citations


def _search_reference_labels(calls: list[dict[str, object]]) -> list[str]:
    references: list[str] = []
    for call in calls:
        if str(call.get("tool_name") or "") != "knowledge" or _action(call) != "search":
            continue
        for item in _tool_result(call).get("results") or []:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "")
            chunk_id = str(item.get("chunk_id") or "")
            title = str(item.get("source_title") or "").strip()
            heading = str(item.get("heading") or "").strip()
            if not source_id or not chunk_id or not title:
                continue
            book = title if title.startswith("《") else f"《{title}》"
            reference = f"{book}·{heading}" if heading else book
            if reference not in references:
                references.append(reference)
    return references


def _visible_reference_labels(final_text: str) -> list[str]:
    references: list[str] = []
    pattern = re.compile(r"《[^》\n]+》(?:\s*·\s*[^，。；;\n]+)?")
    for match in pattern.finditer(str(final_text or "")):
        reference = match.group(0).strip()
        if reference not in references:
            references.append(reference)
    return references


def _bazi_fingerprints(
    calls: list[dict[str, object]], actions: set[str]
) -> list[str]:
    return [
        str(_tool_result(call).get("inputFingerprint") or "")
        for call in calls
        if str(call.get("tool_name") or "") == "bazi"
        and _action(call) in actions
        and _tool_result(call).get("inputFingerprint")
    ]


def _is_subsequence(required: list[tuple], actual: list[tuple[str, str]]) -> bool:
    cursor = iter(actual)
    return all(any(tuple(candidate) == tuple(item) for candidate in cursor) for item in required)
