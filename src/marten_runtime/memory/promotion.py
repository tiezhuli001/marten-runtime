from marten_runtime.memory.models import MemoryEntry


def promote_memory(items: list[MemoryEntry]) -> dict[str, list[str]]:
    promoted: dict[str, list[str]] = {}
    for item in items:
        promoted.setdefault(item.memory_type, []).append(item.text)
    return promoted
