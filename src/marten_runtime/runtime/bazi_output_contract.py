from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


_SECTION_TITLES = (
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
_YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_EVENT_CATEGORIES = {
    "career_change": ("工作", "事业", "入职", "离职", "转岗", "升职", "降职"),
    "relationship": ("感情", "恋爱", "婚恋", "姻缘", "结婚", "婚姻", "对象"),
    "self_health": ("本人健康", "本人身体", "受伤", "检查", "治疗", "住院", "开刀", "手术"),
    "family": ("父亲", "母亲", "父母", "长辈", "六亲"),
    "wealth_change": ("破财", "亏损", "获利", "得财", "奖金", "买房", "卖房"),
}
_GENERIC_EVENT_TEXTS = {
    "学业", "工作", "事业", "婚恋", "恋爱", "婚姻",
    "健康", "本人健康", "父亲", "母亲", "父母", "六亲",
}
_VAGUE_EVENT_PATTERN = re.compile(
    r"(?:工作平台|居住环境|工作环境|家中长辈事务|长辈|父母事务|家宅事务|"
    r"感情与事业|感情和事业|关系与工作|关系和工作)\s*$"
)
_UNSUPPORTED_RELATIONSHIP_RISK_PATTERN = re.compile(
    r"二婚.{0,16}(?:不高|不重|不大|不能|无法|不属|没有|不足|不支持)"
    r"|(?:不足以|不足|不能|无法|不宜|不作|未能|没有|不支持).{0,16}二婚"
    r"|外缘(?:风险)?.{0,16}(?:不高|不重|不大|不明显|不能|无法|没有|不足|不支持)"
    r"|(?:不足以|不足|不能|无法|不宜|不作|未能|没有|不支持).{0,16}外缘"
)
_NATAL_BRANCH_CLASHES = {
    frozenset(pair) for pair in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")
}
BAZI_VERIFICATION_CONFIDENCE_THRESHOLD = 70
BaziVerificationCategory = Literal[
    "relationship",
    "self_health",
    "family",
    "career_change",
    "wealth_change",
]
BaziViolationScope = Literal["verification", "section", "document"]
BaziRepairStrategy = Literal[
    "deterministic_normalize",
    "verification_patch",
    "section_patch",
    "document_regenerate",
]


@dataclass(frozen=True)
class BaziContractViolation:
    code: str
    scope: BaziViolationScope
    repair_strategy: BaziRepairStrategy
    message: str


class BaziVerificationCandidateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: BaziVerificationCategory
    year: int = Field(ge=1901, le=2100)
    event: str = Field(
        min_length=2,
        max_length=80,
        pattern=r"^[^或并、，,；;。|｜]+$",
    )
    confidence: int = Field(ge=0, le=100)
    evidence_summary: str = Field(min_length=4, max_length=96)
    discard_reason: str = Field(max_length=64)


class BaziVerificationEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=1901, le=2100)
    category: BaziVerificationCategory
    event: str = Field(
        min_length=2,
        max_length=80,
        pattern=r"^[^或并、，,；;。|｜]+$",
    )
    fact_ids: list[str] = Field(default_factory=list, max_length=12)
    liunian_basis: str = Field(default="", max_length=600)
    dayun_basis: str = Field(default="", max_length=600)
    natal_basis: str = Field(default="", max_length=600)
    shensha_basis: str = Field(default="", max_length=240)


class BaziAnalysisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart: str = Field(min_length=4, max_length=2400)
    pattern_and_use: str = Field(min_length=4, max_length=2400)
    dayun: str = Field(min_length=4, max_length=2400)
    health: str = Field(min_length=4, max_length=1800)
    education: str = Field(min_length=4, max_length=1800)
    career: str = Field(min_length=4, max_length=2000)
    marriage: str = Field(min_length=4, max_length=2000)
    kinship: str = Field(min_length=4, max_length=1800)
    wealth: str = Field(min_length=4, max_length=1800)
    verification_candidates: list[BaziVerificationCandidateDraft] = Field(
        min_length=5,
        max_length=10,
    )
    verification_events: list[BaziVerificationEventDraft] = Field(max_length=10)
    references: list[str] = Field(min_length=1, max_length=8)


class BaziVerificationEventsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_candidates: list[BaziVerificationCandidateDraft] = Field(
        min_length=5,
        max_length=10,
    )
    verification_events: list[BaziVerificationEventDraft] = Field(
        max_length=10,
    )


def bazi_analysis_response_schema() -> dict[str, object]:
    return _fact_referenced_response_schema(BaziAnalysisDraft.model_json_schema())


def bazi_verification_events_response_schema() -> dict[str, object]:
    return _fact_referenced_response_schema(BaziVerificationEventsPatch.model_json_schema())


