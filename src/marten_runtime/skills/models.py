import ast

from pydantic import BaseModel, Field


class SkillRequires(BaseModel):
    os: list[str] = Field(default_factory=list)
    bins: list[str] = Field(default_factory=list)
    env: list[str] = Field(default_factory=list)
    config: list[str] = Field(default_factory=list)


class SkillMeta(BaseModel):
    skill_id: str
    name: str
    description: str
    aliases: list[str] = Field(default_factory=list)
    enabled: bool = True
    agents: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    always_on: bool = False
    trust_tier: str = "untrusted"
    source_scope: str = "system"
    requires: SkillRequires = Field(default_factory=SkillRequires)

    @classmethod
    def from_front_matter(cls, data: dict[str, object], source_scope: str, skill_id: str) -> "SkillMeta":
        requires = SkillRequires(
            os=_as_list(data.get("requires_os")),
            bins=_as_list(data.get("requires_bins")),
            env=_as_list(data.get("requires_env")),
            config=_as_list(data.get("requires_config")),
        )
        return cls(
            skill_id=str(data.get("skill_id", skill_id)),
            name=str(data.get("name", skill_id)),
            description=str(data.get("description", "loaded from skill file")),
            aliases=_as_list(data.get("aliases")),
            enabled=bool(data.get("enabled", True)),
            agents=_as_list(data.get("agents")),
            channels=_as_list(data.get("channels")),
            tags=_as_list(data.get("tags")),
            always_on=bool(data.get("always_on", False)),
            trust_tier=str(data.get("trust_tier", "untrusted")),
            source_scope=source_scope,
            requires=requires,
        )


class SkillSpec(BaseModel):
    meta: SkillMeta
    body: str
    source_path: str


class SkillHead(BaseModel):
    skill_id: str
    name: str
    description: str
    aliases: list[str] = Field(default_factory=list)
    source_path: str


def parse_skill_markdown(body: str) -> tuple[dict[str, object], str]:
    lines = body.splitlines()
    if len(lines) >= 3 and lines[0].strip() == "---":
        try:
            end_idx = lines[1:].index("---") + 1
        except ValueError:
            return {}, body.strip()
        raw_meta = lines[1:end_idx]
        content = "\n".join(lines[end_idx + 1 :]).strip()
        meta: dict[str, object] = {}
        for line in raw_meta:
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            meta[key.strip()] = _parse_scalar(raw_value.strip())
        return meta, content
    return {}, body.strip()


def _parse_scalar(value: str) -> object:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        if "'" in inner or '"' in inner:
            normalized = value.replace("true", "True").replace("false", "False")
            return ast.literal_eval(normalized)
        return [part.strip() for part in inner.split(",") if part.strip()]
    return value


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]
