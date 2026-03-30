from marten_runtime.skills.models import SkillHead, SkillSpec


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


def render_always_on_skills(items: list[SkillSpec]) -> str:
    chunks: list[str] = []
    for item in items:
        if item.meta.always_on:
            chunks.append(item.body.strip())
    return "\n\n".join(chunks)
