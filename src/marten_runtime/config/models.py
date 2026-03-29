from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ConfigSnapshot(BaseModel):
    config_snapshot_id: str = "cfg_bootstrap"
    assembled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_layers: list[str] = Field(default_factory=lambda: ["builtin", "config_dir", "env"])
    reload_generation: int = 0
    platform_digest: str = "platform_bootstrap"
    models_digest: str = "models_bootstrap"
    skills_digest: str = "skills_bootstrap"
    mcp_digest: str = "mcp_bootstrap"
    agents_digest: str = "agents_bootstrap"
    channels_digest: str = "channels_bootstrap"
    ops_digest: str = "ops_bootstrap"
    restart_required_sections: list[str] = Field(default_factory=list)
