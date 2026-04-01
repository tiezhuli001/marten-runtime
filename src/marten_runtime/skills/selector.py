from marten_runtime.skills.models import SkillSpec


def select_activated_skills(
    items: list[SkillSpec],
    message: str,
    *,
    explicit_skill_ids: list[str] | None = None,
) -> list[SkillSpec]:
    explicit = {item.lower() for item in (explicit_skill_ids or [])}
    return [item for item in items if item.meta.skill_id.lower() in explicit]
