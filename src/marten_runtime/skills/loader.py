from pathlib import Path

from marten_runtime.skills.models import SkillMeta, SkillSpec, parse_skill_markdown


class SkillLoader:
    def __init__(self, roots: list[str]) -> None:
        self.roots = [Path(root) for root in roots]

    def load_all(self) -> list[SkillSpec]:
        merged: dict[str, SkillSpec] = {}
        for root in self.roots:
            if not root.exists():
                continue
            for path in sorted(root.glob("**/SKILL.md")):
                raw_body = path.read_text(encoding="utf-8")
                front_matter, content = parse_skill_markdown(raw_body)
                spec = SkillSpec(
                    meta=SkillMeta.from_front_matter(front_matter, source_scope=root.name, skill_id=path.parent.name),
                    body=content,
                    source_path=str(path),
                )
                merged[spec.meta.skill_id] = spec
        return [merged[key] for key in sorted(merged.keys())]
