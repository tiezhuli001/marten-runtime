from __future__ import annotations

import time

from marten_runtime.mcp.client import MCPClient
from marten_runtime.mcp.models import MCPToolSpec
from marten_runtime.mcp.models import MCPServerSpec
from marten_runtime.mcp.normalize import normalize_mcp_request, server_id_candidates

_TRANSIENT_MCP_ERROR_MARKERS = (
    " eof",
    ": eof",
    " timed out",
    " timeout",
    "connection reset",
    "connection aborted",
    "broken pipe",
    "temporarily unavailable",
    "unexpected end of file",
)
_TRANSIENT_MCP_RETRY_DELAYS_SECONDS = (3.0, 5.0)


def build_mcp_capability_catalog(
    servers: list[MCPServerSpec],
    discovery: dict[str, dict[str, object]],
) -> str | None:
    lines: list[str] = [
        "MCP family contract:",
        '- Use {"action":"list"} to inspect visible servers.',
        '- Use {"action":"detail","server_id":"<exact server_id>"} to inspect one server and copy exact tool names.',
        '- Use {"action":"call","server_id":"<exact server_id>","tool_name":"<exact tool name>","arguments":{...}} for execution.',
        "- Copy server_id and tool_name exactly from this catalog or from a prior mcp result; do not rename or invent aliases.",
        "",
        "MCP capability catalog:",
    ]
    for server in servers:
        details = discovery.get(server.server_id, {})
        state = str(details.get("state", "unknown"))
        if state in {"disabled", "unavailable"}:
            continue
        source_layers = ", ".join(server.source_layers)
        tool_names = ", ".join(tool.name for tool in server.tools) or "<none>"
        lines.append(
            f"- {server.server_id}: tool_count={len(server.tools)}; transport={server.transport}; source={source_layers}; tools=[{tool_names}]"
        )
    if len(lines) == 7:
        return None
    return "\n".join(lines)


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
        result = _call_tool_with_transient_retry(client, server.server_id, tool_name, arguments)
        if bool(result.get("ok")) and not bool(result.get("is_error")):
            _heal_discovery_after_successful_call(
                server=server,
                tool_name=tool_name,
                client=client,
                discovery=discovery,
            )
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
    for candidate in _server_id_candidates(server_id):
        try:
            return server_map[candidate]
        except KeyError:
            continue
    raise ValueError(f"unknown server_id: {server_id}")


def _call_tool_with_transient_retry(
    client: MCPClient,
    server_id: str,
    tool_name: str,
    arguments: dict,
) -> dict:
    attempts = len(_TRANSIENT_MCP_RETRY_DELAYS_SECONDS) + 1
    last_result: dict | None = None
    for attempt in range(attempts):
        try:
            result = client.call_tool(server_id, tool_name, arguments)
        except Exception as exc:
            if attempt + 1 < attempts and _is_transient_mcp_exception(exc):
                time.sleep(_TRANSIENT_MCP_RETRY_DELAYS_SECONDS[attempt])
                continue
            raise
        last_result = result
        if attempt + 1 < attempts and _is_transient_mcp_error_result(result):
            time.sleep(_TRANSIENT_MCP_RETRY_DELAYS_SECONDS[attempt])
            continue
        return result
    return last_result or {}


def _is_transient_mcp_error_result(result: dict) -> bool:
    if bool(result.get("ok")) or not bool(result.get("is_error")):
        return False
    return _looks_like_transient_transport_text(str(result.get("result_text") or ""))


def _is_transient_mcp_exception(exc: Exception | type[Exception]) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, OSError, EOFError, BrokenPipeError)):
        return True
    return _looks_like_transient_transport_text(str(exc))


def _looks_like_transient_transport_text(text: str) -> bool:
    normalized = f" {text.strip().lower()} "
    return any(marker in normalized for marker in _TRANSIENT_MCP_ERROR_MARKERS)


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


def _server_id_candidates(server_id: str | None) -> list[str]:
    return server_id_candidates(server_id)


def _heal_discovery_after_successful_call(
    *,
    server: MCPServerSpec,
    tool_name: str,
    client: MCPClient,
    discovery: dict[str, dict[str, object]],
) -> None:
    try:
        refreshed_tools = client.list_tools(server.server_id)
    except Exception:
        refreshed_tools = []
    if refreshed_tools:
        server.tools = refreshed_tools
    elif tool_name and not any(tool.name == tool_name for tool in server.tools):
        server.tools.append(MCPToolSpec(name=tool_name, description=""))
    tool_count = len(server.tools)
    discovery[server.server_id] = {
        "state": "discovered" if tool_count > 0 else "configured",
        "tool_count": tool_count,
        "error": None,
    }
