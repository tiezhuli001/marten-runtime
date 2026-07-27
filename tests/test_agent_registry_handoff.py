import unittest

from marten_runtime.agents.registry import AgentRegistry
from marten_runtime.agents.specs import AgentSpec


class AgentRegistryHandoffTests(unittest.TestCase):
    def test_catalog_contains_source_and_authorized_targets(self) -> None:
        registry = AgentRegistry()
        registry.register(
            AgentSpec(
                agent_id="main",
                role="general_assistant",
                routing_description="general",
                allowed_handoff_agents=["bazi"],
            )
        )
        registry.register(
            AgentSpec(
                agent_id="bazi",
                role="bazi_consultant",
                routing_description="bazi analysis",
            )
        )

        registry.validate_handoff_catalog()

        self.assertEqual(
            registry.routing_catalog("main"),
            {"main": "general", "bazi": "bazi analysis"},
        )

    def test_catalog_rejects_unknown_self_and_undescribed_targets(self) -> None:
        cases = (
            (["missing"], [], "unknown handoff target missing"),
            (["main"], [], "cannot hand off to itself"),
            (["bazi"], [AgentSpec(agent_id="bazi", role="bazi")], "requires routing_description"),
        )
        for targets, extras, message in cases:
            with self.subTest(message=message):
                registry = AgentRegistry()
                registry.register(
                    AgentSpec(
                        agent_id="main",
                        role="general",
                        routing_description="general",
                        allowed_handoff_agents=targets,
                    )
                )
                for item in extras:
                    registry.register(item)
                with self.assertRaisesRegex(ValueError, message):
                    registry.validate_handoff_catalog()


if __name__ == "__main__":
    unittest.main()