def _fact_referenced_response_schema(schema: dict[str, object]) -> dict[str, object]:
    definitions = schema.get("$defs")
    event_schema = (
        definitions.get("BaziVerificationEventDraft")
        if isinstance(definitions, dict)
        else None
    )
    if not isinstance(event_schema, dict):
        return schema
    properties = event_schema.get("properties")
    if not isinstance(properties, dict):
        return schema
    for field in ("liunian_basis", "dayun_basis", "natal_basis", "shensha_basis"):
        properties.pop(field, None)
    fact_ids_schema = properties.get("fact_ids")
    if isinstance(fact_ids_schema, dict):
        fact_ids_schema.pop("default", None)
    required = [
        str(field)
        for field in event_schema.get("required") or []
        if field not in {"liunian_basis", "dayun_basis", "natal_basis", "shensha_basis"}
    ]
    if "fact_ids" not in required:
        required.append("fact_ids")
    event_schema["required"] = required
    return schema


def bazi_verification_group_violations(
    candidates: list[BaziVerificationCandidateDraft],
    events: list[BaziVerificationEventDraft],
) -> list[str]:
    violations: list[str] = []
    required_categories = {
        "relationship",
        "self_health",
        "family",
        "career_change",
        "wealth_change",
    }
    candidate_categories = {candidate.category for candidate in candidates}
    if missing := sorted(required_categories - candidate_categories):
        violations.append(f"过三关候选表缺少栏目：{','.join(missing)}")
    candidate_counts: dict[str, int] = {}
    for candidate in candidates:
        candidate_counts[candidate.category] = candidate_counts.get(candidate.category, 0) + 1
    if any(count > 2 for count in candidate_counts.values()):
        violations.append("过三关每个候选栏目最多保留两条候选记录")

    candidate_keys = [
        (candidate.category, candidate.year, candidate.event.strip())
        for candidate in candidates
    ]
    if len(candidate_keys) != len(set(candidate_keys)):
        violations.append("过三关候选表包含重复的栏目年份事件")

    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.category] = event_counts.get(event.category, 0) + 1
    if any(count > 2 for count in event_counts.values()):
        violations.append("过三关同一候选栏目最多选择两条事件")

    event_key_list = [
        (event.category, event.year, event.event.strip())
        for event in events
    ]
    event_keys = set(event_key_list)
    if len(event_key_list) != len(event_keys):
        violations.append("过三关最终事件包含重复的栏目年份事件")
    candidate_by_key = {
        (candidate.category, candidate.year, candidate.event.strip()): candidate
        for candidate in candidates
    }
    if not event_keys.issubset(candidate_by_key):
        violations.append("过三关最终事件必须原样来自候选表")

    for candidate in candidates:
        key = (candidate.category, candidate.year, candidate.event.strip())
        selected = key in event_keys
        reason = candidate.discard_reason.strip()
        if selected and reason:
            violations.append("过三关已选候选不得填写舍弃理由")
            break
        if not selected and not reason:
            violations.append("过三关未选候选必须填写舍弃理由")
            break

    for category in required_categories:
        category_candidates = [
            candidate for candidate in candidates if candidate.category == category
        ]
        selected = [
            candidate
            for candidate in category_candidates
            if (candidate.category, candidate.year, candidate.event.strip()) in event_keys
        ]
        unselected = [
            candidate
            for candidate in category_candidates
            if (candidate.category, candidate.year, candidate.event.strip()) not in event_keys
        ]
        eligible = [
            candidate
            for candidate in category_candidates
            if candidate.confidence >= BAZI_VERIFICATION_CONFIDENCE_THRESHOLD
        ]
        if eligible and not selected:
            violations.append(
                f"过三关 {category} 栏目存在可信度达标候选但未选择事件"
            )
        if not eligible and selected:
            violations.append(
                f"过三关 {category} 栏目候选均低于可信度阈值，不应选择事件"
            )
        if any(
            item.confidence < BAZI_VERIFICATION_CONFIDENCE_THRESHOLD
            for item in selected
        ):
            violations.append(
                f"过三关 {category} 栏目选择了低于可信度阈值的候选"
            )
        eligible_unselected = [item for item in unselected if item in eligible]
        if selected and eligible_unselected and min(
            item.confidence for item in selected
        ) < max(item.confidence for item in eligible_unselected):
            violations.append(f"过三关 {category} 栏目未选择可信度最高的一至两条候选")
    return list(dict.fromkeys(violations))


def normalize_bazi_verification_candidate_reasons(
    candidates: list[BaziVerificationCandidateDraft],
    events: list[BaziVerificationEventDraft],
) -> list[BaziVerificationCandidateDraft]:
    selected_keys = {
        (event.category, event.year, event.event.strip())
        for event in events
    }
    selected_categories = {event.category for event in events}
    normalized: list[BaziVerificationCandidateDraft] = []
    for candidate in candidates:
        key = (candidate.category, candidate.year, candidate.event.strip())
        if key in selected_keys:
            reason = ""
        elif candidate.confidence < BAZI_VERIFICATION_CONFIDENCE_THRESHOLD:
            reason = "可信度低于入选阈值"
        elif candidate.discard_reason.strip():
            reason = candidate.discard_reason.strip()
        elif candidate.category in selected_categories:
            reason = "同列可信度排序较低"
        else:
            reason = "该列三层证据不足以形成单一事实"
        normalized.append(
            candidate.model_copy(
                update={"discard_reason": reason}
            )
        )
    return normalized


