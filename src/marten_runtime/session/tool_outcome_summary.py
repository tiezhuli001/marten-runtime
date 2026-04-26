from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from pydantic import BaseModel, Field


def _trim_text(value: str, *, limit: int) -> str:
    normalized = " ".join(str(value).split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


class ToolOutcomeFact(BaseModel):
    key: str
    value: str

    @classmethod
    def create(cls, key: str, value: object, *, value_limit: int = 80) -> "ToolOutcomeFact":
        return cls(key=_trim_text(str(key), limit=40), value=_trim_text(str(value), limit=value_limit))


class ToolOutcomeSummary(BaseModel):
    summary_id: str
    run_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_kind: str = "other"
    summary_text: str
    facts: list[ToolOutcomeFact] = Field(default_factory=list)
    volatile: bool = False
    keep_next_turn: bool = True
    refresh_hint: str | None = None
    token_estimate: int = 0
    tool_name: str | None = None
    truncated: bool = False

    @property
    def user_visible_summary(self) -> str:
        return self.summary_text

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        source_kind: str,
        summary_text: str | None = None,
        user_visible_summary: str | None = None,
        facts: list[ToolOutcomeFact] | None = None,
        volatile: bool = False,
        keep_next_turn: bool | None = None,
        refresh_hint: str | None = None,
        tool_name: str | None = None,
    ) -> "ToolOutcomeSummary":
        raw_summary = summary_text if summary_text is not None else (user_visible_summary or "")
        trimmed_summary = _trim_text(raw_summary, limit=220)
        trimmed_facts = list(facts or [])[:3]
        if keep_next_turn is None:
            keep_next_turn = not volatile
        summary_id = f"sum_{sha256(f'{run_id}:{source_kind}:{trimmed_summary}'.encode('utf-8')).hexdigest()[:8]}"
        token_estimate = max(1, len(trimmed_summary) // 4) if trimmed_summary else 0
        return cls(
            summary_id=summary_id,
            run_id=run_id,
            source_kind=source_kind,
            summary_text=trimmed_summary,
            facts=trimmed_facts,
            volatile=volatile,
            keep_next_turn=keep_next_turn,
            refresh_hint=_trim_text(refresh_hint or "", limit=120) or None,
            token_estimate=token_estimate,
            tool_name=tool_name,
            truncated=(
                trimmed_summary != raw_summary
                or len(trimmed_facts) != len(facts or [])
                or ((_trim_text(refresh_hint or "", limit=120) or None) != (refresh_hint or None))
            ),
        )

    def dedupe_key(self) -> str:
        fact_keys = ",".join(f"{fact.key}={fact.value}" for fact in self.facts)
        normalized = f"{self.source_kind}|{self.summary_text}|{fact_keys}|{self.volatile}|{self.keep_next_turn}"
        return sha256(normalized.encode("utf-8")).hexdigest()


def coerce_tool_outcome_summary(item: ToolOutcomeSummary | dict[str, object]) -> ToolOutcomeSummary:
    if isinstance(item, ToolOutcomeSummary):
        return item
    facts: list[ToolOutcomeFact] = []
    raw_facts = item.get("facts")
    if isinstance(raw_facts, list):
        for raw in raw_facts[:3]:
            if isinstance(raw, ToolOutcomeFact):
                facts.append(raw)
            elif isinstance(raw, dict) and raw.get("key") is not None and raw.get("value") is not None:
                facts.append(ToolOutcomeFact.create(str(raw["key"]), raw["value"]))
    return ToolOutcomeSummary.create(
        run_id=str(item.get("run_id") or "run_unknown"),
        source_kind=str(item.get("source_kind") or "other"),
        summary_text=str(item.get("summary_text") or item.get("user_visible_summary") or ""),
        facts=facts,
        volatile=bool(item.get("volatile", False)),
        keep_next_turn=bool(item.get("keep_next_turn", not bool(item.get("volatile", False)))),
        refresh_hint=str(item.get("refresh_hint")) if item.get("refresh_hint") is not None else None,
        tool_name=str(item.get("tool_name")) if item.get("tool_name") is not None else None,
    )


def render_tool_outcome_summary_block(
    summaries: list[ToolOutcomeSummary | dict[str, object]] | None,
    *,
    max_items: int = 2,
    max_chars: int = 600,
) -> str | None:
    rendered: list[str] = []
    for item in list(summaries or []):
        summary = coerce_tool_outcome_summary(item)
        if not summary.summary_text.strip():
            continue
        if summary.volatile or not summary.keep_next_turn:
            continue
        facts_text = "; ".join(f"{fact.key}={fact.value}" for fact in summary.facts[:2] if fact.key and fact.value)
        line = f"- {summary.summary_text}"
        if facts_text:
            line += f" Facts: {facts_text}."
        rendered.append(_trim_text(line, limit=min(max_chars, 280)))
        if len(rendered) >= max_items:
            break
    if not rendered:
        return None
    heading = (
        "以下仅是上一轮可延续的工具结果摘要，只有当前消息明确承接上一轮结果时才参考。"
        "不要因为上一轮刚用了某个工具族，就在本轮复用同一路径："
    )
    text = heading + "\n" + "\n".join(rendered)
    if len(text) <= max_chars:
        return text
    kept: list[str] = []
    current = heading
    for line in rendered:
        candidate = current + "\n" + "\n".join([*kept, line])
        if len(candidate) > max_chars:
            break
        kept.append(line)
    if not kept:
        kept = [_trim_text(rendered[0], limit=max(20, max_chars - len(heading) - 1))]
    return heading + "\n" + "\n".join(kept)
