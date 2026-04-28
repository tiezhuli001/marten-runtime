from __future__ import annotations

from pydantic import BaseModel

from marten_runtime.agents.ids import canonicalize_runtime_agent_id
from marten_runtime.gateway.models import InboundEnvelope


class AgentBinding(BaseModel):
    agent_id: str
    channel_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None
    mention_required: bool = False
    default: bool = False

    def model_post_init(self, __context: object) -> None:
        self.agent_id = canonicalize_runtime_agent_id(self.agent_id, default="main") or "main"

    def matches(self, envelope: InboundEnvelope) -> bool:
        if self.channel_id and self.channel_id != envelope.channel_id:
            return False
        if self.conversation_id and self.conversation_id != envelope.conversation_id:
            return False
        if self.user_id and self.user_id != envelope.user_id:
            return False
        if self.mention_required and "@" not in envelope.body:
            return False
        return True

    def priority(self) -> tuple[int, int]:
        if self.conversation_id is not None:
            return (0, 0 if self.mention_required else 1)
        if self.user_id is not None:
            return (1, 0 if self.mention_required else 1)
        if self.default:
            return (2, 0 if self.mention_required else 1)
        return (3, 0 if self.mention_required else 1)


class AgentBindingRegistry:
    def __init__(self, bindings: list[AgentBinding] | None = None) -> None:
        self._bindings = list(bindings or [])

    def match(self, envelope: InboundEnvelope) -> AgentBinding | None:
        matches = [binding for binding in self._bindings if binding.matches(envelope)]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.priority())[0]

    def list(self) -> list[AgentBinding]:
        return list(self._bindings)
