import tempfile
import textwrap
import unittest
from pathlib import Path

from marten_runtime.agents.defaults import DEFAULT_AGENT_ASSET_ROOT
from marten_runtime.config.agents_loader import load_agent_specs


class AgentSpecLoadingTests(unittest.TestCase):
    def test_loader_reads_multiple_agents_with_explicit_fields_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agents.toml"
            path.write_text(
                textwrap.dedent(
                    """
                    [agents.main]
                    role = "general_assistant"
                    app_id = "legacy_app"
                    asset_root = "agents/main"
                    allowed_tools = ["time", "skill"]
                    routing_description = "general requests"
                    allowed_handoff_agents = ["bazi"]
                    allowed_knowledge_namespaces = ["personal", "docs"]
                    allowed_knowledge_actions = ["search", "get_chunk"]
                    observation_policy = "sensitive_bazi"
                    prompt_mode = "full"
                    model_profile = "fast"

                    [agents.ops]
                    role = "ops_agent"
                    enabled = false
                    allowed_tools = ["time"]
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            specs = load_agent_specs(str(path))

            self.assertEqual([item.agent_id for item in specs], ["main", "ops"])
            self.assertEqual(specs[0].allowed_tools, ["time", "skill"])
            self.assertEqual(specs[0].routing_description, "general requests")
            self.assertEqual(specs[0].allowed_handoff_agents, ["bazi"])
            self.assertEqual(specs[0].model_profile, "fast")
            self.assertEqual(specs[0].allowed_knowledge_namespaces, ["personal", "docs"])
            self.assertEqual(specs[0].allowed_knowledge_actions, ["search", "get_chunk"])
            self.assertEqual(specs[0].observation_policy, "sensitive_bazi")
            self.assertEqual(specs[1].role, "ops_agent")
            self.assertFalse(specs[1].enabled)
            self.assertEqual(specs[0].asset_root, "agents/main")
            self.assertFalse(hasattr(specs[0], "app_id"))
            self.assertEqual(specs[1].prompt_mode, "full")
            self.assertIsNone(specs[1].model_profile)
            self.assertIsNone(specs[1].allowed_knowledge_namespaces)
            self.assertIsNone(specs[1].allowed_knowledge_actions)
            self.assertEqual(specs[1].routing_description, "")
            self.assertEqual(specs[1].allowed_handoff_agents, [])

    def test_loader_uses_current_default_agent_asset_root_for_missing_asset_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agents.toml"
            path.write_text(
                textwrap.dedent(
                    """
                    [agents.main]
                    role = "general_assistant"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            specs = load_agent_specs(str(path))

            self.assertEqual(specs[0].asset_root, DEFAULT_AGENT_ASSET_ROOT)

    def test_loader_rejects_agent_missing_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agents.toml"
            path.write_text(
                textwrap.dedent(
                    """
                    [agents.main]
                    allowed_tools = ["time"]
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(Exception):
                load_agent_specs(str(path))

    def test_loader_rejects_invalid_knowledge_scope_and_policy(self) -> None:
        invalid_fields = (
            'allowed_handoff_agents = [""]',
            'allowed_knowledge_namespaces = [""]',
            'allowed_knowledge_actions = ["unknown"]',
            'observation_policy = "unknown"',
        )
        for field in invalid_fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "agents.toml"
                path.write_text(
                    textwrap.dedent(
                        f"""
                        [agents.main]
                        role = "general_assistant"
                        allowed_tools = ["knowledge"]
                        {field}
                        """
                    ).strip()
                    + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(Exception):
                    load_agent_specs(str(path))


if __name__ == "__main__":
    unittest.main()