def bind_bazi_verification_facts(
    draft: BaziAnalysisDraft,
    fact_registry: dict[str, dict[str, object]],
) -> tuple[BaziAnalysisDraft, tuple[BaziContractViolation, ...]]:
    if not fact_registry:
        return draft, ()
    bound_events: list[BaziVerificationEventDraft] = []
    violations: list[BaziContractViolation] = []
    for event in draft.verification_events:
        selected: list[dict[str, object]] = []
        valid_ids: list[str] = []
        for fact_id in dict.fromkeys(event.fact_ids):
            fact = fact_registry.get(str(fact_id))
            if not isinstance(fact, dict) or not _fact_applies_to_year(fact, event.year):
                continue
            selected.append(fact)
            valid_ids.append(str(fact_id))
        by_layer = {
            layer: [
                str(fact.get("text") or "").strip()
                for fact in selected
                if fact.get("layer") == layer and str(fact.get("text") or "").strip()
            ]
            for layer in ("liunian", "dayun", "natal", "shensha")
        }
        has_supporting_natal_fact = any(
            fact.get("layer") == "natal" and fact.get("kind") != "pillars"
            for fact in selected
        )
        label = f"{event.year}年｜{event.event.strip()}"
        missing_layers = [
            layer
            for layer in ("liunian", "dayun", "natal")
            if not by_layer[layer]
            or (layer == "natal" and not has_supporting_natal_fact)
        ]
        if missing_layers:
            violations.append(
                BaziContractViolation(
                    code="verification_missing_fact_layer",
                    scope="verification",
                    repair_strategy="verification_patch",
                    message=(
                        f"过三关事件 {label} 缺少确定性事实层："
                        f"{','.join(missing_layers)}"
                    ),
                )
            )
        if event.category == "relationship" and "natal.pillar.2" not in valid_ids:
            violations.append(
                BaziContractViolation(
                    code="verification_relationship_spouse_palace_required",
                    scope="verification",
                    repair_strategy="verification_patch",
                    message=(
                        f"过三关事件 {label} 缺少夫妻宫确定性事实："
                        "natal.pillar.2"
                    ),
                )
            )
        bound_events.append(
            event.model_copy(
                update={
                    "fact_ids": valid_ids,
                    "liunian_basis": _join_fact_text(by_layer["liunian"]),
                    "dayun_basis": _join_fact_text(by_layer["dayun"]),
                    "natal_basis": _join_fact_text(by_layer["natal"]),
                    "shensha_basis": "、".join(by_layer["shensha"]),
                }
            )
        )
    return (
        draft.model_copy(update={"verification_events": bound_events}),
        tuple(violations),
    )


def _fact_applies_to_year(fact: dict[str, object], year: int) -> bool:
    fact_year = fact.get("year")
    if isinstance(fact_year, int) and not isinstance(fact_year, bool):
        return fact_year == year
    year_start = fact.get("year_start")
    year_end = fact.get("year_end")
    if isinstance(year_start, int) and isinstance(year_end, int):
        return year_start <= year <= year_end
    return True


def _join_fact_text(items: list[str], *, limit: int = 4) -> str:
    return "；".join(list(dict.fromkeys(items))[:limit])


def classify_bazi_contract_violations(
    messages: list[str] | tuple[str, ...],
) -> tuple[BaziContractViolation, ...]:
    findings: list[BaziContractViolation] = []
    for message in messages:
        if message == "过三关流年神煞与已计算年份不一致":
            findings.append(
                BaziContractViolation(
                    code="verification_invalid_shensha",
                    scope="verification",
                    repair_strategy="deterministic_normalize",
                    message=message,
                )
            )
        elif message.startswith("过三关"):
            findings.append(
                BaziContractViolation(
                    code="verification_contract_violation",
                    scope="verification",
                    repair_strategy="verification_patch",
                    message=message,
                )
            )
        elif message.startswith("正文") or "栏" in message:
            findings.append(
                BaziContractViolation(
                    code="section_contract_violation",
                    scope="section",
                    repair_strategy="section_patch",
                    message=message,
                )
            )
        else:
            findings.append(
                BaziContractViolation(
                    code="document_contract_violation",
                    scope="document",
                    repair_strategy="document_regenerate",
                    message=message,
                )
            )
    return tuple(findings)


def deterministic_rejected_verification_event_labels(
    events: list[BaziVerificationEventDraft],
) -> tuple[str, ...]:
    return tuple(
        violation.split("：", maxsplit=1)[0].removeprefix("过三关事件 ")
        for violation in deterministic_verification_event_violations(events)
    )


def deterministic_verification_event_violations(
    events: list[BaziVerificationEventDraft],
) -> tuple[str, ...]:
    violations: list[str] = []
    for event in events:
        rendered = (
            f"{event.year}年｜{event.event.strip()}｜"
            f"流年：{event.liunian_basis}；大运：{event.dayun_basis}；"
            f"原局：{event.natal_basis}；神煞辅助：{event.shensha_basis}"
        )
        label = f"{event.year}年｜{event.event.strip()}"
        reasons: list[str] = []
        if _has_generic_verification_event(rendered):
            reasons.append("事件字段只是栏目名称或模糊主题")
        if _has_multi_topic_verification_event(rendered):
            reasons.append("事件字段混入多个主题")
        if _has_dangling_verification_event(rendered):
            reasons.append("事件字段没有完整结果")
        if _uses_branch_relation_on_day_stem(rendered):
            reasons.append("依据把地支关系误写成与日干直接作用")
        if reasons:
            violations.append(f"过三关事件 {label}：{'、'.join(reasons)}")
    return tuple(violations)


