from typing import Literal

from pydantic import BaseModel, Field, ConfigDict, field_validator

from marten_runtime.agents.defaults import DEFAULT_AGENT_ASSET_ROOT


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str
    role: str
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list)
    routing_description: str = ""
    allowed_handoff_agents: list[str] = Field(default_factory=list)
    allowed_knowledge_namespaces: list[str] | None = None
    allowed_knowledge_actions: list[str] | None = None
    prompt_mode: str = "full"
    model_profile: str | None = None
    observation_policy: Literal["standard", "sensitive_bazi"] = "standard"
    asset_root: str = DEFAULT_AGENT_ASSET_ROOT
    bootstrap_file: str = "BOOTSTRAP.md"
    identity_file: str = "SOUL.md"
    agents_file: str = "AGENTS.md"
    tools_file: str = "TOOLS.md"

    @field_validator("allowed_knowledge_namespaces")
    @classmethod
    def validate_knowledge_namespaces(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = list(dict.fromkeys(str(item).strip() for item in value))
        if any(not item for item in normalized):
            raise ValueError("allowed_knowledge_namespaces cannot contain blank values")
        return normalized

    @field_validator("routing_description")
    @classmethod
    def validate_routing_description(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("allowed_handoff_agents")
    @classmethod
    def validate_allowed_handoff_agents(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(str(item).strip() for item in value))
        if any(not item for item in normalized):
            raise ValueError("allowed_handoff_agents cannot contain blank values")
        return normalized

    @field_validator("allowed_knowledge_actions")
    @classmethod
    def validate_knowledge_actions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        allowed = {
            "ingest_text",
            "ingest_file",
            "ingest_status",
            "cancel_ingest",
            "search",
            "get_chunk",
            "delete_source",
            "reindex",
            "stats",
            "model_status",
            "unload_models",
        }
        normalized = list(dict.fromkeys(str(item).strip() for item in value))
        if any(item not in allowed for item in normalized):
            raise ValueError("allowed_knowledge_actions contains an unsupported action")
        return normalized

    @property
    def prompt_manifest_id(self) -> str:
        return f"agent_{self.agent_id}_{self.prompt_mode}"
