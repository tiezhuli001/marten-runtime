from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from marten_runtime.runtime.llm_provider_support import (
    collapse_system_messages as _collapse_system_messages,
    resolve_parameters_schema as _resolve_parameters_schema,
)
from marten_runtime.runtime.capabilities import (
    get_capability_declarations as _get_capability_declarations,
    render_capability_catalog_for_request as _render_capability_catalog_for_request,
    render_tool_description_for_provider as _render_tool_description_for_provider,
)
from marten_runtime.runtime.llm_request_instructions import (
    request_specific_instruction as _request_specific_instruction,
    tool_followup_instruction as _tool_followup_instruction,
)

if TYPE_CHECKING:
    from marten_runtime.runtime.llm_client import (
        FinalizationEvidenceItem,
        FinalizationEvidenceLedger,
        LLMRequest,
        ToolExchange,
    )


def build_openai_messages(request: "LLMRequest") -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    is_tool_followup = bool(request.tool_history) or (
        request.tool_result is not None and bool(request.requested_tool_name)
    )
    is_session_summary = request.request_kind == "session_summary"
    include_capability_catalog = (
        bool(request.capability_catalog_text)
        and not is_tool_followup
        and request.request_kind != "contract_repair"
    )
    capability_catalog_text = request.capability_catalog_text
    if include_capability_catalog:
        capability_catalog_text = _compact_capability_catalog_for_request(request)
    _append_system_message(messages, request.system_prompt)
    if not is_tool_followup:
        _append_system_message(messages, request.skill_heads_text)
    if include_capability_catalog:
        _append_system_message(messages, capability_catalog_text)
    _append_system_message(messages, request.always_on_skill_text)
    _append_system_message(messages, request.repository_context_text)
    _append_system_message(messages, request.compact_summary_text)
    _append_system_message(messages, request.tool_outcome_summary_text)
    _append_system_message(messages, request.memory_text)
    _append_system_message(messages, request.working_context_text)
    if not is_session_summary:
        _append_system_message(messages, _request_specific_instruction(request))
    _append_system_message(
        messages,
        render_finalization_evidence_ledger_block(
            request.finalization_evidence_ledger
            if (is_tool_followup or request.request_kind == "finalization_retry")
            else None
        ),
    )
    _append_system_message(
        messages,
        _tool_followup_instruction(
            request.requested_tool_name,
            tool_history_count=len(request.tool_history),
            has_evidence_ledger=request.finalization_evidence_ledger is not None,
            required_evidence_count=sum(
                1
                for item in (request.finalization_evidence_ledger.items if request.finalization_evidence_ledger else [])
                if item.required_for_user_request
            ),
        ),
    )
    for body in request.activated_skill_bodies:
        _append_system_message(messages, body)
    for item in request.conversation_messages:
        messages.append({"role": item.role, "content": item.content})
    messages.append({"role": "user", "content": request.message})
    tool_history = _tool_history_for_request(request)
    bazi_pillars = _bazi_pillars_from_history(tool_history)
    bazi_pillar_ten_gods = _bazi_pillar_ten_gods_from_history(tool_history)
    for index, item in enumerate(tool_history, start=1):
        call_id = f"call_{index}"
        messages.append(_assistant_tool_call_message(item, call_id))
        messages.append(
            _tool_result_message(
                item,
                call_id,
                bazi_pillars=bazi_pillars,
                bazi_pillar_ten_gods=bazi_pillar_ten_gods,
                request_kind=request.request_kind,
            )
        )
    return _collapse_system_messages(messages)


def build_openai_chat_payload(
    model_name: str, request: "LLMRequest"
) -> dict[str, object]:
    body: dict[str, object] = {
        "model": model_name,
        "messages": build_openai_messages(request),
    }
    if (
        str(model_name).lower().startswith("gpt-5")
        and request.agent_id == "bazi"
        and request.request_kind in {"finalization_retry", "bazi_output_repair"}
    ):
        body["reasoning_effort"] = "low"
        body["max_completion_tokens"] = (
            1200 if request.request_kind == "bazi_output_repair" else 2500
        )
    tool_definitions = build_tool_definitions(request)
    if tool_definitions:
        body["tools"] = tool_definitions
        body["tool_choice"] = build_openai_tool_choice(
            request,
            responses_api=False,
        ) or "auto"
    return body


