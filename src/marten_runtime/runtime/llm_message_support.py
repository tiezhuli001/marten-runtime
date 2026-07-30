from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from marten_runtime.bazi.timing_relations import natal_branch_dynamics, timing_relation_facts

from marten_runtime.runtime.llm_provider_support import (
    collapse_system_messages as _collapse_system_messages,
    resolve_parameters_schema as _resolve_parameters_schema,
)

_BAZI_TIMING_DAYUN_LIMIT = 6
_BAZI_TIMING_YEARS_PER_DAYUN = 10
_BAZI_VERIFICATION_INDEXED_YEAR_LIMIT = 16


@dataclass(frozen=True)
class BaziTimingFact:
    fact_id: str
    layer: str
    kind: str
    text: str
    year: int | None = None
    year_start: int | None = None
    year_end: int | None = None

    def as_provider_record(self, *, compact: bool = False) -> dict[str, object]:
        record: dict[str, object] = {
            "id": self.fact_id,
            "layer": self.layer,
            "kind": self.kind,
            "text": self.text,
        }
        if not compact and self.year is not None:
            record["year"] = self.year
        if not compact and self.year_start is not None:
            record["year_start"] = self.year_start
        if not compact and self.year_end is not None:
            record["year_end"] = self.year_end
        return record
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
            if (
                is_tool_followup
                or request.request_kind
                in {
                    "finalization_retry",
                    "bazi_final_generation",
                    "bazi_analysis_draft_repair",
                    "bazi_verification_event_repair",
                }
            )
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
    if request.max_completion_tokens is not None:
        body["max_completion_tokens"] = request.max_completion_tokens
    if request.response_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.response_schema_name or "structured_response",
                "strict": True,
                "schema": request.response_schema,
            },
        }
    if (
        str(model_name).lower().startswith("gpt-5")
        and request.agent_id == "bazi"
        and request.request_kind
        in {
            "finalization_retry",
            "bazi_final_generation",
            "bazi_analysis_draft_repair",
            "bazi_output_repair",
            "bazi_output_semantic_review",
            "bazi_verification_event_repair",
        }
    ):
        body["reasoning_effort"] = "low"
        body["max_completion_tokens"] = (
            500
            if request.request_kind == "bazi_output_semantic_review"
            else 1600
            if request.request_kind == "bazi_verification_event_repair"
            else 1200
            if request.request_kind == "bazi_output_repair"
            else 3400
            if request.request_kind
            in {"bazi_final_generation", "bazi_analysis_draft_repair"}
            else 2500
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
    if request.request_kind in {
        "finalization_retry",
        "bazi_final_generation",
        "bazi_analysis_draft_repair",
        "bazi_verification_event_repair",
    }:
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
                    "arguments": json.dumps(
                        item.tool_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
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
        if request_kind in {
            "finalization_retry",
            "bazi_final_generation",
            "bazi_analysis_draft_repair",
            "bazi_verification_event_repair",
        }:
            serialized_result = _compact_bazi_finalization_result(serialized_result)
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(
            serialized_result,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }


def _compact_bazi_finalization_result(serialized_result: object) -> object:
    if not isinstance(serialized_result, dict):
        return serialized_result
    payload = serialized_result.get("result")
    if not isinstance(payload, dict):
        return serialized_result
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
            pillar_values = [
                str(item.get("干支") or "") if isinstance(item, dict) else str(item)
                for item in pillars[:4]
            ]
            dynamics = natal_branch_dynamics(pillar_values)
            if any(dynamics.values()):
                serialized_payload["确定性地支作用"] = dynamics
            natal_facts = _natal_timing_facts(pillar_values, pillars)
            if natal_facts:
                serialized_payload["原局确定性事实"] = [
                    fact.as_provider_record(compact=True) for fact in natal_facts
                ]
    if action == "dayun":
        cycles = raw_payload.get("大运列表")
        if isinstance(cycles, list):
            selected_cycles = _select_bazi_cycles(cycles)
            compact_cycles = [
                _compact_bazi_cycle(item, pillars or []) for item in selected_cycles
            ]
            for cycle, compact_cycle in zip(selected_cycles, compact_cycles, strict=True):
                facts = _dayun_timing_facts(cycle, compact_cycle)
                if facts:
                    compact_cycle["确定性事实"] = [
                        fact.as_provider_record(compact=True) for fact in facts
                    ]
                    _strip_indexed_fact_sources(compact_cycle)
            serialized_payload["大运列表"] = compact_cycles
            serialized_payload.pop("大运列表_truncated_count", None)
            timing_years = _compact_bazi_timing_years(
                selected_cycles,
                pillars=pillars,
                pillar_ten_gods=pillar_ten_gods,
                gender=gender,
            )
            structural_summary = _compact_bazi_structural_summary(timing_years)
            if structural_summary:
                serialized_payload["成年后关系事实摘要"] = structural_summary
            past_timing_years = [
                item
                for item in timing_years
                if isinstance(item.get("流年"), int)
                and int(item["流年"]) <= date.today().year
            ]
            indexed_summary = _compact_bazi_structural_summary(
                past_timing_years,
                limit=_BAZI_VERIFICATION_INDEXED_YEAR_LIMIT,
            )
            indexed_years = {
                int(item["流年"])
                for item in indexed_summary
                if isinstance(item.get("流年"), int)
            }
            for timing_year in timing_years:
                if timing_year.get("流年") not in indexed_years:
                    continue
                facts = _annual_timing_facts(timing_year)
                if facts:
                    timing_year["确定性事实"] = [
                        fact.as_provider_record(compact=True) for fact in facts
                    ]
                    _strip_indexed_fact_sources(timing_year)
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
    facts = timing_relation_facts(
        str(cycle.get("干支") or "").strip(),
        moving_label="大运",
        natal_pillars=pillars,
    )
    stem_relations, repeated_branches = facts.stem_relations, facts.repeated_branches
    if stem_relations:
        compact["天干作用"] = [
            _compact_stem_relation(relation.replace("流年干", "大运干"))
            for relation in stem_relations
        ]
    if facts.hidden_stem_relations:
        compact["藏干作用"] = [
            _compact_stem_relation(relation.replace("流年干", "大运干"))
            for relation in facts.hidden_stem_relations
        ]
    if repeated_branches:
        compact["同支伏吟"] = repeated_branches
    if facts.all_branch_relations:
        compact["作用关系"] = facts.all_branch_relations
    if facts.transformation_relations:
        compact["合化判定"] = _compact_transformation_relations(
            facts.transformation_relations
        )
    if facts.impact_relations:
        compact["受伤属性"] = _compact_impact_relations(facts.impact_relations)
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
    timing_years: list[dict[str, object]] = []
    selected_cycles = _select_bazi_cycles(cycles)
    for cycle in selected_cycles:
        dayun = str(cycle.get("干支") or "").strip()
        dayun_ten_god = str(cycle.get("十神") or "").strip()
        annual_items = cycle.get("流年列表")
        if not isinstance(annual_items, list):
            continue
        valid_annuals = [
            annual
            for annual in annual_items
            if isinstance(annual, dict)
            and isinstance(annual.get("流年"), int)
            and not isinstance(annual.get("流年"), bool)
            and (current_year is None or int(annual["流年"]) <= current_year)
        ]
        valid_annuals.sort(key=lambda item: int(item["流年"]))
        first_year = int(valid_annuals[0]["流年"]) if valid_annuals else 0
        eligible_annuals = [
            annual
            for annual in valid_annuals
            if int(annual["流年"]) < first_year + _BAZI_TIMING_YEARS_PER_DAYUN
        ][:_BAZI_TIMING_YEARS_PER_DAYUN]
        for annual in eligible_annuals:
            compact: dict[str, object] = {
                field: annual[field]
                for field in ("流年", "年龄", "干支", "十神")
                if field in annual
            }
            if dayun:
                compact["所在大运"] = dayun
            if dayun_ten_god:
                compact["大运十神"] = dayun_ten_god
            upstream_relations = [
                str(item.get("描述") or "").strip()
                for item in annual.get("原局关系") or []
                if isinstance(item, dict) and str(item.get("描述") or "").strip()
            ]
            facts = timing_relation_facts(
                str(annual.get("干支") or "").strip(),
                moving_label="流年",
                natal_pillars=pillars or [],
                dayun_pillar=dayun,
            )
            relations = _merge_branch_relations(upstream_relations, facts.all_branch_relations)
            if relations:
                compact["作用关系"] = relations
            if facts.transformation_relations:
                compact["合化判定"] = _compact_transformation_relations(
                    facts.transformation_relations
                )
            if facts.impact_relations:
                compact["受伤属性"] = _compact_impact_relations(
                    facts.impact_relations
                )
            stem_relations, repeated_branches = facts.stem_relations, facts.repeated_branches
            if stem_relations:
                compact["天干作用"] = [
                    _compact_stem_relation(item)
                    for item in stem_relations
                ]
            if facts.hidden_stem_relations:
                compact["藏干作用"] = [
                    _compact_stem_relation(item)
                    for item in facts.hidden_stem_relations
                ]
            if repeated_branches:
                compact["同支伏吟"] = repeated_branches
            shensha = list(
                dict.fromkeys(
                    str(item).strip()
                    for item in annual.get("神煞") or []
                    if str(item).strip()
                )
            )
            if shensha:
                compact["神煞"] = shensha
            timing_years.append(compact)
    return timing_years


def _select_bazi_cycles(cycles: list[object]) -> list[dict[str, object]]:
    """Keep the six chronological dayun cycles beginning at qiyun."""
    return [
        cycle for cycle in cycles if isinstance(cycle, dict)
    ][:_BAZI_TIMING_DAYUN_LIMIT]


_FACT_FIELDS = (
    ("作用关系", "relation"),
    ("合化判定", "transformation"),
    ("受伤属性", "impact"),
    ("同支伏吟", "repetition"),
    ("天干作用", "stem_relation"),
    ("藏干作用", "hidden_stem_relation"),
)


def _natal_timing_facts(
    pillars: list[str],
    raw_pillars: list[object] | None = None,
) -> list[BaziTimingFact]:
    if len(pillars) != 4:
        return []
    facts = [
        BaziTimingFact(
            fact_id="natal.pillars",
            layer="natal",
            kind="pillars",
            text=f"原局四柱为{'、'.join(pillars)}",
        )
    ]
    palace_names = ("年柱", "月柱", "日柱", "时柱")
    for index, pillar in enumerate(pillars):
        raw = (
            raw_pillars[index]
            if isinstance(raw_pillars, list) and index < len(raw_pillars)
            else None
        )
        details = [f"{palace_names[index]}为{pillar}"]
        if isinstance(raw, dict):
            stem_ten_god = str(raw.get("天干十神") or "").strip()
            if stem_ten_god and stem_ten_god != "-":
                details.append(f"天干十神为{stem_ten_god}")
            hidden = [
                f"{str(item.get('天干') or '').strip()}{str(item.get('十神') or '').strip()}"
                for item in raw.get("藏干") or []
                if isinstance(item, dict)
                and (str(item.get("天干") or "").strip() or str(item.get("十神") or "").strip())
            ]
            if hidden:
                details.append(f"藏干为{'、'.join(hidden)}")
        facts.append(
            BaziTimingFact(
                fact_id=f"natal.pillar.{index}",
                layer="natal",
                kind="pillar_ten_gods",
                text="，".join(details),
            )
        )
    dynamics = natal_branch_dynamics(pillars)
    for field, kind in (("合化判定", "transformation"), ("受影响属性", "impact")):
        for index, value in enumerate(dynamics.get(field) or []):
            facts.append(
                BaziTimingFact(
                    fact_id=f"natal.{kind}.{index}",
                    layer="natal",
                    kind=kind,
                    text=_timing_fact_text(value),
                )
            )
    return facts


def _dayun_timing_facts(
    raw_cycle: dict[str, object],
    compact_cycle: dict[str, object],
) -> list[BaziTimingFact]:
    start_year = int(raw_cycle.get("起运年份") or 0)
    prefix = f"dayun.{start_year}"
    pillar = str(raw_cycle.get("干支") or "").strip()
    ten_god = str(raw_cycle.get("十神") or "").strip()
    annual_years = [
        int(item["流年"])
        for item in raw_cycle.get("流年列表") or []
        if isinstance(item, dict)
        and isinstance(item.get("流年"), int)
        and not isinstance(item.get("流年"), bool)
    ]
    year_start = min(annual_years) if annual_years else start_year
    year_end = max(annual_years) if annual_years else start_year + 9
    identity = f"{start_year}年起进入{pillar}大运"
    if ten_god:
        identity += f"，大运十神为{ten_god}"
    facts = [
        BaziTimingFact(
            fact_id=f"{prefix}.identity",
            layer="dayun",
            kind="identity",
            text=identity,
            year_start=year_start,
            year_end=year_end,
        )
    ]
    facts.extend(
        _signal_timing_facts(
            compact_cycle,
            prefix=prefix,
            layer="dayun",
            year_start=year_start,
            year_end=year_end,
        )
    )
    return facts


def _annual_timing_facts(timing_year: dict[str, object]) -> list[BaziTimingFact]:
    year = int(timing_year.get("流年") or 0)
    if year <= 0:
        return []
    pillar = str(timing_year.get("干支") or "").strip()
    ten_god = str(timing_year.get("十神") or "").strip()
    identity = f"{year}年流年为{pillar}"
    if ten_god:
        identity += f"，流年十神为{ten_god}"
    facts = [
        BaziTimingFact(
            fact_id=f"year.{year}.identity",
            layer="liunian",
            kind="identity",
            text=identity,
            year=year,
        )
    ]
    facts.extend(
        _signal_timing_facts(
            timing_year,
            prefix=f"year.{year}",
            layer="liunian",
            year=year,
        )
    )
    for index, name in enumerate(timing_year.get("神煞") or []):
        normalized = str(name or "").strip()
        if normalized:
            facts.append(
                BaziTimingFact(
                    fact_id=f"year.{year}.shensha.{index}",
                    layer="shensha",
                    kind="shensha",
                    text=normalized,
                    year=year,
                )
            )
    return facts


def _signal_timing_facts(
    payload: dict[str, object],
    *,
    prefix: str,
    layer: str,
    year: int | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
) -> list[BaziTimingFact]:
    facts: list[BaziTimingFact] = []
    for field, kind in _FACT_FIELDS:
        for index, value in enumerate(payload.get(field) or []):
            facts.append(
                BaziTimingFact(
                    fact_id=f"{prefix}.{kind}.{index}",
                    layer=layer,
                    kind=kind,
                    text=_timing_fact_text(value),
                    year=year,
                    year_start=year_start,
                    year_end=year_end,
                )
            )
    return facts


def _strip_indexed_fact_sources(payload: dict[str, object]) -> None:
    for field, _ in _FACT_FIELDS:
        payload.pop(field, None)
    payload.pop("神煞", None)


def _timing_fact_text(value: object) -> str:
    if isinstance(value, dict):
        relation = str(value.get("关系") or "").strip()
        result = str(value.get("作用结果") or "").strip()
        if relation and result:
            return f"{relation}：{result}"
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value or "").strip()


def build_bazi_timing_fact_registry(
    tool_history: list["ToolExchange"],
) -> dict[str, dict[str, object]]:
    pillars = _bazi_pillars_from_history(tool_history) or []
    raw_pillars = _bazi_raw_pillars_from_history(tool_history)
    facts = _natal_timing_facts(pillars, raw_pillars)
    pillar_ten_gods = _bazi_pillar_ten_gods_from_history(tool_history)
    for exchange in tool_history:
        if exchange.tool_name != "bazi" or exchange.tool_result.get("ok") is not True:
            continue
        result = exchange.tool_result.get("result")
        if not isinstance(result, dict):
            continue
        action = str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        if action != "dayun":
            continue
        cycles = result.get("大运列表")
        if not isinstance(cycles, list):
            continue
        selected_cycles = _select_bazi_cycles(cycles)
        for cycle in selected_cycles:
            facts.extend(_dayun_timing_facts(cycle, _compact_bazi_cycle(cycle, pillars)))
        timing_years = _compact_bazi_timing_years(
            selected_cycles,
            pillars=pillars,
            pillar_ten_gods=pillar_ten_gods,
            gender=str(exchange.tool_payload.get("gender") or ""),
        )
        for timing_year in timing_years:
            facts.extend(_annual_timing_facts(timing_year))
        break
    return {fact.fact_id: fact.as_provider_record() for fact in facts}


def _compact_stem_relation(value: str) -> str:
    matched = re.fullmatch(
        r"([甲乙丙丁戊己庚辛壬癸])"
        r"(?:([甲乙丙丁戊己庚辛壬癸])(合)|([生克])([甲乙丙丁戊己庚辛壬癸]))"
        r"（(.+?)(合|生|克)(.+?)）",
        str(value or ""),
    )
    if matched is None:
        return str(value or "")
    left_stem = matched.group(1)
    right_stem = matched.group(2) or matched.group(5)
    operation = matched.group(3) or matched.group(4)
    left_label, detail_operation, right_label = matched.group(6, 7, 8)
    if operation != detail_operation:
        return str(value or "")
    left = left_label if left_label.endswith(left_stem) else f"{left_label}{left_stem}"
    right = right_label if right_label.endswith(right_stem) else f"{right_label}{right_stem}"
    compact = f"{left}{operation}{right}"
    for verbose, short in (
        ("流年", "岁"),
        ("大运", "运"),
        ("本气", "本"),
        ("中气", "中"),
        ("余气", "余"),
    ):
        compact = compact.replace(verbose, short)
    return compact


def _compact_transformation_relations(items: list[dict[str, object]]) -> list[str]:
    compact: list[str] = []
    for item in items:
        participants = ",".join(
            f"{part.get('宫位', '')}{part.get('地支', '')}"
            f"({part.get('五行', '')}/{part.get('十神', '')})"
            for part in item.get("参与支", [])
            if isinstance(part, dict)
        )
        triggers = "、".join(str(value) for value in item.get("引化天干", []))
        compact.append(
            f"{item.get('关系', '')}:{item.get('状态', '')};"
            f"引={triggers or '无'};参与={participants}"
        )
    return list(dict.fromkeys(compact))


def _compact_impact_relations(items: list[dict[str, object]]) -> list[str]:
    compact: list[str] = []
    for item in items:
        compact.extend(
            f"{part.get('宫位', '')}{part.get('地支', '')}:"
            f"{part.get('五行', '')}/{part.get('十神', '')}"
            for part in item.get("受影响一方", [])
            if isinstance(part, dict)
        )
    return list(dict.fromkeys(compact))


def _merge_branch_relations(upstream: list[str], computed: list[str]) -> list[str]:
    merged = list(dict.fromkeys(upstream))
    seen = {_branch_relation_key(item) for item in merged}
    for item in computed:
        key = _branch_relation_key(item)
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def _branch_relation_key(value: str) -> tuple[str, str]:
    branches = [char for char in value[:8] if char in "子丑寅卯辰巳午未申酉戌亥"]
    relation = next(
        (marker for marker in ("三合", "三会", "六合", "相冲", "相刑", "自刑", "相害", "相破") if marker in value),
        value,
    )
    return "".join(sorted(branches[:3])), relation


def _compact_bazi_structural_summary(
    timing_years: list[dict[str, object]],
    *,
    limit: int = 20,
) -> list[dict[str, object]]:
    signal_fields = (
        "作用关系",
        "合化判定",
        "受伤属性",
        "同支伏吟",
        "天干作用",
        "藏干作用",
        "神煞",
    )
    candidates = [
        item
        for item in timing_years
        if isinstance(item.get("年龄"), int)
        and item["年龄"] >= 18
        and any(item.get(field) for field in signal_fields)
    ]

    def signal_counts(item: dict[str, object]) -> dict[str, int]:
        return {
            field: len(item.get(field) or [])
            for field in signal_fields
            if item.get(field)
        }

    def signal_score(item: dict[str, object]) -> float:
        counts = signal_counts(item)
        return (
            counts.get("合化判定", 0) * 6
            + counts.get("作用关系", 0) * 4
            + counts.get("同支伏吟", 0) * 3
            + counts.get("受伤属性", 0) * 2
            + counts.get("天干作用", 0)
            + counts.get("藏干作用", 0) * 0.25
            + counts.get("神煞", 0) * 0.5
        )

    ranked = sorted(
        candidates,
        key=lambda item: (
            signal_score(item),
            int(item.get("流年") or 0),
        ),
        reverse=True,
    )[:limit]
    summary = [
        {
            **{
                field: item[field]
                for field in ("流年", "年龄", "干支", "所在大运")
                if field in item
            },
            "信号计数": signal_counts(item),
        }
        for item in ranked
    ]
    return sorted(summary, key=lambda item: int(item.get("流年") or 0))


def compact_bazi_verification_repair_evidence(
    tool_history: list["ToolExchange"],
    candidate_years: set[int],
) -> dict[str, object]:
    pillars = _bazi_pillars_from_history(tool_history) or []
    pillar_ten_gods = _bazi_pillar_ten_gods_from_history(tool_history)
    evidence: dict[str, object] = {"原局四柱": pillars}
    dynamics = natal_branch_dynamics(pillars)
    if any(dynamics.values()):
        evidence["原局确定性地支作用"] = dynamics
    for exchange in tool_history:
        if exchange.tool_name != "bazi" or exchange.tool_result.get("ok") is not True:
            continue
        result = exchange.tool_result.get("result")
        if not isinstance(result, dict):
            continue
        action = str(exchange.tool_payload.get("action") or exchange.tool_result.get("action") or "")
        if action == "chart":
            raw_pillars = result.get("四柱")
            if isinstance(raw_pillars, list):
                evidence["原局十神宫位"] = raw_pillars[:4]
        if action != "dayun":
            continue
        cycles = result.get("大运列表")
        if not isinstance(cycles, list):
            continue
        selected_cycles = _select_bazi_cycles(cycles)
        timing_years = _compact_bazi_timing_years(
            selected_cycles,
            current_year=max(candidate_years) if candidate_years else 2100,
            pillars=pillars,
            pillar_ten_gods=pillar_ten_gods,
            gender=str(exchange.tool_payload.get("gender") or ""),
        )
        for timing_year in timing_years:
            timing_year["确定性事实"] = [
                fact.as_provider_record(compact=True)
                for fact in _annual_timing_facts(timing_year)
            ]
            _strip_indexed_fact_sources(timing_year)
        evidence["候选年份应期事实"] = [
            item for item in timing_years if item.get("流年") in candidate_years
        ]
        related_cycles: list[dict[str, object]] = []
        for cycle in selected_cycles:
            if not any(
                isinstance(annual, dict) and annual.get("流年") in candidate_years
                for annual in cycle.get("流年列表") or []
            ):
                continue
            compact_cycle = _compact_bazi_cycle(cycle, pillars)
            compact_cycle["确定性事实"] = [
                fact.as_provider_record(compact=True)
                for fact in _dayun_timing_facts(cycle, compact_cycle)
            ]
            _strip_indexed_fact_sources(compact_cycle)
            related_cycles.append(compact_cycle)
        evidence["相关大运"] = related_cycles
        evidence["原局确定性事实"] = [
            fact.as_provider_record(compact=True)
            for fact in _natal_timing_facts(
                pillars,
                _bazi_raw_pillars_from_history(tool_history),
            )
        ]
        if "起运信息" in result:
            evidence["起运信息"] = result["起运信息"]
        break
    return evidence


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


def _bazi_raw_pillars_from_history(
    tool_history: list["ToolExchange"],
) -> list[object] | None:
    for exchange in tool_history:
        if exchange.tool_name != "bazi" or exchange.tool_result.get("ok") is not True:
            continue
        result = exchange.tool_result.get("result")
        raw_pillars = result.get("四柱") if isinstance(result, dict) else None
        if isinstance(raw_pillars, list) and len(raw_pillars) >= 4:
            return raw_pillars[:4]
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
    ) and request.request_kind not in {
        "bazi_dayun_repair",
        "bazi_knowledge_search",
        "bazi_case_search",
    }:
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
    if tool_name == "bazi_case" and request.request_kind == "bazi_case_search":
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "const": "search"},
                "query": {"type": "string", "minLength": 1},
                "top_k": {"type": "integer", "const": 3},
                "event_category": {
                    "type": "string",
                    "enum": [
                        "education",
                        "career",
                        "wealth",
                        "marriage",
                        "health",
                        "family",
                        "children",
                        "relocation",
                        "legal",
                        "other",
                    ],
                },
            },
            "required": ["action", "query", "top_k"],
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
