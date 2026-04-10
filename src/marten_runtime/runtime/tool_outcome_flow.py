from __future__ import annotations

import json
import logging

from marten_runtime.runtime.llm_client import ToolExchange

logger = logging.getLogger(__name__)
from marten_runtime.session.tool_outcome_summary import (
    ToolOutcomeFact,
    ToolOutcomeSummary,
)
from marten_runtime.tools.registry import ToolSnapshot


def infer_episode_source_kind(
    history: list[ToolExchange], tool_snapshot: ToolSnapshot
) -> str:
    kinds = {
        str(
            tool_snapshot.tool_metadata.get(item.tool_name, {}).get("source_kind")
            or ("mcp" if item.tool_name == "mcp" else "builtin")
        )
        for item in history
    }
    if not kinds:
        return "other"
    if len(kinds) == 1:
        return next(iter(kinds))
    return "mixed"


def collect_structured_hint_facts(history: list[ToolExchange]) -> list[ToolOutcomeFact]:
    preferred_keys = (
        "full_name",
        "default_branch",
        "repo",
        "branch",
        "name",
        "title",
        "url",
        "html_url",
        "estimated_usage",
        "effective_window",
    )
    facts: list[ToolOutcomeFact] = []
    for item in reversed(history):
        if not isinstance(item.tool_result, dict):
            continue
        candidate_dicts: list[dict[str, object]] = [item.tool_result]
        current_run = item.tool_result.get("current_run")
        if isinstance(current_run, dict):
            actual_peak_total = int(current_run.get("actual_peak_total_tokens") or 0)
            actual_peak_stage = str(current_run.get("actual_peak_stage") or "").strip()
            initial_tokens = int(current_run.get("initial_input_tokens_estimate") or 0)
            peak_tokens = int(current_run.get("peak_input_tokens_estimate") or 0)
            peak_stage = str(current_run.get("peak_stage") or "").strip()
            if actual_peak_total > 0:
                if actual_peak_stage == "llm_second":
                    facts.append(
                        ToolOutcomeFact.create(
                            "actual_peak_source", "工具结果注入后的 follow-up 模型调用"
                        )
                    )
                facts.append(
                    ToolOutcomeFact.create(
                        "actual_peak_total_tokens", actual_peak_total
                    )
                )
            else:
                if peak_stage == "tool_followup" and peak_tokens > max(
                    0, initial_tokens
                ):
                    facts.append(
                        ToolOutcomeFact.create("peak_source", "工具结果注入后")
                    )
                if peak_tokens > 0:
                    facts.append(ToolOutcomeFact.create("peak_tokens", peak_tokens))
            facts = merge_tool_episode_facts(facts, None)
            if len(facts) >= 3:
                return facts[:3]
        result_text = item.tool_result.get("result_text")
        if isinstance(result_text, str):
            try:
                parsed = json.loads(result_text)
                if isinstance(parsed, dict):
                    candidate_dicts.append(parsed)
                    items = parsed.get("items")
                    if isinstance(items, list) and items and isinstance(items[0], dict):
                        candidate_dicts.append(items[0])
            except Exception:
                logger.debug(
                    "mcp result parse failed for structured hint", exc_info=True
                )
        for candidate in candidate_dicts:
            for key in preferred_keys:
                value = candidate.get(key)
                if value is None:
                    continue
                normalized = str(value).strip()
                if not normalized or len(normalized) > 120:
                    continue
                fact_key = "url" if key == "html_url" else key
                fact = ToolOutcomeFact.create(fact_key, normalized)
                if any(
                    existing.key == fact.key and existing.value == fact.value
                    for existing in facts
                ):
                    continue
                facts.append(fact)
                if len(facts) >= 3:
                    return facts
    return facts


def merge_tool_episode_facts(
    primary: list[ToolOutcomeFact] | None,
    fallback: list[ToolOutcomeFact] | None,
    *,
    limit: int = 3,
) -> list[ToolOutcomeFact]:
    merged: list[ToolOutcomeFact] = []
    for fact in [*(primary or []), *(fallback or [])]:
        if not fact.key.strip() or not fact.value.strip():
            continue
        if any(
            existing.key == fact.key and existing.value == fact.value
            for existing in merged
        ):
            continue
        merged.append(fact)
        if len(merged) >= limit:
            break
    return merged


def resolve_summary_volatile_flag(
    *,
    draft_volatile: bool,
    facts: list[ToolOutcomeFact],
    fallback_summary: ToolOutcomeSummary | None,
) -> bool:
    if fallback_summary is not None and fallback_summary.volatile:
        return True
    if not draft_volatile:
        return False
    durable_fact_keys = {"full_name", "default_branch", "name", "repo", "branch"}
    if any(fact.key in durable_fact_keys for fact in facts):
        return False
    return True