def build_tool_definitions(request: "LLMRequest") -> list[dict[str, object]]:
    if request.request_kind == "finalization_retry":
        return []
    tool_names = list(request.available_tools)
    forced_tool_name = _forced_initial_tool_name(request)
    if forced_tool_name:
        tool_names = [tool_name for tool_name in tool_names if tool_name == forced_tool_name]
    return [
        {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": _tool_description_for_provider(tool_name, request),
                "parameters": _tool_parameters_schema_for_provider(tool_name, request),
            },
        }
        for tool_name in tool_names
    ]


def _append_system_message(
    messages: list[dict[str, object]], content: str | None
) -> None:
    if content:
        messages.append({"role": "system", "content": content})


def render_finalization_evidence_ledger_block(
    ledger: "FinalizationEvidenceLedger" | None,
) -> str | None:
    if ledger is None or not ledger.items:
        return None
    lines = [
        "Current-turn evidence ledger:",
        f"- tool_call_count={ledger.tool_call_count}",
    ]
    if ledger.model_request_count is not None:
        lines.append(f"- model_request_count={ledger.model_request_count}")
    lines.append(
        "- requires_result_coverage={value}".format(
            value="yes" if ledger.requires_result_coverage else "no"
        )
    )
    lines.append(
        "- requires_round_trip_report={value}".format(
            value="yes" if ledger.requires_round_trip_report else "no"
        )
    )
    lines.append("- evidence_items:")
    for item in ledger.items:
        lines.append(_render_finalization_evidence_item(item))
    return "\n".join(lines)


def _tool_history_for_request(request: "LLMRequest") -> list["ToolExchange"]:
    if request.request_kind == "finalization_retry":
        ledger = request.finalization_evidence_ledger
        if (
            str(request.compact_summary_text or "").strip()
            and ledger is not None
            and not any(item.required_for_user_request for item in ledger.items)
        ):
            return []
    tool_history = list(request.tool_history)
    if tool_history or request.tool_result is None or not request.requested_tool_name:
        return tool_history
    from marten_runtime.runtime.llm_client import ToolExchange

    tool_history.append(
        ToolExchange(
            tool_name=request.requested_tool_name,
            tool_payload=request.requested_tool_payload,
            tool_result=request.tool_result,
        )
    )
    return tool_history


def _render_finalization_evidence_item(item: "FinalizationEvidenceItem") -> str:
    parts = [
        f"{item.ordinal}. tool={item.tool_name}",
        f"required={'yes' if item.required_for_user_request else 'no'}",
        f"source={item.evidence_source}",
    ]
    if item.tool_action:
        parts.append(f"action={item.tool_action}")
    if item.payload_summary:
        parts.append(f"payload={_truncate_ledger_text(item.payload_summary, limit=80)}")
    parts.append(f"result={_truncate_ledger_text(item.result_summary, limit=180)}")
    return "- " + " | ".join(parts)


def _truncate_ledger_text(text: str | None, *, limit: int) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _assistant_tool_call_message(
    item: "ToolExchange", call_id: str
) -> dict[str, object]:
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": item.tool_name,
                    "arguments": json.dumps(item.tool_payload, ensure_ascii=True),
                },
            }
        ],
    }


def _tool_result_message(
    item: "ToolExchange",
    call_id: str,
    *,
    bazi_pillars: list[str] | None = None,
    bazi_pillar_ten_gods: list[str] | None = None,
    request_kind: str = "",
) -> dict[str, object]:
    serialization_options: dict[str, int] = {}
    if (
        item.tool_name == "knowledge"
        and str(item.tool_payload.get("action") or item.tool_result.get("action") or "").strip()
        == "search"
        and str(item.tool_payload.get("namespace") or item.tool_result.get("namespace") or "").strip()
        == "bazi-theory"
    ):
        serialization_options["content_item_limit"] = 10
    serialized_result = _serialize_tool_result_for_provider(
        item.tool_result,
        **serialization_options,
    )
    if item.tool_name == "bazi":
        serialized_result = _restore_compact_bazi_facts(
            item.tool_result,
            serialized_result,
            action=str(
                item.tool_payload.get("action")
                or item.tool_result.get("action")
                or ""
            ).strip(),
            pillars=bazi_pillars,
            pillar_ten_gods=bazi_pillar_ten_gods,
            gender=str(item.tool_payload.get("gender") or "").strip(),
        )
        if request_kind == "finalization_retry":
            serialized_result = _compact_bazi_finalization_result(serialized_result)
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(
            serialized_result,
            ensure_ascii=True,
        ),
    }


