import tomllib
from pathlib import Path

from marten_runtime.agents.specs import AgentSpec


def load_agent_specs(path: str) -> list[AgentSpec]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    items = []
    for agent_id, payload in data.get("agents", {}).items():
        items.append(AgentSpec(agent_id=agent_id, **payload))
    return sorted(items, key=lambda item: item.agent_id)
