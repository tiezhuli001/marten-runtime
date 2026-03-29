from marten_runtime.memory.models import MemoryEntry


def search_entries(query: str, items: list[MemoryEntry]) -> list[MemoryEntry]:
    term = query.strip().lower()
    if not term:
        return []
    return [item for item in items if term in item.text.lower()]
