from __future__ import annotations

from hashlib import sha256

from pydantic import BaseModel, Field

from marten_runtime.skills.filter import filter_skills
from marten_runtime.skills.loader import SkillLoader
from marten_runtime.skills.models import SkillSpec
from marten_runtime.skills.render import render_always_on_skills, render_skill_heads
from marten_runtime.skills.snapshot import SkillSnapshot

DEFAULT_SKILL_HEAD_MAX_CHARS = 1200
DEFAULT_SKILL_HEAD_MAX_ITEMS = 24


class SkillRuntimeView(BaseModel):
    visible_skills: list[SkillSpec] = Field(default_factory=list)
    snapshot: SkillSnapshot = Field(
        default_factory=lambda: SkillSnapshot(skill_snapshot_id="skill_default")
    )
    skill_heads_text: str | None = None
    always_on_text: str | None = None


class SkillService:
    def __init__(self, roots: list[str]) -> None:
        self.loader = SkillLoader(roots)

    def build_runtime(
        self,
        *,
        agent_id: str,
        channel_id: str,
        env: dict[str, str] | None = None,
        config: dict[str, str] | None = None,
    ) -> SkillRuntimeView:
        visible = filter_skills(
            agent_id=agent_id,
            channel_id=channel_id,
            items=self.loader.load_all(),
            env=env,
            config=config,
        )
        digest = sha256(
            ",".join(skill.meta.skill_id for skill in visible).encode("utf-8")
        ).hexdigest()[:8]
        snapshot = SkillSnapshot.from_skills(f"skill_{digest}", visible)
        always_on_skills = [
            self.loader.load_skill(skill.meta.skill_id)
            for skill in visible
            if skill.meta.always_on
        ]
        return SkillRuntimeView(
            visible_skills=visible,
            snapshot=snapshot,
            skill_heads_text=render_skill_heads(
                snapshot.heads,
                max_chars=DEFAULT_SKILL_HEAD_MAX_CHARS,
                max_items=DEFAULT_SKILL_HEAD_MAX_ITEMS,
            ).text,
            always_on_text=render_always_on_skills(always_on_skills) or None,
        )

    def load_skill(self, skill_id: str) -> SkillSpec:
        return self.loader.load_skill(skill_id)
