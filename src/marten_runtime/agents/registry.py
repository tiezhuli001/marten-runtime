from marten_runtime.agents.specs import AgentSpec


class AgentRegistry:
    def __init__(self) -> None:
        self._items: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec) -> None:
        self._items[spec.agent_id] = spec

    def get(self, agent_id: str) -> AgentSpec:
        return self._items[agent_id]
