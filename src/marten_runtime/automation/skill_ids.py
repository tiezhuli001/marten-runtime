from __future__ import annotations


GITHUB_TRENDING_DIGEST_SKILL_ID = "github_trending_digest"


def canonicalize_automation_skill_id(skill_id: str) -> str:
    return str(skill_id).strip()


def resolve_automation_runtime_skill_id(skill_id: str) -> str | None:
    canonical = canonicalize_automation_skill_id(skill_id)
    if not canonical:
        return None
    if canonical == GITHUB_TRENDING_DIGEST_SKILL_ID:
        return None
    return canonical


def display_name_for_automation_skill_id(skill_id: str) -> str | None:
    if canonicalize_automation_skill_id(skill_id) == GITHUB_TRENDING_DIGEST_SKILL_ID:
        return "GitHub热榜推荐"
    return None