def _compact_bazi_finalization_result(serialized_result: object) -> object:
    if not isinstance(serialized_result, dict):
        return serialized_result
    payload = serialized_result.get("result")
    if not isinstance(payload, dict):
        return serialized_result
    structural_summary = payload.get("成年后结构组合摘要")
    timing_years = payload.get("应期逐年表")
    if isinstance(structural_summary, list) and isinstance(timing_years, list):
        selected_years = {
            item.get("流年")
            for item in structural_summary
            if isinstance(item, dict) and item.get("流年") is not None
        }
        payload["应期逐年表"] = [
            item
            for item in timing_years
            if isinstance(item, dict) and item.get("流年") in selected_years
        ]
    payload.pop("小运", None)
    return serialized_result


def _restore_compact_bazi_facts(
    raw_result: dict[str, object],
    serialized_result: object,
    *,
    action: str,
    pillars: list[str] | None = None,
    pillar_ten_gods: list[str] | None = None,
    gender: str = "",
) -> object:
    if not isinstance(serialized_result, dict):
        return serialized_result
    raw_payload = raw_result.get("result")
    serialized_payload = serialized_result.get("result")
    if not isinstance(raw_payload, dict) or not isinstance(serialized_payload, dict):
        return serialized_result
    if action == "chart":
        pillars = raw_payload.get("四柱")
        if isinstance(pillars, list):
            serialized_payload["四柱"] = [
                _serialize_tool_result_for_provider(item, content_item_limit=3)
                for item in pillars[:4]
            ]
            serialized_payload.pop("四柱_truncated_count", None)
    if action == "dayun":
        cycles = raw_payload.get("大运列表")
        if isinstance(cycles, list):
            serialized_payload["大运列表"] = [
                _compact_bazi_cycle(item, pillars or [])
                for item in cycles
                if isinstance(item, dict)
            ]
            serialized_payload.pop("大运列表_truncated_count", None)
            timing_years = _compact_bazi_timing_years(
                cycles,
                pillars=pillars,
                pillar_ten_gods=pillar_ten_gods,
                gender=gender,
                include_event_candidates=True,
            )
            structural_summary = _compact_bazi_structural_summary(timing_years)
            if structural_summary:
                serialized_payload["成年后结构组合摘要"] = structural_summary
            for timing_year in timing_years:
                timing_year.pop("候选归属", None)
            serialized_payload["应期逐年表"] = timing_years
    return serialized_result


def _compact_bazi_cycle(
    cycle: dict[str, object],
    pillars: list[str],
) -> dict[str, object]:
    compact = {
        field: cycle[field]
        for field in ("起运年份", "起运年龄", "干支", "十神")
        if field in cycle
    }
    stem_relations, repeated_branches = _annual_relation_hints(
        str(cycle.get("干支") or "").strip(),
        "",
        pillars,
    )
    if stem_relations:
        compact["天干作用"] = [
            relation.replace("流年干", "大运干")
            for relation in stem_relations
        ]
    if repeated_branches:
        compact["同支伏吟"] = repeated_branches
    return compact


def _compact_bazi_timing_years(
    cycles: list[object],
    *,
    current_year: int | None = None,
    pillars: list[str] | None = None,
    pillar_ten_gods: list[str] | None = None,
    gender: str = "",
    include_event_candidates: bool = False,
) -> list[dict[str, object]]:
    end_year = (
        datetime.now(ZoneInfo("Asia/Shanghai")).year
        if current_year is None
        else current_year
    )
    timing_years: list[dict[str, object]] = []
    key_shensha = {"桃花", "驿马", "红鸾", "天喜", "血刃", "白虎"}
    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        dayun = str(cycle.get("干支") or "").strip()
        dayun_ten_god = str(cycle.get("十神") or "").strip()
        annual_items = cycle.get("流年列表")
        if not isinstance(annual_items, list):
            continue
        for annual in annual_items:
            if not isinstance(annual, dict):
                continue
            year = annual.get("流年")
            if isinstance(year, bool) or not isinstance(year, int) or year > end_year:
                continue
            compact: dict[str, object] = {
                field: annual[field]
                for field in ("流年", "年龄", "干支", "十神")
                if field in annual
            }
            if dayun:
                compact["所在大运"] = dayun
            if dayun_ten_god:
                compact["大运十神"] = dayun_ten_god
            relations = [
                str(item.get("描述") or "").strip()
                for item in annual.get("原局关系") or []
                if isinstance(item, dict) and str(item.get("描述") or "").strip()
            ]
            if relations:
                compact["作用关系"] = relations
            stem_relations, repeated_branches = _annual_relation_hints(
                str(annual.get("干支") or "").strip(),
                dayun,
                pillars or [],
            )
            if stem_relations:
                compact["天干作用"] = stem_relations
            if repeated_branches:
                compact["同支伏吟"] = repeated_branches
            structure_hints = _annual_structure_hints(
                annual_ten_god=str(annual.get("十神") or "").strip(),
                dayun_ten_god=dayun_ten_god,
                dayun_pillar=dayun,
                pillars=pillars or [],
                pillar_ten_gods=pillar_ten_gods or [],
                stem_relations=stem_relations,
                branch_relations=relations,
                repeated_branches=repeated_branches,
            )
            if structure_hints:
                compact["结构组合"] = structure_hints
            shensha = [
                str(item).strip()
                for item in annual.get("神煞") or []
                if str(item).strip() in key_shensha
            ]
            if shensha:
                compact["关键神煞"] = shensha
            event_candidates = _annual_event_candidates(
                annual_ten_god=str(annual.get("十神") or "").strip(),
                dayun_ten_god=dayun_ten_god,
                gender=gender,
                pillar_ten_gods=pillar_ten_gods or [],
                stem_relations=stem_relations,
                branch_relations=relations,
                repeated_branches=repeated_branches,
                structure_hints=structure_hints,
                shensha=shensha,
            )
            if event_candidates and include_event_candidates:
                compact["候选归属"] = event_candidates
            timing_years.append(compact)
    return timing_years


