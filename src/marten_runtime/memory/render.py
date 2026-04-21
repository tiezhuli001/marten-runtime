from __future__ import annotations


def render_memory_block(text: str, *, char_limit: int = 400) -> str | None:
    normalized = str(text or "").strip()
    if not normalized:
        return None
    if len(normalized) > char_limit:
        normalized = normalized[: max(1, char_limit - 1)].rstrip() + "…"
    return f"User memory:\n{normalized}"
