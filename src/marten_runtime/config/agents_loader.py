import tomllib
from pathlib import Path

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
        "app_id": "example_assistant",
        "enabled": True,
        "allowed_tools": [],
        "prompt_mode": "full",
        "model_profile": None,
    }
    normalized.update(payload)
    normalized["allowed_tools"] = list(dict.fromkeys(normalized.get("allowed_tools", [])))
    return normalized
