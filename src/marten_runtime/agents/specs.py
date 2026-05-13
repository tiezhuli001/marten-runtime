from pydantic import BaseModel, Field, ConfigDict

from marten_runtime.agents.defaults import DEFAULT_AGENT_ASSET_ROOT


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str
    role: str
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list)
    prompt_mode: str = "full"
    model_profile: str | None = None
    asset_root: str = DEFAULT_AGENT_ASSET_ROOT
    bootstrap_file: str = "BOOTSTRAP.md"
    identity_file: str = "SOUL.md"
    agents_file: str = "AGENTS.md"
    tools_file: str = "TOOLS.md"

    @property
    def prompt_manifest_id(self) -> str:
        return f"agent_{self.agent_id}_{self.prompt_mode}"
