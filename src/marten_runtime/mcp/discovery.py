from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Mapping

from marten_runtime.mcp.client import MCPClient
from marten_runtime.mcp.models import MCPServerSpec
from marten_runtime.runtime.cooperative_stop import raise_if_interrupted


def discover_mcp_tools(
    servers: list[MCPServerSpec],
    client: MCPClient,
    *,
    stop_event=None,
    deadline_monotonic: float | None = None,
    timeout_seconds_override: float | None = None,
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
            server.tools = _list_tools(
                client,
                server.server_id,
                stop_event=stop_event,
                deadline_monotonic=deadline_monotonic,
                timeout_seconds_override=timeout_seconds_override,
            )
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


def _list_tools(
    client: MCPClient,
    server_id: str,
    *,
    stop_event=None,
    deadline_monotonic: float | None = None,
    timeout_seconds_override: float | None = None,
):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return client.list_tools(server_id, **_list_tools_kwargs(client, stop_event, deadline_monotonic, timeout_seconds_override))

    result: list[object] = []
    error: list[Exception] = []

    def worker() -> None:
        try:
            result.extend(
                client.list_tools(
                    server_id,
                    **_list_tools_kwargs(
                        client,
                        stop_event,
                        deadline_monotonic,
                        timeout_seconds_override,
                    ),
                )
            )
        except Exception as exc:  # pragma: no cover - exercised through integration tests
            error.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while thread.is_alive():
        thread.join(timeout=0.05)
        raise_if_interrupted(
            stop_event=stop_event,
            deadline_monotonic=deadline_monotonic,
            cancelled_message="MCP_CALL_CANCELLED",
            timed_out_message="MCP_CALL_TIMED_OUT",
        )
    if error:
        raise error[0]
    return result


def _list_tools_kwargs(
    client: MCPClient,
    stop_event,
    deadline_monotonic: float | None,
    timeout_seconds_override: float | None,
) -> dict[str, object]:
    try:
        signature = inspect.signature(client.list_tools)
    except (TypeError, ValueError):
        return {}
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    candidates = {
        "stop_event": stop_event,
        "deadline_monotonic": deadline_monotonic,
        "timeout_seconds_override": timeout_seconds_override,
    }
    return {
        key: value
        for key, value in candidates.items()
        if value is not None and (accepts_kwargs or key in signature.parameters)
    }
