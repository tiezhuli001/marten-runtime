from pydantic import BaseModel, Field


class MCPToolSpec(BaseModel):
    name: str
    description: str = ""


class MCPServerSpec(BaseModel):
    server_id: str
    source_layers: list[str] = Field(default_factory=list)
    transport: str = "mock"
    backend_id: str = "remote-mock"
    enabled: bool = True
    timeout_ms: int = 10_000
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    adapter: str | None = None
    tools: list[MCPToolSpec] = Field(default_factory=list)
