from __future__ import annotations

from marten_runtime.mcp.client import MCPClient
from marten_runtime.mcp.normalize import normalize_mcp_request
from marten_runtime.mcp.models import MCPServerSpec


def build_mcp_capability_catalog(
    servers: list[MCPServerSpec],
    discovery: dict[str, dict[str, object]],
) -> str | None:
    lines: list[str] = []
    for server in servers:
        details = discovery.get(server.server_id, {})
        state = str(details.get("state", "unknown"))
        if state in {"disabled", "unavailable"}:
            continue
        source_layers = ", ".join(server.source_layers)
        lines.append(
            f"- {server.server_id}: tool_count={len(server.tools)}; transport={server.transport}; source={source_layers}"
        )
    if not lines:
        return None
    return "MCP capability catalog:\n" + "\n".join(lines)


def run_mcp_tool(
    payload: dict,
    servers: list[MCPServerSpec],
    client: MCPClient,
    discovery: dict[str, dict[str, object]],
) -> dict:
    server_map = {server.server_id: server for server in servers}
    normalized = normalize_mcp_request(server_map, payload)
    action = normalized.action
    if action == "list":
        server_id = normalized.server_id or ""
        visible = [server_map[server_id]] if server_id else list(server_map.values())
        return {
            "action": "list",
            "servers": [
                _server_summary(server, discovery.get(server.server_id, {}))
                for server in visible
                if server.enabled
            ],
        }
    if action == "detail":
        server = _require_server(server_map, normalized.server_id)
        return {
            "action": "detail",
            "server": _server_summary(server, discovery.get(server.server_id, {}), include_tools=True),
        }
    if action == "call":
        server = _require_server(server_map, normalized.server_id)
        tool_name = normalized.tool_name or ""
        arguments = normalized.arguments
        result = client.call_tool(server.server_id, tool_name, arguments)
        return {
            "action": "call",
            "server_id": server.server_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "payload": arguments,
            **result,
        }
    raise ValueError("unsupported mcp action")


def _require_server(server_map: dict[str, MCPServerSpec], server_id: str | None) -> MCPServerSpec:
    server_id = str(server_id or "").strip()
    if not server_id:
        raise ValueError("server_id is required")
    try:
        return server_map[server_id]
    except KeyError as exc:
        raise ValueError(f"unknown server_id: {server_id}") from exc


def _server_summary(
    server: MCPServerSpec,
    discovery: dict[str, object],
    *,
    include_tools: bool = False,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "server_id": server.server_id,
        "transport": server.transport,
        "source_layers": list(server.source_layers),
        "state": discovery.get("state", "unknown"),
        "tool_count": len(server.tools),
    }
    if include_tools:
        summary["tools"] = [
            {"name": tool.name, "description": tool.description}
            for tool in server.tools
        ]
    else:
        summary["tool_names"] = [tool.name for tool in server.tools]
    return summary
