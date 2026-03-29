from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from collections.abc import Callable

from pydantic import BaseModel, Field


ToolHandler = Callable[[dict], dict]


class ToolDescriptor(BaseModel):
    name: str
    source_kind: str = "builtin"
    server_id: str | None = None
    backend_id: str | None = None
    description: str = ""


class ToolSnapshot(BaseModel):
    tool_snapshot_id: str
    config_snapshot_id: str = "cfg_bootstrap"
    builtin_tools: list[str] = Field(default_factory=list)
    mcp_tools: dict[str, dict[str, str]] = Field(default_factory=dict)
    tool_metadata: dict[str, dict[str, str]] = Field(default_factory=dict)
    degraded_servers: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def allows(self, tool_name: str) -> bool:
        return tool_name in self.builtin_tools or tool_name in self.mcp_tools

    def available_tools(self) -> list[str]:
        return sorted([*self.builtin_tools, *self.mcp_tools.keys()])


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._descriptors: dict[str, ToolDescriptor] = {}

    def register(
        self,
        name: str,
        handler: ToolHandler,
        *,
        source_kind: str = "builtin",
        server_id: str | None = None,
        backend_id: str | None = None,
        description: str = "",
    ) -> None:
        self._handlers[name] = handler
        self._descriptors[name] = ToolDescriptor(
            name=name,
            source_kind=source_kind,
            server_id=server_id,
            backend_id=backend_id,
            description=description,
        )

    def call(self, name: str, payload: dict) -> dict:
        return self._handlers[name](payload)

    def list(self) -> list[str]:
        return sorted(self._handlers.keys())

    def build_snapshot(self, allowed_tools: list[str] | None = None) -> ToolSnapshot:
        names = self._resolve_names(allowed_tools)
        builtin_tools: list[str] = []
        mcp_tools: dict[str, dict[str, str]] = {}
        tool_metadata: dict[str, dict[str, str]] = {}
        for name in names:
            descriptor = self._descriptors[name]
            tool_metadata[name] = {
                "source_kind": descriptor.source_kind,
                "server_id": descriptor.server_id or "",
                "backend_id": descriptor.backend_id or "",
                "description": descriptor.description,
            }
            if descriptor.source_kind == "mcp":
                mcp_tools[name] = {
                    "server_id": descriptor.server_id or "",
                    "backend_id": descriptor.backend_id or "",
                }
                continue
            builtin_tools.append(name)
        digest = sha256(",".join(names).encode("utf-8")).hexdigest()[:8]
        return ToolSnapshot(
            tool_snapshot_id=f"tool_{digest}",
            builtin_tools=builtin_tools,
            mcp_tools=mcp_tools,
            tool_metadata=tool_metadata,
        )

    def _resolve_names(self, allowed_tools: list[str] | None) -> list[str]:
        if allowed_tools is None or "*" in allowed_tools:
            return self.list()
        selectors = set(allowed_tools)
        names: list[str] = []
        for name in self.list():
            descriptor = self._descriptors[name]
            if name in selectors:
                names.append(name)
                continue
            if descriptor.source_kind == "builtin" and "builtin:*" in selectors:
                names.append(name)
                continue
            if descriptor.source_kind == "mcp" and "mcp:*" in selectors:
                names.append(name)
                continue
            if descriptor.source_kind == "mcp" and descriptor.server_id and f"mcp:{descriptor.server_id}" in selectors:
                names.append(name)
        return sorted(names)
