from pathlib import Path

from marten_runtime.skills.models import (
    SkillMeta,
    SkillSpec,
    parse_skill_body_markdown,
    parse_skill_head_markdown,
)


class SkillLoader:
    def __init__(self, roots: list[str]) -> None:
        self.roots = [Path(root) for root in roots]

    def load_all(self, *, include_bodies: bool = False) -> list[SkillSpec]:
        merged: dict[str, SkillSpec] = {}
        for root in self.roots:
            if not root.exists():
                continue
            for path in sorted(root.iterdir()):
                skill_path = path / "SKILL.md"
                if not path.is_dir() or not skill_path.exists():
                    continue
                spec = (
                    self._read_skill_body(skill_path, source_scope=root.name)
                    if include_bodies
                    else self._read_skill_head(skill_path, source_scope=root.name)
                )
                merged[spec.meta.skill_id] = spec
        return [merged[key] for key in sorted(merged.keys())]

    def load_skill(self, skill_id: str) -> SkillSpec:
        for root in reversed(self.roots):
            skill_path = root / skill_id / "SKILL.md"
            if skill_path.exists():
                return self._read_skill_body(skill_path, source_scope=root.name)
        raise KeyError(skill_id)

    def _read_skill_head(self, path: Path, *, source_scope: str) -> SkillSpec:
        raw_body = path.read_text(encoding="utf-8")
        front_matter = parse_skill_head_markdown(raw_body)
        return SkillSpec(
            meta=SkillMeta.from_front_matter(front_matter, source_scope=source_scope, skill_id=path.parent.name),
            body=None,
            source_path=str(path),
        )

    def _read_skill_body(self, path: Path, *, source_scope: str) -> SkillSpec:
        raw_body = path.read_text(encoding="utf-8")
        front_matter, content = parse_skill_body_markdown(raw_body)
        return SkillSpec(
            meta=SkillMeta.from_front_matter(front_matter, source_scope=source_scope, skill_id=path.parent.name),
            body=content,
            source_path=str(path),
        )
