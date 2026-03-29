import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class AppBootstrapConfig(BaseModel):
    root: str
    agents: str
    identity: str | None = None
    tools: str | None = None
    user: str | None = None
    bootstrap: str | None = None
    memory: str | None = None


class AppSkillsConfig(BaseModel):
    app_dir: str = "skills"
    required: list[str] = Field(default_factory=list)


class AppMCPConfig(BaseModel):
    required_servers: list[str] = Field(default_factory=list)


class AppManifest(BaseModel):
    app_id: str
    app_version: str
    default_agent: str
    prompt_mode: str = "full"
    delegation_policy: str = "isolated_session_only"
    bootstrap: AppBootstrapConfig
    skills: AppSkillsConfig = Field(default_factory=AppSkillsConfig)
    mcp: AppMCPConfig = Field(default_factory=AppMCPConfig)

    @property
    def bootstrap_manifest_id(self) -> str:
        return f"boot_{self.app_id}_{self.prompt_mode}"


def load_app_manifest(path: str) -> AppManifest:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return AppManifest(**data)
