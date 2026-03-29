from pydantic import BaseModel, Field

from marten_runtime.skills.models import SkillHead, SkillSpec
from marten_runtime.skills.render import build_skill_heads


class SkillSnapshot(BaseModel):
    skill_snapshot_id: str
    heads: list[SkillHead] = Field(default_factory=list)
    always_on_ids: list[str] = Field(default_factory=list)
    rejected_skill_ids: list[str] = Field(default_factory=list)

    @classmethod
    def from_skills(cls, snapshot_id: str, items: list[SkillSpec]) -> "SkillSnapshot":
        return cls(
            skill_snapshot_id=snapshot_id,
            heads=build_skill_heads(items),
            always_on_ids=[item.meta.skill_id for item in items if item.meta.always_on],
        )