def bazi_semantic_review_response_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "violations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["event", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["passed", "violations"],
        "additionalProperties": False,
    }


def parse_bazi_analysis_draft(text: str) -> BaziAnalysisDraft | None:
    raw = str(text or "").strip()
    unfenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    decoder = json.JSONDecoder()
    candidates = [raw, unfenced]
    candidates.extend(raw[index:] for index, char in enumerate(raw) if char == "{")
    for candidate in candidates:
        try:
            payload, _ = decoder.raw_decode(candidate.lstrip())
            return _normalize_bazi_analysis_draft(
                BaziAnalysisDraft.model_validate(payload)
            )
        except (TypeError, ValueError, ValidationError):
            continue
    return None


def parse_bazi_verification_events_patch(
    text: str,
) -> BaziVerificationEventsPatch | None:
    raw = str(text or "").strip()
    unfenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    decoder = json.JSONDecoder()
    candidates = [raw, unfenced]
    candidates.extend(raw[index:] for index, char in enumerate(raw) if char == "{")
    for candidate in candidates:
        try:
            payload, _ = decoder.raw_decode(candidate.lstrip())
            return _normalize_bazi_verification_events_patch(
                BaziVerificationEventsPatch.model_validate(payload)
            )
        except (TypeError, ValueError, ValidationError):
            continue
    return None


def _normalize_bazi_analysis_draft(draft: BaziAnalysisDraft) -> BaziAnalysisDraft:
    return draft.model_copy(
        update={
            "verification_candidates": [
                candidate.model_copy(
                    update={
                        "event": _normalize_verification_event_for_year(
                            candidate.event,
                            candidate.year,
                        )
                    }
                )
                for candidate in draft.verification_candidates
            ],
            "verification_events": [
                event.model_copy(
                    update={
                        "event": _normalize_verification_event_for_year(
                            event.event,
                            event.year,
                        )
                    }
                )
                for event in draft.verification_events
            ],
        }
    )


def _normalize_bazi_verification_events_patch(
    patch: BaziVerificationEventsPatch,
) -> BaziVerificationEventsPatch:
    return patch.model_copy(
        update={
            "verification_candidates": [
                candidate.model_copy(
                    update={
                        "event": _normalize_verification_event_for_year(
                            candidate.event,
                            candidate.year,
                        )
                    }
                )
                for candidate in patch.verification_candidates
            ],
            "verification_events": [
                event.model_copy(
                    update={
                        "event": _normalize_verification_event_for_year(
                            event.event,
                            event.year,
                        )
                    }
                )
                for event in patch.verification_events
            ],
        }
    )


def _normalize_verification_event_for_year(text: str, year: int) -> str:
    original = normalize_verification_event_text(text)
    normalized = re.sub(rf"^{year}年\s*", "", original).strip()
    normalized = re.sub(r"(?:且)?结果落定$", "", normalized).strip()
    normalized = normalize_verification_event_text(normalized)
    return normalized if len(normalized) >= 2 else original


def render_bazi_analysis_draft(draft: BaziAnalysisDraft) -> str:
    section_bodies = (
        ("一、命盘", draft.chart),
        ("二、原局格局喜用", draft.pattern_and_use),
        ("三、大运", draft.dayun),
        ("四、健康注意", draft.health),
        ("五、学历", draft.education),
        ("六、事业", draft.career),
        ("七、婚姻", draft.marriage),
        ("八、六亲", draft.kinship),
        ("九、财富等级", draft.wealth),
    )
    rendered = [f"## {title}\n{str(body).strip()}" for title, body in section_bodies]
    event_lines: list[str] = []
    category_order = {
        "relationship": 0,
        "self_health": 1,
        "family": 2,
        "career_change": 3,
        "wealth_change": 4,
    }
    ordered_events = sorted(
        enumerate(draft.verification_events),
        key=lambda item: (
            item[1].year,
            category_order[item[1].category],
            item[0],
        ),
    )
    for _, event in ordered_events:
        evidence = (
            f"流年：{_clean_evidence_clause(event.liunian_basis)}；"
            f"大运：{_clean_evidence_clause(event.dayun_basis)}；"
            f"原局：{_clean_evidence_clause(event.natal_basis)}"
        )
        if event.shensha_basis.strip():
            evidence = (
                f"{evidence}；神煞辅助："
                f"{_clean_evidence_clause(event.shensha_basis)}"
            )
        event_lines.append(f"- {event.year}年｜{event.event.strip()}｜{evidence}。")
    rendered.append("## 十、过三关\n" + "\n".join(event_lines))
    references = "\n".join(
        f"- {str(reference).strip()}"
        for reference in draft.references
        if str(reference).strip()
    )
    rendered.append(f"## 十一、参考依据\n{references}")
    return "\n\n".join(rendered).strip()


def _clean_evidence_clause(text: str) -> str:
    return str(text or "").strip().rstrip("，,；;。 ")


