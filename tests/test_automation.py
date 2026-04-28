import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.automation.skill_ids import resolve_automation_runtime_skill_id
from marten_runtime.config.automations_loader import load_automations


class AutomationTests(unittest.TestCase):
    def test_loader_supports_seed_data(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            example = root / "config" / "automations.example.toml"
            example.parent.mkdir(parents=True, exist_ok=True)
            example.write_text(
                """
[[automations]]
automation_id = "daily_hot"
name = "Daily GitHub Hot Repos"
app_id = "main_agent"
agent_id = "main"
prompt_template = "Summarize today's hot repositories."
schedule_kind = "daily"
schedule_expr = "10:00"
timezone = "Asia/Shanghai"
session_target = "isolated"
delivery_channel = "feishu"
delivery_target = "oc_test_chat"
skill_id = "github_trending_digest"
enabled = true
""".strip(),
                encoding="utf-8",
            )

            jobs = load_automations(str(root / "config" / "automations.toml"))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].automation_id, "daily_hot")
        self.assertEqual(jobs[0].schedule_expr, "10:00")
        self.assertEqual(jobs[0].delivery_channel, "feishu")
        self.assertEqual(jobs[0].skill_id, "github_trending_digest")

    def test_resolve_automation_runtime_skill_id_skips_trending_digest_bridge(self) -> None:
        self.assertIsNone(resolve_automation_runtime_skill_id("github_trending_digest"))
        self.assertEqual(resolve_automation_runtime_skill_id("self_improve"), "self_improve")
        self.assertIsNone(resolve_automation_runtime_skill_id("  "))

    def test_loader_canonicalizes_legacy_assistant_agent_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config" / "automations.toml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                """
[[automations]]
automation_id = "daily_hot"
name = "Daily GitHub Hot Repos"
app_id = "main_agent"
agent_id = "assistant"
prompt_template = "Summarize today's hot repositories."
schedule_kind = "daily"
schedule_expr = "10:00"
timezone = "Asia/Shanghai"
session_target = "isolated"
delivery_channel = "feishu"
delivery_target = "oc_test_chat"
skill_id = "github_trending_digest"
enabled = true
""".strip(),
                encoding="utf-8",
            )

            jobs = load_automations(str(config_path))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].agent_id, "main")


if __name__ == "__main__":
    unittest.main()
