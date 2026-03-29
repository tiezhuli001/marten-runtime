from __future__ import annotations

from hashlib import sha256

from pydantic import BaseModel, Field

from marten_runtime.skills.filter import filter_skills
from marten_runtime.skills.loader import SkillLoader
from marten_runtime.skills.models import SkillSpec
from marten_runtime.skills.render import render_always_on_skills
from marten_runtime.skills.snapshot import SkillSnapshot


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
        return SkillRuntimeView(
            visible_skills=visible,
            snapshot=snapshot,
            skill_heads_text=_render_skill_heads(snapshot),
            always_on_text=render_always_on_skills(visible) or None,
        )


def _render_skill_heads(snapshot: SkillSnapshot) -> str | None:
    if not snapshot.heads:
        return None
    lines = ["Visible skills:"]
    for head in snapshot.heads:
        lines.append(f"- {head.skill_id}: {head.description}")
    return "\n".join(lines)