@dataclass(frozen=True)
class BaziSemanticReview:
    passed: bool
    violations: tuple[str, ...] = ()
    rejected_events: tuple[str, ...] = ()


def parse_bazi_semantic_review(text: str) -> BaziSemanticReview:
    raw = str(text or "").strip()
    unfenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    decoder = json.JSONDecoder()
    candidates = [raw, unfenced]
    candidates.extend(raw[index:] for index, char in enumerate(raw) if char == "{")
    for candidate in candidates:
        try:
            payload, _ = decoder.raw_decode(candidate.lstrip())
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("passed"), bool):
            continue
        violations: list[str] = []
        rejected_events: list[str] = []
        for item in payload.get("violations", []):
            if isinstance(item, dict):
                event = str(item.get("event") or "").strip()
                reason = str(item.get("reason") or "").strip()
                detail = f"{event}：{reason}" if event and reason else event or reason
                if event:
                    rejected_events.append(event)
            else:
                detail = str(item).strip()
            if detail:
                violations.append(detail)
        normalized_violations = tuple(violations)
        if payload["passed"] and normalized_violations:
            return BaziSemanticReview(
                False,
                normalized_violations,
                tuple(rejected_events),
            )
        return BaziSemanticReview(
            bool(payload["passed"]),
            normalized_violations,
            tuple(rejected_events),
        )
    return BaziSemanticReview(False, ("语义审查响应无法解析",))


def prune_semantically_rejected_verification_events(
    draft: BaziAnalysisDraft,
    rejected_event_labels: tuple[str, ...],
) -> BaziAnalysisDraft | None:
    unique_labels = tuple(dict.fromkeys(rejected_event_labels))
    if not unique_labels:
        return None
    rejected_keys: set[tuple[BaziVerificationCategory, int, str]] = set()
    for label in unique_labels:
        matches = [
            (event.category, event.year, event.event.strip())
            for event in draft.verification_events
            if (
                f"{event.year}年｜{event.event.strip()}" in label
                or f"{event.year}｜{event.event.strip()}" in label
            )
        ]
        if len(matches) != 1:
            return None
        rejected_keys.add(matches[0])
    if len(rejected_keys) != len(unique_labels):
        return None
    retained_events = [
        event
        for event in draft.verification_events
        if (event.category, event.year, event.event.strip()) not in rejected_keys
    ]
    normalized_candidates = normalize_bazi_verification_candidate_reasons(
        draft.verification_candidates,
        retained_events,
    )
    if bazi_verification_group_violations(normalized_candidates, retained_events):
        return None
    return draft.model_copy(
        update={
            "verification_candidates": normalized_candidates,
            "verification_events": retained_events,
        }
    )


def normalize_bazi_timing_contract_text(text: str) -> str:
    normalized_lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line
        line = line.replace("引出", "引动").replace("发动", "引动")
        line = re.sub(r"[，,]\s*(?=[；;。])", "", line)
        line = re.sub(r"([；;])\s*[，,]", r"\1", line)
        normalized_lines.append(line)
    return "\n".join(normalized_lines).strip()


def bazi_timing_contract_violations(
    text: str,
    *,
    expected_shensha: tuple[str, ...] = (),
    expected_shensha_years: tuple[tuple[int, str], ...] = (),
) -> list[str]:
    marriage = section_text(text, "婚姻")
    kinship = section_text(text, "六亲")
    wealth = section_text(text, "财富等级")
    verification = section_text(text, "过三关")
    violations: list[str] = []
    if _has_invalid_peach_blossom_year(text, marriage):
        violations.append("婚姻栏宣称的桃花流年与命局日支公式不一致")
    if re.search(
        r"二婚.{0,16}(?:不高|不重|不大|不能|无法|不属|没有)"
        r"|(?:不足以|不能|无法|不宜|不作|未能|没有).{0,16}二婚",
        marriage,
    ):
        violations.append("婚姻栏在无明确风险结论时仍讨论二婚")
    if re.search(
        r"虽有外缘|外缘(?:风险)?.{0,12}(?:不高|不重|不大|不明显|不能|无法|没有)"
        r"|(?:不足以|不能|无法|不宜|不作|未能|没有).{0,16}外缘",
        marriage,
    ):
        violations.append("婚姻栏在无明确风险结论时仍讨论外缘")
    if _uses_year_branch_combine_as_marriage_signal(marriage):
        violations.append("婚姻栏把只合年支误作夫妻宫信号")
    if _denies_natal_spouse_palace_clash(text, marriage):
        violations.append("婚姻栏否认原局已经存在的夫妻宫相冲")
    if re.search(r"流年.{0,24}(?:偏财.{0,12}父星|正印.{0,12}母星)", kinship):
        violations.append("六亲栏按流年自身十神直接指定父母身份")
    if _has_generic_verification_event(verification):
        violations.append("过三关包含栏目名称，缺少可核验的具体事件")
    if _has_unstructured_verification_event(verification):
        violations.append("过三关缺少年份、单一事件与事实依据的分隔结构")
    if _has_multi_topic_verification_event(verification):
        violations.append("过三关同一行混入多个事件主题")
    if _has_dangling_verification_event(verification):
        violations.append("过三关包含未完成的事件描述")
    if _uses_branch_relation_on_day_stem(verification):
        violations.append("过三关将地支关系误写成与日干直接作用")
    invalid_shensha_sections = [
        section
        for section in _SECTION_TITLES
        if _has_invalid_yearly_shensha_evidence(
            section_text(text, section),
            expected_shensha_years,
        )
    ]
    if invalid_shensha_sections == ["过三关"]:
        violations.append("过三关流年神煞与已计算年份不一致")
    elif invalid_shensha_sections:
        violations.append("正文中的流年神煞与已计算年份不一致")
    wealth_has_projection = bool(
        re.search(r"\d+(?:\.\d+)?\s*[×*]\s*\d+(?:\.\d+)?|年均可积累|累计.{0,8}\d+\s*万", wealth)
        or re.search(r"\d+(?:\.\d+)?\s*(?:[-~—至到]\s*\d+(?:\.\d+)?\s*)?万(?:元)?", wealth)
        and re.search(r"预计|估算|推算|可达|收入能力|总资产|净积累|资产等级|普通积累|小康|小富|中富", wealth)
    )
    wealth_has_real_baseline = _has_real_wealth_baseline(wealth)
    wealth_has_bazi_estimate = _has_bazi_wealth_estimate(wealth)
    if wealth and not wealth_has_bazi_estimate:
        violations.append("财富栏缺少多路径结构评分与命理年收入能力区间")
    if wealth_has_projection and not wealth_has_real_baseline and not wealth_has_bazi_estimate:
        violations.append("财富栏使用了用户未提供的现实收入或资产基线")
    if not wealth_has_real_baseline and re.search(
        r"总资产.{0,20}\d+(?:\.\d+)?\s*(?:[-~—至到]\s*\d+(?:\.\d+)?\s*)?万",
        wealth,
    ):
        violations.append("财富栏在缺少资产负债基线时推算总资产")
    return violations


