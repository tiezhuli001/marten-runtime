from marten_runtime.skills.service import SkillService


def run_skill_tool(payload: dict, skill_service: SkillService) -> dict:
    action = str(payload.get("action", "")).strip().lower()
    if action != "load":
        raise ValueError("unsupported skill action")
    skill_id = str(payload.get("skill_id", "")).strip()
    if not skill_id:
        raise ValueError("skill_id is required")
    skill = skill_service.load_skill(skill_id)
    return {
        "action": "load",
        "skill_id": skill.meta.skill_id,
        "name": skill.meta.name,
        "description": skill.meta.description,
        "body": skill.body or "",
    }