def _compact_bazi_structural_summary(
    timing_years: list[dict[str, object]],
    *,
    limit: int = 40,
) -> list[dict[str, object]]:
    candidates = [
        {
            field: item[field]
            for field in ("流年", "年龄", "干支", "所在大运", "结构组合", "候选归属")
            if field in item
        }
        for item in timing_years
        if isinstance(item.get("年龄"), int)
        and item["年龄"] >= 18
        and (item.get("结构组合") or item.get("候选归属"))
    ]
    ranked = sorted(
        candidates,
        key=lambda item: (
            len(item.get("候选归属") or []) * 3 + len(item.get("结构组合") or []) * 2,
            int(item.get("流年") or 0),
        ),
        reverse=True,
    )[:limit]
    return sorted(ranked, key=lambda item: int(item.get("流年") or 0))


def _bazi_pillars_from_history(tool_history: list["ToolExchange"]) -> list[str] | None:
    pillar_names = ("年柱", "月柱", "日柱", "时柱")
    payload_names = ("yearPillar", "monthPillar", "dayPillar", "hourPillar")
    for exchange in tool_history:
        if exchange.tool_name != "bazi" or exchange.tool_result.get("ok") is not True:
            continue
        result = exchange.tool_result.get("result")
        if isinstance(result, dict):
            raw_pillars = result.get("四柱")
            if isinstance(raw_pillars, list):
                values = [
                    str(item.get("干支") if isinstance(item, dict) else item or "").strip()
                    for item in raw_pillars[:4]
                ]
                if len(values) == 4 and all(len(item) >= 2 for item in values):
                    return values
            original = result.get("原始四柱")
            if isinstance(original, dict):
                values = [str(original.get(name) or "").strip() for name in pillar_names]
                if all(len(item) >= 2 for item in values):
                    return values
        values = [str(exchange.tool_payload.get(name) or "").strip() for name in payload_names]
        if all(len(item) >= 2 for item in values):
            return values
    return None


def _bazi_pillar_ten_gods_from_history(
    tool_history: list["ToolExchange"],
) -> list[str] | None:
    for exchange in tool_history:
        if exchange.tool_name != "bazi" or exchange.tool_result.get("ok") is not True:
            continue
        result = exchange.tool_result.get("result")
        raw_pillars = result.get("四柱") if isinstance(result, dict) else None
        if not isinstance(raw_pillars, list):
            continue
        values = [
            str(item.get("天干十神") or "").strip() if isinstance(item, dict) else ""
            for item in raw_pillars[:4]
        ]
        if len(values) == 4 and any(values):
            return values
    pillars = _bazi_pillars_from_history(tool_history)
    if pillars is None:
        return None
    day_stem = pillars[2][0]
    return [
        _ten_god_for_stem(day_stem, pillar[0]) if index != 2 else "-"
        for index, pillar in enumerate(pillars)
    ]


_STEM_ELEMENT = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}
_YANG_STEMS = {"甲", "丙", "戊", "庚", "壬"}
_CONTROLS = {("木", "土"), ("土", "水"), ("水", "火"), ("火", "金"), ("金", "木")}
_STEM_COMBINES = {frozenset(pair) for pair in (("甲", "己"), ("乙", "庚"), ("丙", "辛"), ("丁", "壬"), ("戊", "癸"))}


