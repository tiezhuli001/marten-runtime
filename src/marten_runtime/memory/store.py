from __future__ import annotations

from typing import Protocol

from marten_runtime.memory.models import MemoryItem


class MemoryStore(Protocol):
    def append(self, item: MemoryItem) -> MemoryItem: ...

    def replace(self, memory_id: str, new_item: MemoryItem) -> MemoryItem: ...

    def delete(self, memory_id: str) -> MemoryItem: ...

    def supersede(self, memory_id: str, *, updated_at: str | None = None) -> MemoryItem: ...

    def get(self, memory_id: str) -> MemoryItem | None: ...

    def list_active(
        self,
        user_id: str,
        *,
        scope: str | None = None,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        type: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryItem]: ...

    def search(
        self,
        user_id: str,
        query: str,
        *,
        scope: str | None = None,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        type: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]: ...
