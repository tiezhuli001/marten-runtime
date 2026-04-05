from __future__ import annotations

import json

from marten_runtime.mcp.models import MCPServerSpec
from marten_runtime.mcp.request_models import NormalizedMCPRequest


def normalize_mcp_request(
    server_map: dict[str, MCPServerSpec],
    payload: dict,
) -> NormalizedMCPRequest:
    normalized_payload = dict(payload)
    action = str(normalized_payload.get("action", "")).strip().lower()
    if not action:
        action = _infer_action(normalized_payload)
    server_id = _normalize_optional_text(normalized_payload.get("server_id"))
    tool_name = _normalize_optional_text(
        normalized_payload.get("tool_name")
        or normalized_payload.get("tool")
        or normalized_payload.get("name")
    )
    arguments = _normalize_arguments(
        normalized_payload.get("arguments", normalized_payload.get("params", normalized_payload.get("payload")))
    )
    arguments = _normalize_tool_specific_arguments(tool_name, arguments)
    if action == "call" and not arguments:
        arguments = _collect_inline_arguments(normalized_payload)
        arguments = _normalize_tool_specific_arguments(tool_name, arguments)
    if action == "call" and not server_id:
        server_id = _infer_server_id(server_map, tool_name)
    if action == "call" and not server_id:
        raise ValueError("server_id is required")
    if action == "call" and server_id:
        _require_server(server_map, server_id)
    if action == "call" and not tool_name:
        tool_name = _infer_tool_name(server_map, server_id)
    if action == "call" and not tool_name:
        raise ValueError("tool_name is required")
    return NormalizedMCPRequest(
        action=action,
        server_id=server_id,
        tool_name=tool_name,
        arguments=arguments,
    )


def _infer_action(payload: dict) -> str:
    if payload.get("server_id") or payload.get("tool_name") or payload.get("tool") or payload.get("query"):
        return "call"
    return "list"


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_arguments(arguments: object) -> dict:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        normalized = arguments.strip()
        if not normalized:
            return {}
        parsed = json.loads(normalized)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("arguments must be an object")


def _collect_inline_arguments(payload: dict) -> dict:
    control_keys = {"action", "server_id", "tool_name", "tool", "name", "arguments", "params", "payload"}
    return {key: value for key, value in payload.items() if key not in control_keys}


def _normalize_tool_specific_arguments(tool_name: str | None, arguments: dict) -> dict:
    if tool_name == "search_repositories" and "query" not in arguments and "q" in arguments:
        normalized = dict(arguments)
        normalized["query"] = normalized.pop("q")
        return normalized
    return arguments


def _require_server(server_map: dict[str, MCPServerSpec], server_id: str) -> MCPServerSpec:
    try:
        return server_map[server_id]
    except KeyError as exc:
        raise ValueError(f"unknown server_id: {server_id}") from exc


def _infer_server_id(server_map: dict[str, MCPServerSpec], tool_name: str | None) -> str | None:
    if tool_name:
        matches = [
            server.server_id
            for server in server_map.values()
            if any(tool.name == tool_name for tool in server.tools)
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"ambiguous tool_name: {tool_name}")
    single_tool_servers = [server.server_id for server in server_map.values() if len(server.tools) == 1]
    if len(single_tool_servers) == 1:
        return single_tool_servers[0]
    return None


def _infer_tool_name(
    server_map: dict[str, MCPServerSpec],
    server_id: str | None,
) -> str | None:
    if not server_id:
        return None
    server = _require_server(server_map, server_id)
    if len(server.tools) == 1:
        return server.tools[0].name
    return None
