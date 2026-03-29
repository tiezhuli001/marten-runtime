from marten_runtime.mcp.models import MCPServerSpec


class MCPRegistry:
    def __init__(self) -> None:
        self._servers: dict[str, MCPServerSpec] = {}

    def register(self, spec: MCPServerSpec) -> None:
        self._servers[spec.server_id] = spec

    def list_servers(self) -> list[str]:
        return sorted(self._servers.keys())

    def get(self, server_id: str) -> MCPServerSpec:
        return self._servers[server_id]
