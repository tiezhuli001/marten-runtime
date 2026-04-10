import unittest
from datetime import datetime, timezone

from marten_runtime.agents.bindings import AgentBinding, AgentBindingRegistry
from marten_runtime.agents.registry import AgentRegistry
from marten_runtime.agents.router import AgentRouter
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.gateway.models import InboundEnvelope


class RouterTests(unittest.TestCase):
    def test_registry_returns_registered_agent(self) -> None:
        registry = AgentRegistry()
        spec = AgentSpec(agent_id="assistant", role="general_assistant", app_id="example_assistant")

        registry.register(spec)

        self.assertEqual(registry.get("assistant"), spec)

    def test_router_routes_regular_messages_to_assistant(self) -> None:
        registry = AgentRegistry()
        spec = AgentSpec(agent_id="assistant", role="general_assistant", app_id="example_assistant")
        registry.register(spec)
        router = AgentRouter(registry)
        envelope = InboundEnvelope(
            channel_id="http",
            user_id="demo",
            conversation_id="conv-1",
            message_id="msg-1",
            body="hello",
            received_at=datetime.now(timezone.utc),
            dedupe_key="dedupe_1",
            trace_id="trace_1",
        )

        routed = router.route(envelope)

        self.assertEqual(routed.agent_id, "assistant")
        self.assertEqual(routed.app_id, "example_assistant")

    def test_router_ignores_message_keywords_without_agent_binding(self) -> None:
        registry = AgentRegistry()
        registry.register(AgentSpec(agent_id="assistant", role="general_assistant", app_id="example_assistant"))
        registry.register(AgentSpec(agent_id="coding", role="coding_agent", app_id="example_assistant"))
        router = AgentRouter(registry, default_agent_id="assistant")
        envelope = InboundEnvelope(
            channel_id="http",
            user_id="demo",
            conversation_id="conv-2",
            message_id="msg-2",
            body="please fix bug in repo",
            received_at=datetime.now(timezone.utc),
            dedupe_key="dedupe_2",
            trace_id="trace_2",
        )

        routed = router.route(envelope)

        self.assertEqual(routed.agent_id, "assistant")

    def test_router_prefers_explicit_active_agent(self) -> None:
        registry = AgentRegistry()
        registry.register(AgentSpec(agent_id="assistant", role="general_assistant", app_id="example_assistant"))
        registry.register(AgentSpec(agent_id="coding", role="coding_agent", app_id="example_assistant"))
        router = AgentRouter(registry, default_agent_id="assistant")
        envelope = InboundEnvelope(
            channel_id="http",
            user_id="demo",
            conversation_id="conv-3",
            message_id="msg-3",
            body="hello",
            received_at=datetime.now(timezone.utc),
            dedupe_key="dedupe_3",
            trace_id="trace_3",
        )

        routed = router.route(envelope, active_agent_id="coding")

        self.assertEqual(routed.agent_id, "coding")

    def test_router_prefers_requested_agent_over_binding(self) -> None:
        registry = AgentRegistry()
        registry.register(AgentSpec(agent_id="assistant", role="general_assistant", app_id="example_assistant"))
        registry.register(AgentSpec(agent_id="ops", role="ops_agent", app_id="example_assistant"))
        registry.register(AgentSpec(agent_id="coding", role="coding_agent", app_id="example_assistant"))
        bindings = AgentBindingRegistry(
            [
                AgentBinding(
                    agent_id="ops",
                    channel_id="feishu",
                    conversation_id="conv-4",
                )
            ]
        )
        router = AgentRouter(registry, default_agent_id="assistant", bindings=bindings)
        envelope = InboundEnvelope(
            channel_id="feishu",
            user_id="demo",
            conversation_id="conv-4",
            message_id="msg-4",
            body="hello",
            received_at=datetime.now(timezone.utc),
            dedupe_key="dedupe_4",
            trace_id="trace_4",
        )

        routed = router.route(envelope, active_agent_id="ops", requested_agent_id="coding")

        self.assertEqual(routed.agent_id, "coding")

    def test_router_uses_conversation_binding_before_active_agent(self) -> None:
        registry = AgentRegistry()
        registry.register(AgentSpec(agent_id="assistant", role="general_assistant", app_id="example_assistant"))
        registry.register(AgentSpec(agent_id="ops", role="ops_agent", app_id="example_assistant"))
        registry.register(AgentSpec(agent_id="coding", role="coding_agent", app_id="example_assistant"))
        bindings = AgentBindingRegistry(
            [
                AgentBinding(
                    agent_id="ops",
                    channel_id="feishu",
                    conversation_id="conv-5",
                )
            ]
        )
        router = AgentRouter(registry, default_agent_id="assistant", bindings=bindings)
        envelope = InboundEnvelope(
            channel_id="feishu",
            user_id="demo",
            conversation_id="conv-5",
            message_id="msg-5",
            body="hello",
            received_at=datetime.now(timezone.utc),
            dedupe_key="dedupe_5",
            trace_id="trace_5",
        )

        routed = router.route(envelope, active_agent_id="coding")

        self.assertEqual(routed.agent_id, "ops")

    def test_router_uses_user_binding_when_no_conversation_binding_exists(self) -> None:
        registry = AgentRegistry()
        registry.register(AgentSpec(agent_id="assistant", role="general_assistant", app_id="example_assistant"))
        registry.register(AgentSpec(agent_id="ops", role="ops_agent", app_id="example_assistant"))
        bindings = AgentBindingRegistry(
            [
                AgentBinding(
                    agent_id="ops",
                    channel_id="feishu",
                    user_id="demo",
                )
            ]
        )
        router = AgentRouter(registry, default_agent_id="assistant", bindings=bindings)
        envelope = InboundEnvelope(
            channel_id="feishu",
            user_id="demo",
            conversation_id="conv-6",
            message_id="msg-6",
            body="hello",
            received_at=datetime.now(timezone.utc),
            dedupe_key="dedupe_6",
            trace_id="trace_6",
        )

        routed = router.route(envelope)

        self.assertEqual(routed.agent_id, "ops")

    def test_router_falls_back_to_binding_when_requested_agent_is_missing(self) -> None:
        registry = AgentRegistry()
        registry.register(AgentSpec(agent_id="assistant", role="general_assistant", app_id="example_assistant"))
        registry.register(AgentSpec(agent_id="ops", role="ops_agent", app_id="example_assistant"))
        bindings = AgentBindingRegistry(
            [
                AgentBinding(
                    agent_id="ops",
                    channel_id="feishu",
                    conversation_id="conv-7",
                )
            ]
        )
        router = AgentRouter(registry, default_agent_id="assistant", bindings=bindings)
        envelope = InboundEnvelope(
            channel_id="feishu",
            user_id="demo",
            conversation_id="conv-7",
            message_id="msg-7",
            body="hello",
            received_at=datetime.now(timezone.utc),
            dedupe_key="dedupe_7",
            trace_id="trace_7",
        )

        routed = router.route(envelope, requested_agent_id="missing")

        self.assertEqual(routed.agent_id, "ops")


if __name__ == "__main__":
    unittest.main()
