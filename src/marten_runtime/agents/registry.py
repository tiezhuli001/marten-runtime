from marten_runtime.agents.specs import AgentSpec


class AgentRegistry:
    def __init__(self) -> None:
        self._items: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec) -> None:
        self._items[spec.agent_id] = spec

    def get(self, agent_id: str) -> AgentSpec:
        return self._items[agent_id]

    def list(self) -> list[AgentSpec]:
        return [self._items[key] for key in sorted(self._items)]

    def routing_catalog(self, source_agent_id: str) -> dict[str, str]:
        source = self.get(source_agent_id)
        catalog = {
            source.agent_id: source.routing_description or source.role,
        }
        for target_id in source.allowed_handoff_agents:
            target = self.get(target_id)
            catalog[target.agent_id] = target.routing_description
        return catalog

    def validate_handoff_catalog(self) -> None:
        for source in self.list():
            for target_id in source.allowed_handoff_agents:
                if target_id == source.agent_id:
                    raise ValueError(
                        f"agent {source.agent_id} cannot hand off to itself"
                    )
                try:
                    target = self.get(target_id)
                except KeyError as exc:
                    raise ValueError(
                        f"agent {source.agent_id} references unknown handoff target {target_id}"
                    ) from exc
                if not target.routing_description:
                    raise ValueError(
                        f"handoff target {target_id} requires routing_description"
                    )
