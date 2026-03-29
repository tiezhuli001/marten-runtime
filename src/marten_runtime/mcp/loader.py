import json
import tomllib
from pathlib import Path

from marten_runtime.config.file_resolver import resolve_config_path
from marten_runtime.mcp.models import MCPServerSpec, MCPToolSpec


def load_mcp_servers(mcp_toml_path: str, compat_json_path: str | None = None) -> list[MCPServerSpec]:
    merged: dict[str, dict] = {}
    if compat_json_path:
        compat_path = Path(compat_json_path)
        if compat_path.exists():
            compat = json.loads(compat_path.read_text(encoding="utf-8"))
            for server_id, item in compat.get("servers", {}).items():
                merged[server_id] = {
                    "server_id": server_id,
                    "source_layers": ["mcps.json"],
                    "transport": item.get("transport", "mock"),
                    "backend_id": item.get("backend_id", server_id),
                    "enabled": item.get("enabled", True),
                    "timeout_ms": _resolve_timeout_ms(item),
                    "command": item.get("command"),
                    "args": [str(arg) for arg in item.get("args", [])],
                    "env": {str(key): str(value) for key, value in item.get("env", {}).items()},
                    "cwd": item.get("cwd"),
                    "url": item.get("url"),
                    "headers": {str(key): str(value) for key, value in item.get("headers", {}).items()},
                    "adapter": item.get("adapter"),
                    "tools": [],
                }
    resolved = resolve_config_path(mcp_toml_path)
    if resolved is not None:
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
        source_label = f"config/{resolved.name}"
        for item in data.get("servers", []):
            current = merged.get(item["server_id"], {})
            source_layers = list(current.get("source_layers", []))
            if source_label not in source_layers:
                source_layers.append(source_label)
            current.update(item)
            current["source_layers"] = source_layers
            if "tools" in current:
                current["tools"] = [MCPToolSpec(**tool) for tool in current.get("tools", [])]
            merged[item["server_id"]] = current
    servers = [MCPServerSpec(**item) for item in merged.values()]
    return sorted(servers, key=lambda item: item.server_id)


def _resolve_timeout_ms(item: dict) -> int:
    if "timeout_ms" in item and item["timeout_ms"] is not None:
        return int(item["timeout_ms"])
    if "timeout_seconds" in item and item["timeout_seconds"] is not None:
        return int(float(item["timeout_seconds"]) * 1000)
    return 10_000