def _has_real_wealth_baseline(text: str) -> bool:
    marker = r"用户(?:已)?提供|现实基线|当前(?:年)?收入|现有资产|负债|储蓄率"
    for clause in re.split(r"[。；;\n]", str(text or "")):
        if re.search(rf"(?:未提供|没有提供|缺少|无法提供).{{0,40}}(?:{marker})", clause):
            continue
        if re.search(
            rf"(?:{marker}).{{0,20}}\d+(?:\.\d+)?\s*(?:万(?:元)?|%|％)",
            clause,
        ):
            return True
    return False


def _has_bazi_wealth_estimate(text: str) -> bool:
    normalized = re.sub(r"[*_`]+", "", str(text or ""))
    score_match = re.search(
        r"财富结构分\s*[：:]?\s*(?P<score>\d+)\s*/\s*9"
        r".{0,40}?成局路径\s*(?P<path>\d+)\s*\+\s*承载\s*(?P<capacity>\d+)"
        r"\s*\+\s*大运\s*(?P<dayun>\d+)\s*-\s*制约\s*(?P<constraint>\d+)",
        normalized,
    )
    if score_match is None:
        return False
    values = {key: int(value) for key, value in score_match.groupdict().items()}
    if not (
        0 <= values["path"] <= 3
        and 0 <= values["capacity"] <= 2
        and 0 <= values["dayun"] <= 3
        and 0 <= values["constraint"] <= 3
    ):
        return False
    calculated = max(
        0,
        min(
            9,
            values["path"]
            + values["capacity"]
            + values["dayun"]
            - values["constraint"],
        ),
    )
    if values["score"] != calculated:
        return False
    expected_range = {
        0: (5, 15), 1: (5, 15), 2: (5, 15),
        3: (15, 30), 4: (15, 30),
        5: (30, 60), 6: (30, 60),
        7: (50, 100), 8: (50, 100),
        9: (80, 150),
    }[calculated]
    range_match = re.search(
        r"命理年收入能力区间.{0,16}?(?P<low>\d+)\s*[-~—至到]\s*"
        r"(?P<high>\d+)\s*万",
        normalized,
    )
    visible_ranges = [
        (int(low), int(high))
        for low, high in re.findall(
            r"(?<!\d)(\d+)\s*[-~—至到]\s*(\d+)\s*万",
            normalized,
        )
    ]
    return bool(
        range_match
        and (int(range_match.group("low")), int(range_match.group("high")))
        == expected_range
        and visible_ranges
        and all(item == expected_range for item in visible_ranges)
        and re.search(r"不等同(?:于)?现实收入|不是现实收入事实", normalized)
    )


def past_event_timing_categories(text: str) -> int:
    categories: set[str] = set()
    for line in str(text or "").splitlines():
        if not _YEAR_PATTERN.search(line):
            continue
        if line.count("｜") < 2 and line.count("|") < 2:
            continue
        if not all(marker in line for marker in ("流年", "大运", "原局")):
            continue
        parts = re.split(r"[｜|]", line, maxsplit=2)
        event_text = parts[1].strip() if len(parts) >= 2 else ""
        if event_text in _GENERIC_EVENT_TEXTS:
            continue
        event_text = normalize_verification_event_text(event_text)
        if any(marker in event_text for marker in _EVENT_CATEGORIES["family"]):
            matched = ["family"]
        else:
            matched = [
                category
                for category, markers in _EVENT_CATEGORIES.items()
                if category != "family"
                and any(marker in event_text for marker in markers)
            ]
        if len(matched) == 1:
            categories.add(matched[0])
    return len(categories)


