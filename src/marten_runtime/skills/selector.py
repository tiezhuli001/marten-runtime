from __future__ import annotations

import re

from marten_runtime.skills.models import SkillSpec


AUTOMATION_PRIORITY_TAGS = {"automation", "recurring", "tasks", "management", "schedule"}
AUTOMATION_INTENT_PATTERNS = (
    "自动任务",
    "定时任务",
    "暂停",
    "恢复",
    "删除",
    "删掉",
    "移除",
    "修改",
    "更新",
    "有哪些任务",
    "哪些任务",
)


def select_activated_skills(
    items: list[SkillSpec],
    message: str,
    *,
    explicit_skill_ids: list[str] | None = None,
) -> list[SkillSpec]:
    haystack = message.lower()
    tokens = set(re.findall(r"[a-z0-9_:-]+", haystack))
    explicit = {item.lower() for item in (explicit_skill_ids or [])}
    activated: list[SkillSpec] = []
    for item in items:
        if item.meta.skill_id.lower() in explicit:
            activated.append(item)
            continue
        names = {
            item.meta.skill_id.lower(),
            item.meta.name.lower(),
            item.meta.name.lower().replace(" ", "_"),
        }
        names.update(alias.lower() for alias in item.meta.aliases)
        tags = {tag.lower() for tag in item.meta.tags}
        is_automation_skill = bool(AUTOMATION_PRIORITY_TAGS & tags)
        if (
            any(name in haystack for name in names)
            or bool(tokens & tags)
            or (is_automation_skill and _looks_like_automation_management_intent(haystack))
        ):
            activated.append(item)
    if _looks_like_automation_management_intent(haystack) and any(
        AUTOMATION_PRIORITY_TAGS & {tag.lower() for tag in item.meta.tags} for item in activated
    ):
        prioritized = [
            item
            for item in activated
            if AUTOMATION_PRIORITY_TAGS & {tag.lower() for tag in item.meta.tags}
        ]
        if prioritized:
            return prioritized
    return activated


def _looks_like_automation_management_intent(haystack: str) -> bool:
    return any(pattern in haystack for pattern in AUTOMATION_INTENT_PATTERNS)
