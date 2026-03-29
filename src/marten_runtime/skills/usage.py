from pydantic import BaseModel


class SkillUsage(BaseModel):
    skill_id: str
    use_count: int = 0
    reject_count: int = 0
