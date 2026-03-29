from marten_runtime.skills.models import SkillSpec


class SkillRegistry:
    def __init__(self) -> None:
        self._items: dict[str, SkillSpec] = {}

    def register(self, spec: SkillSpec) -> None:
        self._items[spec.meta.skill_id] = spec

    def list_ids(self) -> list[str]:
        return sorted(self._items.keys())

    def get(self, skill_id: str) -> SkillSpec:
        return self._items[skill_id]