def _ten_god_for_stem(day_stem: str, target_stem: str) -> str:
    day_element = _STEM_ELEMENT.get(day_stem)
    target_element = _STEM_ELEMENT.get(target_stem)
    if day_element is None or target_element is None:
        return ""
    same_polarity = (day_stem in _YANG_STEMS) == (target_stem in _YANG_STEMS)
    if day_element == target_element:
        return "比肩" if same_polarity else "劫财"
    if (day_element, target_element) in _CONTROLS:
        return "偏财" if same_polarity else "正财"
    if (target_element, day_element) in _CONTROLS:
        return "七杀" if same_polarity else "正官"
    generates = {("木", "火"), ("火", "土"), ("土", "金"), ("金", "水"), ("水", "木")}
    if (day_element, target_element) in generates:
        return "食神" if same_polarity else "伤官"
    if (target_element, day_element) in generates:
        return "偏印" if same_polarity else "正印"
    return ""


def _annual_relation_hints(
    annual_pillar: str,
    dayun_pillar: str,
    pillars: list[str],
) -> tuple[list[str], list[str]]:
    if len(annual_pillar) < 2:
        return [], []
    annual_stem, annual_branch = annual_pillar[0], annual_pillar[1]
    labels = ("年", "月", "日", "时")
    stem_targets = [
        (pillar[0], f"{label}干")
        for label, pillar in zip(labels, pillars, strict=False)
        if len(pillar) >= 2
    ]
    branch_targets = [
        (pillar[1], f"{label}支")
        for label, pillar in zip(labels, pillars, strict=False)
        if len(pillar) >= 2
    ]
    if len(dayun_pillar) >= 2:
        stem_targets.append((dayun_pillar[0], "大运干"))
        branch_targets.append((dayun_pillar[1], "大运支"))

    stem_relations: list[str] = []
    for target_stem, target_label in stem_targets:
        if annual_stem == target_stem:
            stem_relations.append(f"{annual_stem}伏吟{target_label}")
            continue
        if frozenset((annual_stem, target_stem)) in _STEM_COMBINES:
            stem_relations.append(f"{annual_stem}{target_stem}合（流年干合{target_label}）")
            continue
        annual_element = _STEM_ELEMENT.get(annual_stem)
        target_element = _STEM_ELEMENT.get(target_stem)
        if (annual_element, target_element) in _CONTROLS:
            stem_relations.append(f"{annual_stem}克{target_stem}（流年干克{target_label}）")
        elif (target_element, annual_element) in _CONTROLS:
            stem_relations.append(f"{target_stem}克{annual_stem}（{target_label}克流年干）")

    repeated_branches = [
        f"{annual_branch}伏吟{target_label}"
        for target_branch, target_label in branch_targets
        if annual_branch == target_branch
    ]
    return stem_relations, repeated_branches