def _has_generic_verification_event(text: str) -> bool:
    for line in str(text or "").splitlines():
        if not _YEAR_PATTERN.search(line):
            continue
        parts = re.split(r"[｜|]", line, maxsplit=2)
        if len(parts) >= 2:
            event = parts[1].strip()
            if (
                event in _GENERIC_EVENT_TEXTS
                or _VAGUE_EVENT_PATTERN.search(event)
            ):
                return True
    return False


def _has_unstructured_verification_event(text: str) -> bool:
    for line in str(text or "").splitlines():
        if _YEAR_PATTERN.search(line) and line.count("｜") < 2 and line.count("|") < 2:
            return True
    return False


def _has_multi_topic_verification_event(text: str) -> bool:
    for line in str(text or "").splitlines():
        if not _YEAR_PATTERN.search(line):
            continue
        parts = re.split(r"[｜|]", line, maxsplit=2)
        if len(parts) < 2:
            continue
        event = parts[1].strip()
        if any(
            marker in event
            for marker in ("或", "、", "，", ",", "以及", "同时", "同步")
        ):
            return True
        matched_categories = {
            category
            for category, markers in _EVENT_CATEGORIES.items()
            if any(marker in event for marker in markers)
        }
        if "family" in matched_categories:
            # Health, career, and wealth terms describe the named relative when
            # the event has an explicit family subject; they are not additional
            # events about the chart owner.
            matched_categories = {"family"}
        if len(matched_categories) > 1:
            return True
    return False


def normalize_verification_event_text(text: str) -> str:
    normalized = str(text or "").strip()
    normalized = normalized.rstrip("，、；;。 ")
    normalized = re.sub(r"(?:但|并|且|和|与|或|及)+$", "", normalized).rstrip("，、；;。 ")
    return normalized


def _has_dangling_verification_event(text: str) -> bool:
    for line in str(text or "").splitlines():
        if not _YEAR_PATTERN.search(line):
            continue
        parts = re.split(r"[｜|]", line, maxsplit=2)
        if len(parts) >= 2 and re.search(r"(?:但|并|且|和|与|或|及)\s*$", parts[1].strip()):
            return True
    return False


def _uses_branch_relation_on_day_stem(text: str) -> bool:
    value = str(text or "")
    return bool(
        re.search(
            r"(?:流年支|大运支|年支|月支|日支|时支|地支)"
            r"[子丑寅卯辰巳午未申酉戌亥]?\s*(?:直接)?(?:合|冲|刑|害|破)日(?:干|主)",
            value,
        )
        or re.search(
            r"(?:六合|相冲|相刑|自刑|相害|相破)[^，,；;。｜|\n]{0,12}"
            r"(?:直接|并)?(?:合|冲|刑|害|破)日(?:干|主)",
            value,
        )
    )


def section_text(text: str, section: str) -> str:
    start = _section_position(text, section)
    if start < 0:
        return ""
    following = [
        position
        for title in _SECTION_TITLES
        if title != section
        and (position := _section_position(text[start + 1 :], title)) >= 0
    ]
    end = start + 1 + min(following) if following else len(text)
    return text[start:end]


def bazi_violation_sections(violations: list[str]) -> list[str]:
    mapping = (
        ("命盘栏", "命盘"),
        ("原局格局喜用栏", "原局格局喜用"),
        ("大运栏", "大运"),
        ("婚姻栏", "婚姻"),
        ("健康栏", "健康注意"),
        ("学历栏", "学历"),
        ("事业栏", "事业"),
        ("六亲栏", "六亲"),
        ("财富栏", "财富等级"),
        ("过三关", "过三关"),
    )
    selected: list[str] = []
    for violation in violations:
        for prefix, section in mapping:
            if str(violation or "").startswith(prefix) and section not in selected:
                selected.append(section)
                break
    return [section for section in _SECTION_TITLES if section in selected]


def missing_bazi_sections(text: str) -> list[str]:
    return [section for section in _SECTION_TITLES if not _has_bazi_section_content(text, section)]


def _has_bazi_section_heading(text: str, section: str) -> bool:
    return bool(
        re.search(
            rf"(?m)^\s*(?:(?:#{{1,6}}\s*)"
            rf"(?:(?:[一二三四五六七八九十]+|\d+)[、.．]\s*)?|"
            rf"(?:(?:[一二三四五六七八九十]+|\d+)[、.．]\s*))"
            rf"(?:\*{{1,2}})?{re.escape(section)}(?:\*{{1,2}})?(?=\s|[（(:：]|$)",
            str(text or ""),
        )
    )


def _has_bazi_section_content(text: str, section: str) -> bool:
    if not _has_bazi_section_heading(text, section):
        return False
    rendered = section_text(text, section).strip()
    lines = rendered.splitlines()
    if len(lines) < 2:
        return False
    body = re.sub(r"[\s*_`#>\-•]+", "", "\n".join(lines[1:]))
    return len(body) >= 4


