from marten_runtime.agents.specs import AgentSpec
from marten_runtime.apps.runtime_defaults import DEFAULT_AGENT_ID


LEGACY_AGENT_ALIASES = {
    "assistant": DEFAULT_AGENT_ID,
}


class AgentRegistry:
    def __init__(self) -> None:
        self._items: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec) -> None:
        self._items[spec.agent_id] = spec

    def get(self, agent_id: str) -> AgentSpec:
        try:
            return self._items[agent_id]
        except KeyError:
            alias = LEGACY_AGENT_ALIASES.get(agent_id)
            if alias is None:
                raise
            return self._items[alias]
