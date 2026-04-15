from pydantic import BaseModel, Field


class AgentSpec(BaseModel):
    agent_id: str
    role: str
    app_id: str = "main_agent"
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list)
    prompt_mode: str = "full"
    model_profile: str | None = None