def bazi_repair_source_text(text: str, sections: list[str]) -> str:
    selected = [section_text(text, section).strip() for section in sections]
    rendered = "\n\n".join(item for item in selected if item)
    return rendered or str(text or "").strip()


def merge_bazi_repaired_sections(
    original_text: str,
    repaired_text: str,
    sections: list[str],
) -> str:
    merged = str(original_text or "")
    original_missing = set(missing_bazi_sections(merged))
    for section in sections:
        replacement = section_text(repaired_text, section).strip()
        span = _section_span(merged, section)
        if not replacement or span is None:
            continue
        candidate = f"{merged[:span[0]]}{replacement}\n\n{merged[span[1]:].lstrip()}"
        if set(missing_bazi_sections(candidate)) - original_missing:
            continue
        merged = candidate
    return merged.strip()


def _section_span(text: str, section: str) -> tuple[int, int] | None:
    start = _section_position(text, section)
    if start < 0:
        return None
    following = [
        start + 1 + position
        for title in _SECTION_TITLES
        if title != section
        and (position := _section_position(text[start + 1 :], title)) >= 0
    ]
    return start, min(following) if following else len(text)


def _has_invalid_peach_blossom_year(text: str, marriage: str) -> bool:
    natal_branches = _natal_branches(text)
    if len(natal_branches) < 3:
        return any(
            "桃花" in clause and _YEAR_PATTERN.search(clause)
            for clause in re.split(r"[；;。\n]", marriage)
        )
    peach_by_branch = {
        "寅": "卯", "午": "卯", "戌": "卯",
        "申": "酉", "子": "酉", "辰": "酉",
        "巳": "午", "酉": "午", "丑": "午",
        "亥": "子", "卯": "子", "未": "子",
    }
    expected = {peach_by_branch[natal_branches[2]]} if natal_branches[2] in peach_by_branch else set()
    for clause in re.split(r"[；;。\n]", marriage):
        if "桃花" not in clause:
            continue
        for year in _peach_blossom_claimed_years(clause):
            if _gregorian_year_branch(int(year)) not in expected:
                return True
    return False


def _peach_blossom_claimed_years(clause: str) -> list[str]:
    if clause.count("桃花") == 1 and re.search(
        r"(?:不|非|未|不能|不作|不算|并非).{0,12}桃花(?:年|年份|应期)?",
        clause,
    ):
        return []
    if re.search(r"桃花(?:年|年份|应期)", clause):
        return _YEAR_PATTERN.findall(clause)
    years: list[str] = []
    for segment in re.split(r"[、,，]", clause):
        if "桃花" in segment:
            years.extend(_YEAR_PATTERN.findall(segment))
    return years


def _uses_year_branch_combine_as_marriage_signal(marriage: str) -> bool:
    for clause in re.split(r"[；;。\n]", marriage):
        year_branch_combine = "合年支" in clause or bool(re.search(r"年支.{0,8}(?:相合|被合)", clause))
        marriage_claim = bool(re.search(r"恋爱|婚恋|结婚|夫妻宫|配偶", clause))
        spouse_palace_evidence = "日支" in clause or "夫妻宫" in clause
        if year_branch_combine and marriage_claim and not spouse_palace_evidence:
            return True
    return False


def _denies_natal_spouse_palace_clash(text: str, marriage: str) -> bool:
    branches = _natal_branches(text)
    if len(branches) != 4:
        return False
    day_branch = branches[2]
    has_clash = any(
        frozenset((day_branch, branch)) in _NATAL_BRANCH_CLASHES
        for index, branch in enumerate(branches)
        if index != 2
    )
    if not has_clash:
        return False
    return bool(
        re.search(
            r"(?:日支|夫妻宫).{0,20}(?:不是|并非|不属|没有|无|未见).{0,20}(?:冲|重冲)",
            marriage,
        )
    )


def _has_invalid_yearly_shensha_evidence(
    text: str,
    expected: tuple[tuple[int, str], ...],
) -> bool:
    if not expected:
        return False
    expected_pairs = set(expected)
    names = {name for _, name in expected}
    for line in str(text or "").splitlines():
        years = {int(year) for year in _YEAR_PATTERN.findall(line)}
        mentioned = {name for name in names if name in line}
        if not years or not mentioned:
            continue
        if not any((year, name) in expected_pairs for year in years for name in mentioned):
            return True
    return False


def _natal_branches(text: str) -> list[str]:
    match = re.search(r"地支\s*[：:]\s*(?P<branches>[^\n]+)", section_text(text, "命盘"))
    if match is None:
        return []
    return re.findall(r"[子丑寅卯辰巳午未申酉戌亥]", match.group("branches"))[:4]


def _gregorian_year_branch(year: int) -> str:
    return "子丑寅卯辰巳午未申酉戌亥"[(year - 1984) % 12]


def _section_position(text: str, section: str) -> int:
    match = re.search(
        rf"(?m)^\s*(?:#{{1,6}}\s*)?(?:\*{{1,2}})?"
        rf"(?:(?:[一二三四五六七八九十]+|\d+)[、.．]\s*)?"
        rf"{re.escape(section)}(?:\*{{1,2}})?(?=\s|[（(:：]|$)",
        text,
    )
    return match.start() if match is not None else -1
