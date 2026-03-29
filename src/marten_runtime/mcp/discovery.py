from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping

from marten_runtime.mcp.client import MCPClient
from marten_runtime.mcp.models import MCPServerSpec


def discover_mcp_tools(
    servers: list[MCPServerSpec],
    client: MCPClient,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for server in servers:
        if not server.enabled:
            result[server.server_id] = {"state": "disabled", "tool_count": 0, "error": None}
            continue
        if server.tools:
            result[server.server_id] = {
                "state": "configured",
                "tool_count": len(server.tools),
                "error": None,
            }
            continue
        if server.transport == "mock":
            result[server.server_id] = {"state": "configured", "tool_count": 0, "error": None}
            continue
        try:
            server.tools = _list_tools(client, server.server_id)
            result[server.server_id] = {
                "state": "discovered",
                "tool_count": len(server.tools),
                "error": None,
            }
        except Exception as exc:
            result[server.server_id] = {
                "state": "unavailable",
                "tool_count": 0,
                "error": str(exc),
            }
    return result


def _list_tools(client: MCPClient, server_id: str):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return client.list_tools(server_id)

    result: list[object] = []
    error: list[Exception] = []

    def worker() -> None:
        try:
            result.extend(client.list_tools(server_id))
        except Exception as exc:  # pragma: no cover - exercised through integration tests
            error.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result
