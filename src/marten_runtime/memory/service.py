from __future__ import annotations

from pathlib import Path

from marten_runtime.memory.export import memory_export_path, render_memory_markdown, sections_from_items, write_memory_export
from marten_runtime.memory.loader import MemoryLoadRequest, MemoryLoadResult, MemoryLoader
from marten_runtime.memory.models import MemoryDocument, MemoryItem
from marten_runtime.memory.sqlite_store import SQLiteMemoryStore
from marten_runtime.memory.store import MemoryStore


class ThinMemoryService:
    def __init__(
        self,
        root: str | Path,
        *,
        store: MemoryStore | None = None,
        db_path: str | Path | None = None,
        max_write_chars: int = 1000,
        prompt_char_limit: int = 800,
    ) -> None:
        self.root = Path(root)
        self.max_write_chars = max_write_chars
        self.prompt_char_limit = prompt_char_limit
        self.store = store or SQLiteMemoryStore(db_path or self.root / "memory.sqlite3")
        self.loader = MemoryLoader(self.store)
        self.last_load_result: MemoryLoadResult | None = None

    def has_stable_user_id(self, user_id: str) -> bool:
        return bool(str(user_id or "").strip())

    def memory_path(self, user_id: str) -> Path:
        if not self.has_stable_user_id(user_id):
            raise ValueError("stable user_id is required")
        return memory_export_path(self.root, user_id)

    def load(self, user_id: str) -> MemoryDocument:
        if not self.has_stable_user_id(user_id):
            return MemoryDocument(
                user_id="",
                path=self.root / "users" / "_anonymous" / "MEMORY.md",
                available=False,
            )
        items = self.store.list_active(user_id)
        text = render_memory_markdown(items)
        path = self.memory_path(user_id)
        return MemoryDocument(
            user_id=user_id,
            path=path,
            text=text,
            sections=sections_from_items(items),
            items=items,
        )

    def render_prompt_memory(
        self,
        user_id: str,
        *,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        current_message: str = "",
    ) -> str | None:
        if not self.has_stable_user_id(user_id):
            return None
        result = self.loader.load(
            MemoryLoadRequest(
                user_id=user_id,
                agent_id=agent_id,
                workspace_id=workspace_id,
                current_message=current_message,
                char_budget=self.prompt_char_limit,
            )
        )
        self.last_load_result = result
        return result.rendered_text

    def append(
        self,
        user_id: str,
        *,
        section: str,
        content: str,
        scope: str = "global",
        agent_id: str | None = None,
        workspace_id: str | None = None,
        type: str = "fact",
        source_excerpt: str = "",
        source_run_id: str | None = None,
        priority: int = 50,
    ) -> MemoryDocument:
        self._validate_write(content)
        document = self._require_document(user_id)
        item = MemoryItem.new(
            user_id=user_id,
            scope=scope,
            agent_id=agent_id,
            workspace_id=workspace_id,
            type=type,
            section=section,
            content=_normalize_entry(content),
            source_excerpt=source_excerpt,
            source_run_id=source_run_id,
            priority=priority,
        )
        self.store.append(item)
        return self._save(user_id)

    def replace(
        self,
        user_id: str,
        *,
        section: str,
        content: str,
        scope: str = "global",
        agent_id: str | None = None,
        workspace_id: str | None = None,
        type: str = "fact",
        source_excerpt: str = "",
        source_run_id: str | None = None,
        priority: int = 50,
        memory_id: str | None = None,
    ) -> MemoryDocument:
        self._validate_write(content)
        self._require_document(user_id)
        entries = [_normalize_entry(line) for line in str(content).splitlines() if _normalize_entry(line)] or [_normalize_entry(content)]
        targets = [self.store.get(memory_id)] if memory_id else self.store.list_active(user_id, scope=scope, agent_id=agent_id, workspace_id=workspace_id, type=type)
        targets = [item for item in targets if item is not None and item.section == _normalize_section(section)]
        for target in targets:
            self.store.delete(target.memory_id)
        for index, entry in enumerate(entries):
            new_item = MemoryItem.new(
                user_id=user_id,
                scope=scope,
                agent_id=agent_id,
                workspace_id=workspace_id,
                type=type,
                section=section,
                content=entry,
                source_excerpt=source_excerpt,
                source_run_id=source_run_id,
                priority=priority,
            )
            if index == 0 and memory_id and targets:
                self.store.replace(targets[0].memory_id, new_item)
            else:
                self.store.append(new_item)
        return self._save(user_id)

    def delete(
        self,
        user_id: str,
        *,
        section: str,
        content: str | None = None,
        scope: str | None = None,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        memory_id: str | None = None,
    ) -> MemoryDocument:
        self._require_document(user_id)
        if memory_id:
            self.store.delete(memory_id)
            return self._save(user_id)
        entry = _normalize_entry(content) if content is not None else None
        items = self.store.list_active(user_id, scope=scope, agent_id=agent_id, workspace_id=workspace_id)
        for item in items:
            if item.section != _normalize_section(section):
                continue
            if entry is not None and item.content != entry:
                continue
            self.store.delete(item.memory_id)
        return self._save(user_id)

    def diagnostics_summary(self) -> dict[str, object]:
        return {
            "store_kind": "sqlite",
            "active_count": self.store.count_active() if hasattr(self.store, "count_active") else len(self.store.list_active("")),
            "fts_enabled": True,
            "loaded_count_last_turn": self.last_load_result.loaded_count if self.last_load_result else None,
            "budget_chars": self.prompt_char_limit,
        }

    def _require_document(self, user_id: str) -> MemoryDocument:
        document = self.load(user_id)
        if not document.available:
            raise ValueError("stable user_id is required")
        return document

    def _save(self, user_id: str) -> MemoryDocument:
        document = self.load(user_id)
        write_memory_export(self.root, user_id, document.items)
        document.text = render_memory_markdown(document.items)
        return document

    def _validate_write(self, content: str) -> None:
        normalized = _normalize_entry(content)
        if not normalized:
            raise ValueError("content is required")
        if len(normalized) > self.max_write_chars:
            raise ValueError("memory write too large")


def _normalize_section(section: str) -> str:
    value = " ".join(str(section).split()).strip().lower()
    if not value:
        raise ValueError("section is required")
    return value


def _normalize_entry(content: str) -> str:
    return " ".join(str(content).split()).strip()
