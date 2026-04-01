from pydantic import BaseModel

from marten_runtime.skills.models import SkillHead, SkillSpec


class RenderedSkillHeads(BaseModel):
    text: str | None = None
    compact: bool = False
    truncated: bool = False
    truncated_reason: str | None = None


def build_skill_heads(items: list[SkillSpec]) -> list[SkillHead]:
    return [
        SkillHead(
            skill_id=item.meta.skill_id,
            name=item.meta.name,
            description=item.meta.description,
            aliases=item.meta.aliases,
            source_path=item.source_path,
        )
        for item in items
        if not item.meta.always_on
    ]


def render_skill_heads(
    items: list[SkillHead],
    *,
    max_chars: int,
    max_items: int,
) -> RenderedSkillHeads:
    if not items or max_chars <= 0 or max_items <= 0:
        return RenderedSkillHeads()
    visible_items = items[:max_items]
    full_text = _render_full(visible_items)
    if len(full_text) <= max_chars:
        return RenderedSkillHeads(
            text=full_text,
            compact=False,
            truncated=len(items) > len(visible_items),
            truncated_reason="max_items" if len(items) > len(visible_items) else None,
        )
    compact_text = _render_compact(visible_items)
    if len(compact_text) <= max_chars:
        return RenderedSkillHeads(
            text=compact_text,
            compact=True,
            truncated=len(items) > len(visible_items),
            truncated_reason="max_items" if len(items) > len(visible_items) else None,
        )
    return RenderedSkillHeads(
        text=compact_text[:max_chars],
        compact=True,
        truncated=True,
        truncated_reason="max_chars",
    )


def render_always_on_skills(items: list[SkillSpec]) -> str:
    chunks: list[str] = []
    for item in items:
        if item.meta.always_on and item.body:
            chunks.append(item.body.strip())
    return "\n\n".join(chunks)


def _render_full(items: list[SkillHead]) -> str:
    lines = ["Visible skills:"]
    for item in items:
        alias_text = f" Aliases: {', '.join(item.aliases)}." if item.aliases else ""
        lines.append(f"- {item.skill_id}: {item.description}{alias_text}")
    return "\n".join(lines)


def _render_compact(items: list[SkillHead]) -> str:
    return "\n".join(["Visible skills:", *[f"- {item.skill_id}" for item in items]])