def _annual_event_candidates(
    *,
    annual_ten_god: str,
    dayun_ten_god: str,
    gender: str,
    pillar_ten_gods: list[str],
    stem_relations: list[str],
    branch_relations: list[str],
    repeated_branches: list[str],
    structure_hints: list[str],
    shensha: list[str],
) -> list[str]:
    """Return compact evidence-based domains; the model still performs final interpretation."""
    stem_text = " ".join(stem_relations)
    branch_text = " ".join([*branch_relations, *repeated_branches])
    structure_text = " ".join(structure_hints)
    ten_gods = [*pillar_ten_gods, "", "", "", ""]
    candidates: list[tuple[int, str]] = []

    day_branch_hit = any(label in branch_text for label in ("日柱", "日支"))
    hour_branch_hit = any(label in branch_text for label in ("时柱", "时支"))
    year_branch_hit = any(label in branch_text for label in ("年柱", "年支"))
    month_branch_hit = any(label in branch_text for label in ("月柱", "月支"))
    direct_day_control = "流年干克日干" in stem_text

    if direct_day_control and (day_branch_hit or hour_branch_hit):
        candidates.append((4, "本人健康/检查（流年克日主，日时宫同步引动）"))

    year_stem_relation = any(
        marker in item
        for item in stem_relations
        for marker in ("流年干克年干", "流年干合年干", "伏吟年干")
    )
    if year_stem_relation and year_branch_hit:
        parent = _parent_label_for_ten_god(ten_gods[0])
        if parent:
            candidates.append((5, f"{parent}事务/健康（父母星与年柱同动）"))
        else:
            candidates.append((3, "父母家宅（年干与年支同动）"))

    dayun_hits_year_stem = "大运" in structure_text and "年干" in structure_text
    if dayun_hits_year_stem:
        parent = _parent_label_for_ten_god(ten_gods[0])
        candidates.append(
            (
                4,
                f"{parent or '父母'}事务待核验（大运作用父母星，流年多宫引动；缺少流年干直接作用时不单独定健康）",
            )
        )

    if "年支伏吟叠加其他柱位" in structure_text:
        candidates.append((5, "房屋/搬迁/工作环境变动（年支伏吟叠加其他宫位受作用）"))
    elif (
        ("冲年支" in branch_text or ("相冲" in branch_text and "年柱" in branch_text))
        and hour_branch_hit
    ):
        candidates.append((5, "房屋/搬迁/工作环境变动（年支受冲且时支同步引动）"))

    if month_branch_hit or "月干" in stem_text:
        score = 4 if annual_ten_god in {"正官", "七杀", "正印", "偏印", "食神", "伤官"} else 3
        candidates.append((score, "事业/岗位平台变动（月柱或职业十神受作用）"))
    elif (
        dayun_ten_god in {"正官", "七杀"}
        and len(stem_relations) >= 2
        and bool(branch_relations or repeated_branches)
    ):
        candidates.append((4, "事业/岗位平台变动（官杀大运中天干多处作用并引动地支）"))

    spouse_stars = {"偏财", "正财"} if gender == "male" else {"正官", "七杀"}
    relationship_evidence = int(annual_ten_god in spouse_stars) + int("桃花" in shensha) + int(day_branch_hit)
    if relationship_evidence >= 2:
        candidates.append((relationship_evidence + 2, "恋爱婚姻（配偶星、桃花、夫妻宫至少两项同动）"))

    ordered = sorted(candidates, key=lambda item: (-item[0], item[1]))
    return list(dict.fromkeys(label for _, label in ordered))[:4]


def _parent_label_for_ten_god(ten_god: str) -> str:
    if ten_god == "偏财":
        return "父亲"
    if ten_god == "正印":
        return "母亲"
    return ""


def _annual_structure_hints(
    *,
    annual_ten_god: str,
    dayun_ten_god: str,
    dayun_pillar: str,
    pillars: list[str],
    pillar_ten_gods: list[str],
    stem_relations: list[str],
    branch_relations: list[str],
    repeated_branches: list[str],
) -> list[str]:
    hints: list[str] = []
    branch_text = " ".join([*branch_relations, *repeated_branches])
    ten_gods = [*pillar_ten_gods, "", "", "", ""]

    year_stem_hit = next(
        (item for item in stem_relations if "年干" in item),
        "",
    )
    if year_stem_hit and ("年柱" in branch_text or "年支" in branch_text):
        target_ten_god = ten_gods[0]
        target = f"年干{target_ten_god}" if target_ten_god and target_ten_god != "-" else "年干"
        relation = year_stem_hit.split("（", 1)[0]
        hints.append(f"流年{annual_ten_god}与{target}、年支同步引动；天干关系：{relation}")

    if "年支" in " ".join(repeated_branches) and any(
        label in " ".join(branch_relations)
        for label in ("月柱", "日柱", "时柱")
    ):
        hints.append("年支伏吟叠加其他柱位受合冲刑害")

    day_stem_controlled = any("流年干克日干" in item for item in stem_relations)
    day_or_hour_branch_hit = any(
        label in branch_text
        for label in ("日柱", "时柱", "日支", "时支")
    )
    if day_stem_controlled and day_or_hour_branch_hit:
        hints.append(f"流年{annual_ten_god}克日干，日支或时支同步引动")

    month_stem_controlled = any("流年干克月干" in item for item in stem_relations)
    month_day_repeated = all(
        label in " ".join(repeated_branches)
        for label in ("月支", "日支")
    )
    if month_stem_controlled and ten_gods[1] and ten_gods[1] != "-":
        suffix = "，月日支伏吟" if month_day_repeated else ""
        hints.append(f"流年{annual_ten_god}克月干{ten_gods[1]}{suffix}")

    dayun_relations, _ = _annual_relation_hints(dayun_pillar, "", pillars)
    dayun_year_stem_control = next(
        (item for item in dayun_relations if "大运干克年干" in item.replace("流年干", "大运干")),
        "",
    )
    if dayun_year_stem_control and ten_gods[0] and ten_gods[0] != "-":
        activated_pillars = {
            label
            for label in ("年柱", "年支", "月柱", "月支", "日柱", "日支", "时柱", "时支")
            if label in branch_text
        }
        if len(activated_pillars) >= 2:
            hints.append(f"大运{dayun_ten_god}克年干{ten_gods[0]}，流年支多处引动")
    return list(dict.fromkeys(hints))


