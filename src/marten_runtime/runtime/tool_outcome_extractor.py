from __future__ import annotations

import json
from collections.abc import Mapping

from marten_runtime.session.tool_outcome_summary import ToolOutcomeFact, ToolOutcomeSummary


def extract_tool_outcome_summary(
    *,
    run_id: str,
    tool_name: str,
    tool_payload: Mapping[str, object] | None,
    tool_result: Mapping[str, object] | None,
    tool_metadata: Mapping[str, object] | None = None,
) -> ToolOutcomeSummary | None:
    payload = dict(tool_payload or {})
    result = dict(tool_result or {})
    metadata = dict(tool_metadata or {})
    source_kind = str(metadata.get("source_kind") or _infer_source_kind(tool_name, payload, result))

    if tool_name == "runtime" and str(result.get("action") or payload.get("action") or "") == "context_status":
        return None
    if tool_name == "skill":
        skill_id = str(result.get("skill_id") or payload.get("skill_id") or "").strip()
        if not skill_id:
            return None
        return ToolOutcomeSummary.create(
            run_id=run_id,
            source_kind="skill",
            tool_name=tool_name,
            summary_text=f"上一轮加载了 skill {skill_id}。",
            facts=[ToolOutcomeFact.create("skill_id", skill_id)],
        )
    if tool_name == "time":
        return ToolOutcomeSummary.create(
            run_id=run_id,
            source_kind=source_kind,
            tool_name=tool_name,
            summary_text="上一轮调用了 time 工具获取当前时间。",
            volatile=True,
            keep_next_turn=False,
            refresh_hint="若再次询问当前时间，应重新调用工具。",
        )
    if source_kind == "mcp" or tool_name == "mcp":
        server_id = str(result.get("server_id") or payload.get("server_id") or metadata.get("server_id") or "").strip()
        label = f"{server_id} MCP" if server_id else "MCP"
        facts = _small_facts(result, keys=("repo", "branch", "name", "title", "url"))
        if not facts:
            facts = _small_facts_from_result_text(result)
        summary = f"上一轮调用了 {label}，并获得了查询结果。"
        if facts:
            summary = f"{summary[:-1]} 关键结果：{facts[0].key}={facts[0].value}。"
        return ToolOutcomeSummary.create(
            run_id=run_id,
            source_kind="mcp",
            tool_name=tool_name,
            summary_text=summary,
            facts=facts,
        )
    facts = _small_facts(result, keys=("id", "name", "status", "url"))
    if not facts:
        return None
    return ToolOutcomeSummary.create(
        run_id=run_id,
        source_kind=source_kind,
        tool_name=tool_name,
        summary_text=f"上一轮调用了 {tool_name}，并获得了结果。",
        facts=facts,
    )


def _small_facts(result: dict[str, object], *, keys: tuple[str, ...]) -> list[ToolOutcomeFact]:
    facts: list[ToolOutcomeFact] = []
    for key in keys:
        value = result.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if not normalized or len(normalized) > 100:
            continue
        facts.append(ToolOutcomeFact.create(key, normalized))
        if len(facts) >= 3:
            break
    return facts


def _infer_source_kind(tool_name: str, payload: dict[str, object], result: dict[str, object]) -> str:
    if tool_name == "mcp" or result.get("server_id") is not None or payload.get("server_id") is not None:
        return "mcp"
    if tool_name == "skill":
        return "skill"
    if tool_name == "automation":
        return "automation"
    return "builtin"


def _small_facts_from_result_text(result: dict[str, object]) -> list[ToolOutcomeFact]:
    result_text = result.get("result_text")
    if not isinstance(result_text, str):
        return []
    try:
        parsed = json.loads(result_text)
    except Exception:
        return []
    candidates: list[dict[str, object]] = []
    if isinstance(parsed, dict):
        candidates.append(parsed)
        items = parsed.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            candidates.append(items[0])
    facts: list[ToolOutcomeFact] = []
    for candidate in candidates:
        for key in ("full_name", "default_branch", "repo", "branch", "url", "html_url"):
            value = candidate.get(key)
            if value is None:
                continue
            fact_key = "url" if key == "html_url" else key
            fact = ToolOutcomeFact.create(fact_key, value)
            if any(existing.key == fact.key and existing.value == fact.value for existing in facts):
                continue
            facts.append(fact)
            if len(facts) >= 3:
                return facts
    return facts
