import tempfile
import textwrap
import unittest
from pathlib import Path

from marten_runtime.apps.runtime_defaults import DEFAULT_APP_ID
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
                    app_id = "main_agent"
                    allowed_tools = ["time", "skill"]
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
            self.assertEqual(specs[0].model_profile, "fast")
            self.assertEqual(specs[1].role, "ops_agent")
            self.assertFalse(specs[1].enabled)
            self.assertEqual(specs[1].app_id, "main_agent")
            self.assertEqual(specs[1].prompt_mode, "full")
            self.assertIsNone(specs[1].model_profile)

    def test_loader_uses_current_default_runtime_asset_for_missing_app_id(self) -> None:
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

            self.assertEqual(specs[0].app_id, DEFAULT_APP_ID)

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


if __name__ == "__main__":
    unittest.main()
