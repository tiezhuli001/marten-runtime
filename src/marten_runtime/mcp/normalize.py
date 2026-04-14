from __future__ import annotations

import json

from marten_runtime.mcp.models import MCPServerSpec
from marten_runtime.mcp.request_models import NormalizedMCPRequest

# Normalize only field/container/canonical-parameter shape. This layer may
# reconcile alias keys and canonical parameter names, but it must not perform
# semantic query repair, intent routing, or provider-specific policy decisions.

def normalize_mcp_request(
    server_map: dict[str, MCPServerSpec],
    payload: dict,
) -> NormalizedMCPRequest:
    normalized_payload = dict(payload)
    action = str(normalized_payload.get("action", "")).strip().lower()
    action, normalized_payload = _normalize_action_alias(action, normalized_payload)
    if not action:
        action = _infer_action(normalized_payload)
    server_id = _normalize_optional_text(
        normalized_payload.get("server_id")
        or normalized_payload.get("server")
        or normalized_payload.get("server_name")
    )
    tool_name = _normalize_optional_text(
        normalized_payload.get("tool_name")
        or normalized_payload.get("tool")
        or normalized_payload.get("name")
    )
    arguments = _normalize_arguments(
        normalized_payload.get(
            "arguments",
            normalized_payload.get(
                "params",
                normalized_payload.get(
                    "parameters",
                    normalized_payload.get(
                        "payload",
                        normalized_payload.get(
                            "input",
                            normalized_payload.get("args"),
                        ),
                    ),
                ),
            ),
        )
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
    if (
        payload.get("server_id")
        or payload.get("server")
        or payload.get("server_name")
        or payload.get("tool_name")
        or payload.get("tool")
        or payload.get("name")
        or payload.get("query")
    ):
        return "call"
    return "list"


def _normalize_action_alias(action: str, payload: dict) -> tuple[str, dict]:
    normalized_action = action.strip().lower()
    normalized_payload = dict(payload)
    if normalized_action in {"list", "detail", "call", ""}:
        return normalized_action, normalized_payload
    if normalized_payload.get("tool_name") or normalized_payload.get("tool") or normalized_payload.get("name"):
        return normalized_action, normalized_payload
    normalized_payload["tool"] = normalized_action
    return "call", normalized_payload


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
    control_keys = {
        "action",
        "server_id",
        "server",
        "server_name",
        "tool_name",
        "tool",
        "name",
        "arguments",
        "params",
        "parameters",
        "payload",
        "input",
        "args",
    }
    return {key: value for key, value in payload.items() if key not in control_keys}


def _normalize_tool_specific_arguments(tool_name: str | None, arguments: dict) -> dict:
    normalized = dict(arguments)
    if "per_page" not in normalized and "perPage" in normalized:
        normalized["per_page"] = normalized.pop("perPage")
    if tool_name == "search_repositories" and "query" not in normalized and "q" in normalized:
        normalized["query"] = normalized.pop("q")
    if tool_name in {"list_commits", "get_commit"} and "owner" not in normalized:
        repo_value = normalized.get("repo")
        if isinstance(repo_value, str) and "/" in repo_value:
            owner, repo = repo_value.split("/", 1)
            owner = owner.strip()
            repo = repo.strip()
            if owner and repo:
                normalized["owner"] = owner
                normalized["repo"] = repo
    return normalized


def _require_server(server_map: dict[str, MCPServerSpec], server_id: str) -> MCPServerSpec:
    for candidate in _server_id_candidates(server_id):
        try:
            return server_map[candidate]
        except KeyError:
            continue
    raise ValueError(f"unknown server_id: {server_id}")


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


def server_id_candidates(server_id: str | None) -> list[str]:
    normalized = str(server_id or "").strip()
    if not normalized:
        return []
    candidates = [normalized]
    if "_" in normalized:
        candidates.append(normalized.replace("_", "-"))
    if "-" in normalized:
        candidates.append(normalized.replace("-", "_"))
    deduped: list[str] = []
    for item in candidates:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _server_id_candidates(server_id: str | None) -> list[str]:
    return server_id_candidates(server_id)
