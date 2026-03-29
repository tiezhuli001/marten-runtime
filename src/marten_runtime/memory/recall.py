from marten_runtime.memory.models import MemoryEntry
from marten_runtime.memory.search import search_entries


def build_recall_context(query: str, items: list[MemoryEntry], limit: int = 3) -> str:
    matched = search_entries(query, items)[:limit]
    return "\n".join(f"- {item.text}" for item in matched)
