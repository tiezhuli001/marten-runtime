from marten_runtime.agents.bindings import AgentBindingRegistry
from marten_runtime.agents.registry import AgentRegistry
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.gateway.models import InboundEnvelope


class AgentRouter:
    def __init__(
        self,
        registry: AgentRegistry,
        default_agent_id: str = "assistant",
        bindings: AgentBindingRegistry | None = None,
    ) -> None:
        self.registry = registry
        self.default_agent_id = default_agent_id
        self.bindings = bindings or AgentBindingRegistry()

    def route(
        self,
        envelope: InboundEnvelope,
        active_agent_id: str | None = None,
        requested_agent_id: str | None = None,
    ) -> AgentSpec:
        binding = self.bindings.match(envelope)
        binding_agent_id = binding.agent_id if binding is not None else None
        for candidate in [requested_agent_id, binding_agent_id, active_agent_id, self.default_agent_id]:
            if candidate is None:
                continue
            try:
                return self.registry.get(candidate)
            except KeyError:
                continue
        raise KeyError("no routable agent registered")
