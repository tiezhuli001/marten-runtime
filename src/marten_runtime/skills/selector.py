from __future__ import annotations

import re

from marten_runtime.skills.models import SkillSpec


def select_activated_skills(items: list[SkillSpec], message: str) -> list[SkillSpec]:
    haystack = message.lower()
    tokens = set(re.findall(r"[a-z0-9_:-]+", haystack))
    activated: list[SkillSpec] = []
    for item in items:
        names = {
            item.meta.skill_id.lower(),
            item.meta.name.lower(),
            item.meta.name.lower().replace(" ", "_"),
        }
        tags = {tag.lower() for tag in item.meta.tags}
        if any(name in haystack for name in names) or bool(tokens & tags):
            activated.append(item)
    return activated
