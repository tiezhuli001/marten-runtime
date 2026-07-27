import tomllib
from pathlib import Path

from marten_runtime.agents.defaults import DEFAULT_AGENT_ASSET_ROOT
from marten_runtime.agents.specs import AgentSpec


def load_agent_specs(path: str) -> list[AgentSpec]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    items = []
    for agent_id, payload in data.get("agents", {}).items():
        items.append(AgentSpec(**_normalize_agent_payload(agent_id, payload)))
    return sorted(items, key=lambda item: item.agent_id)


def _normalize_agent_payload(agent_id: str, payload: dict[str, object]) -> dict[str, object]:
    normalized = {
        "agent_id": agent_id,
        "enabled": True,
        "allowed_tools": [],
        "routing_description": "",
        "allowed_handoff_agents": [],
        "allowed_knowledge_namespaces": None,
        "allowed_knowledge_actions": None,
        "prompt_mode": "full",
        "model_profile": None,
        "observation_policy": "standard",
        "asset_root": DEFAULT_AGENT_ASSET_ROOT,
        "bootstrap_file": "BOOTSTRAP.md",
        "identity_file": "SOUL.md",
        "agents_file": "AGENTS.md",
        "tools_file": "TOOLS.md",
    }
    normalized.update(payload)
    normalized.pop("app_id", None)
    normalized["allowed_tools"] = list(dict.fromkeys(normalized.get("allowed_tools", [])))
    normalized["allowed_handoff_agents"] = list(
        dict.fromkeys(normalized.get("allowed_handoff_agents", []))
    )
    for key in ("allowed_knowledge_namespaces", "allowed_knowledge_actions"):
        if normalized.get(key) is not None:
            normalized[key] = list(dict.fromkeys(normalized[key]))
    return normalized
