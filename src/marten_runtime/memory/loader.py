from __future__ import annotations

from pydantic import BaseModel, Field

from marten_runtime.agents.ids import canonicalize_runtime_agent_id
from marten_runtime.memory.models import MemoryItem
from marten_runtime.memory.store import MemoryStore


class MemoryLoadRequest(BaseModel):
    user_id: str
    agent_id: str | None = None
    workspace_id: str | None = None
    current_message: str = ""
    char_budget: int = 800
    per_scope_limit: int = 8
    search_limit: int = 12


class MemoryLoadResult(BaseModel):
    items: list[MemoryItem] = Field(default_factory=list)
    rendered_text: str | None = None
    active_count: int = 0
    loaded_count: int = 0
    budget_chars: int = 800


class MemoryLoader:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def load(self, request: MemoryLoadRequest) -> MemoryLoadResult:
        user_id = str(request.user_id or "").strip()
        if not user_id:
            return MemoryLoadResult(budget_chars=request.char_budget)
        agent_id = canonicalize_runtime_agent_id(request.agent_id, default=None)
        candidates: list[tuple[MemoryItem, bool]] = []
        candidates.extend((item, False) for item in self.store.list_active(user_id, scope="global", limit=request.per_scope_limit))
        if agent_id:
            candidates.extend((item, False) for item in self.store.list_active(user_id, scope="agent", agent_id=agent_id, limit=request.per_scope_limit))
        workspace_id = str(request.workspace_id or "").strip() or None
        if workspace_id:
            candidates.extend((item, False) for item in self.store.list_active(user_id, scope="workspace", workspace_id=workspace_id, limit=request.per_scope_limit))
        eligible_search_results = self._search_eligible(user_id, request, agent_id=agent_id, workspace_id=workspace_id)
        candidates.extend((item, True) for item in eligible_search_results)
        active_count = len({item.memory_id for item, _ in candidates})
        deduped = _dedupe_with_fts_flag(candidates)
        ordered = sorted(
            deduped,
            key=lambda pair: (pair[0].priority, pair[1], pair[0].updated_at, pair[0].memory_id),
            reverse=True,
        )
        selected = _select_with_budget([item for item, _ in ordered], request.char_budget)
        rendered = render_memory_items(selected) if selected else None
        return MemoryLoadResult(
            items=selected,
            rendered_text=rendered,
            active_count=active_count,
            loaded_count=len(selected),
            budget_chars=request.char_budget,
        )

    def _search_eligible(
        self,
        user_id: str,
        request: MemoryLoadRequest,
        *,
        agent_id: str | None,
        workspace_id: str | None,
    ) -> list[MemoryItem]:
        query = str(request.current_message or "").strip()
        if not query:
            return []
        results: list[MemoryItem] = []
        results.extend(self.store.search(user_id, query, scope="global", limit=request.search_limit))
        if agent_id:
            results.extend(self.store.search(user_id, query, scope="agent", agent_id=agent_id, limit=request.search_limit))
        if workspace_id:
            results.extend(self.store.search(user_id, query, scope="workspace", workspace_id=workspace_id, limit=request.search_limit))
        return results


def render_memory_items(items: list[MemoryItem]) -> str | None:
    if not items:
        return None
    lines = ["User memory:"]
    for item in items:
        lines.append(f"- [{item.type}][{_scope_label(item)}] {item.content}")
    return "\n".join(lines)


def _scope_label(item: MemoryItem) -> str:
    if item.scope == "agent":
        return f"agent:{item.agent_id}"
    if item.scope == "workspace":
        return f"workspace:{item.workspace_id}"
    return "global"


def _dedupe_with_fts_flag(candidates: list[tuple[MemoryItem, bool]]) -> list[tuple[MemoryItem, bool]]:
    by_id: dict[str, tuple[MemoryItem, bool]] = {}
    for item, fts_hit in candidates:
        previous = by_id.get(item.memory_id)
        by_id[item.memory_id] = (item, fts_hit or (previous[1] if previous else False))
    return list(by_id.values())


def _select_with_budget(items: list[MemoryItem], budget: int) -> list[MemoryItem]:
    if budget <= 0:
        return []
    selected: list[MemoryItem] = []
    used = len("User memory:\n")
    for item in items:
        line = f"- [{item.type}][{_scope_label(item)}] {item.content}"
        line_cost = len(line) + (1 if selected else 0)
        if selected and used + line_cost > budget:
            continue
        if not selected and used + len(line) > budget:
            continue
        selected.append(item)
        used += line_cost
    return selected