def _serialize_tool_result_for_provider(
    tool_result: object,
    *,
    text_limit: int = 1600,
    content_item_limit: int = 2,
) -> object:
    if isinstance(tool_result, dict):
        if _is_successful_github_file_content_result(tool_result):
            text_limit = max(text_limit, 12000)
            content_item_limit = max(content_item_limit, 6)
        if _is_mcp_discovery_result(tool_result):
            content_item_limit = max(content_item_limit, 80)
        serialized: dict[str, object] = {}
        for key, value in tool_result.items():
            if key == "content" and isinstance(value, list):
                trimmed_items: list[object] = []
                for item in value[:content_item_limit]:
                    trimmed_items.append(
                        _serialize_tool_result_for_provider(
                            item,
                            text_limit=text_limit,
                            content_item_limit=content_item_limit,
                        )
                    )
                if len(value) > content_item_limit:
                    trimmed_items.append({"type": "truncated", "omitted_items": len(value) - content_item_limit})
                serialized[key] = trimmed_items
                continue
            if key in {"result_text", "text", "message"} and isinstance(value, str):
                serialized[key] = _truncate_ledger_text(value, limit=text_limit)
                continue
            if isinstance(value, str):
                serialized[key] = _truncate_ledger_text(value, limit=text_limit)
                continue
            if isinstance(value, dict):
                serialized[key] = _serialize_tool_result_for_provider(
                    value,
                    text_limit=text_limit,
                    content_item_limit=content_item_limit,
                )
                continue
            if isinstance(value, list):
                serialized[key] = [
                    _serialize_tool_result_for_provider(
                        item,
                        text_limit=text_limit,
                        content_item_limit=content_item_limit,
                    )
                    for item in value[:content_item_limit]
                ]
                if len(value) > content_item_limit:
                    serialized[f"{key}_truncated_count"] = len(value) - content_item_limit
                continue
            serialized[key] = value
        return serialized
    if isinstance(tool_result, list):
        trimmed = [
            _serialize_tool_result_for_provider(
                item,
                text_limit=text_limit,
                content_item_limit=content_item_limit,
            )
            for item in tool_result[:content_item_limit]
        ]
        if len(tool_result) > content_item_limit:
            trimmed.append({"omitted_items": len(tool_result) - content_item_limit})
        return trimmed
    if isinstance(tool_result, str):
        return _truncate_ledger_text(tool_result, limit=text_limit)
    return tool_result


def _is_successful_github_file_content_result(tool_result: dict[str, object]) -> bool:
    return (
        str(tool_result.get("action") or "").strip() == "call"
        and str(tool_result.get("server_id") or "").strip() == "github"
        and str(tool_result.get("tool_name") or "").strip() == "get_file_contents"
        and bool(tool_result.get("ok", True))
        and not bool(tool_result.get("is_error"))
    )


def _is_mcp_discovery_result(tool_result: dict[str, object]) -> bool:
    return str(tool_result.get("action") or "").strip() in {"list", "detail"}


def _tool_description(tool_name: str, request: "LLMRequest") -> str:
    metadata = request.tool_snapshot.tool_metadata.get(tool_name, {})
    if isinstance(metadata, Mapping):
        return str(metadata.get("description", ""))
    return ""


def _tool_description_for_provider(tool_name: str, request: "LLMRequest") -> str:
    declarations = _get_capability_declarations()
    declaration = declarations.get(tool_name)
    if declaration is not None:
        return _render_tool_description_for_provider(declaration)
    return _tool_description(tool_name, request)


def _forced_initial_tool_name(request: "LLMRequest") -> str | None:
    if (
        request.tool_history or request.tool_result is not None
    ) and request.request_kind not in {"bazi_dayun_repair", "bazi_knowledge_search"}:
        return None
    forced = str(request.requested_tool_name or "").strip()
    if not forced:
        return None
    return forced


def resolve_required_initial_tool_name(request: "LLMRequest") -> str | None:
    forced_tool_name = _forced_initial_tool_name(request)
    if forced_tool_name:
        return forced_tool_name
    return None


