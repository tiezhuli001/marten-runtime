from marten_runtime.memory.models import MemoryEntry


def export_entries(items: list[MemoryEntry]) -> str:
    return "\n".join(f"[{item.memory_type}] {item.text}" for item in items)
