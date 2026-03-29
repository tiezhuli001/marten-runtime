import unittest

from marten_runtime.gateway.models import InboundEnvelope
from marten_runtime.operator.delivery import finalize_delivery
from marten_runtime.agents.registry import AgentRegistry
from marten_runtime.agents.router import AgentRouter
from marten_runtime.agents.specs import AgentSpec
from datetime import datetime, timezone


class DeliveryTruthTests(unittest.TestCase):
    def test_delivery_fails_closed_until_validation_and_review_pass(self) -> None:
        validation_failed = finalize_delivery(False, True, run_id="run_1", trace_id="trace_1")
        review_failed = finalize_delivery(True, False, run_id="run_1", trace_id="trace_1")
        success = finalize_delivery(True, True, run_id="run_1", trace_id="trace_1")

        self.assertEqual(validation_failed.event_type, "error")
        self.assertEqual(validation_failed.reason, "validation_failed")
        self.assertEqual(review_failed.reason, "review_not_passed")
        self.assertEqual(success.event_type, "final")
        self.assertTrue(success.delivered)

    def test_router_can_route_coding_request_to_domain_agent(self) -> None:
        registry = AgentRegistry()
        registry.register(AgentSpec(agent_id="assistant", role="general_assistant", app_id="example_assistant"))
        registry.register(AgentSpec(agent_id="coding", role="coding_agent", app_id="example_assistant"))
        router = AgentRouter(registry, default_agent_id="assistant")
        envelope = InboundEnvelope(
            channel_id="http",
            user_id="demo",
            conversation_id="conv-code",
            message_id="msg-code-1",
            body="show current task",
            received_at=datetime.now(timezone.utc),
            dedupe_key="dedupe_code_1",
            trace_id="trace_code_1",
        )

        routed = router.route(envelope, active_agent_id="coding")

        self.assertEqual(routed.agent_id, "coding")


if __name__ == "__main__":
    unittest.main()