def build_openai_tool_choice(
    request: "LLMRequest",
    *,
    responses_api: bool,
) -> dict[str, object] | None:
    required_tool_name = resolve_required_initial_tool_name(request)
    if not required_tool_name:
        return None
    if responses_api:
        return {"type": "function", "name": required_tool_name}
    return {"type": "function", "function": {"name": required_tool_name}}


def _tool_parameters_schema(tool_name: str, request: "LLMRequest") -> dict[str, object]:
    schema = _resolve_parameters_schema(tool_name, request.tool_snapshot)
    if tool_name == "bazi" and request.request_kind == "bazi_dayun_repair":
        return _exact_payload_parameters_schema(request.requested_tool_payload)
    if tool_name == "knowledge" and request.request_kind == "bazi_knowledge_search":
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "const": "search"},
                "namespace": {"type": "string", "const": "bazi-theory"},
                "query": {"type": "string", "minLength": 1},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["action", "namespace", "query"],
            "additionalProperties": False,
        }
    if tool_name != "session":
        return schema
    if _forced_initial_tool_name(request) != "session":
        return schema
    return _forced_session_parameters_schema(schema, request.requested_tool_payload)


def _exact_payload_parameters_schema(payload: Mapping[str, object]) -> dict[str, object]:
    properties: dict[str, object] = {}
    for key, value in payload.items():
        value_type = "boolean" if isinstance(value, bool) else None
        if value_type is None and isinstance(value, int):
            value_type = "integer"
        if value_type is None and isinstance(value, float):
            value_type = "number"
        if value_type is None and isinstance(value, str):
            value_type = "string"
        property_schema: dict[str, object] = {"const": value}
        if value_type is not None:
            property_schema["type"] = value_type
        properties[str(key)] = property_schema
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _tool_parameters_schema_for_provider(
    tool_name: str,
    request: "LLMRequest",
) -> dict[str, object]:
    schema = _tool_parameters_schema(tool_name, request)
    strip_composition = tool_name == "memory"
    return _normalize_provider_schema(
        _strip_schema_descriptions(schema, strip_composition=strip_composition)
    )


def _strip_schema_descriptions(schema: object, *, strip_composition: bool = False) -> object:
    if isinstance(schema, dict):
        cleaned: dict[str, object] = {}
        for key, value in schema.items():
            if key in {"description", "title", "examples", "default"}:
                continue
            if strip_composition and key in {"allOf", "anyOf", "oneOf", "if", "then", "else"}:
                continue
            cleaned[key] = _strip_schema_descriptions(
                value, strip_composition=strip_composition
            )
        return cleaned
    if isinstance(schema, list):
        return [
            _strip_schema_descriptions(item, strip_composition=strip_composition)
            for item in schema
        ]
    return schema


def _normalize_provider_schema(schema: object) -> object:
    if isinstance(schema, dict):
        normalized = {key: _normalize_provider_schema(value) for key, value in schema.items()}
        if str(normalized.get("type") or "") == "object":
            properties = normalized.get("properties")
            if not isinstance(properties, dict):
                normalized["properties"] = {}
        return normalized
    if isinstance(schema, list):
        return [_normalize_provider_schema(item) for item in schema]
    return schema


def _compact_capability_catalog_for_request(request: "LLMRequest") -> str | None:
    declarations = _get_capability_declarations()
    source_text = str(request.capability_catalog_text or "")
    if "Global rule:" not in source_text:
        return source_text or None
    mcp_catalog_text = None
    marker = "MCP family contract:"
    if marker in source_text:
        mcp_catalog_text = source_text.split(marker, 1)[1]
        mcp_catalog_text = marker + mcp_catalog_text
    return _render_capability_catalog_for_request(
        declarations,
        available_tools=request.available_tools,
        mcp_catalog_text=mcp_catalog_text,
    )


def _forced_session_parameters_schema(
    schema: dict[str, object],
    payload: Mapping[str, object],
) -> dict[str, object]:
    narrowed = copy.deepcopy(schema)
    properties = narrowed.setdefault("properties", {})
    if not isinstance(properties, dict):
        return narrowed
    required = list(narrowed.get("required", []))
    action = str(payload.get("action") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    if action:
        action_schema = dict(properties.get("action") or {})
        action_schema["type"] = "string"
        action_schema["enum"] = [action]
        properties["action"] = action_schema
        if "action" not in required:
            required.append("action")
    if session_id:
        session_schema = dict(properties.get("session_id") or {})
        session_schema["type"] = "string"
        session_schema["enum"] = [session_id]
        properties["session_id"] = session_schema
        if "session_id" not in required:
            required.append("session_id")
    narrowed["required"] = required
    return narrowed
