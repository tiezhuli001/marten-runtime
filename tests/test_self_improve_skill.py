import tempfile
import unittest
from pathlib import Path

from marten_runtime.skills.filter import filter_skills
from marten_runtime.skills.loader import SkillLoader
from marten_runtime.skills.selector import select_activated_skills
from tests.support.skill_builders import write_skill


class SelfImproveSkillTests(unittest.TestCase):
    def test_selector_explicitly_activates_self_improve_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shared = base / "skills"
            write_skill(
                shared,
                "self_improve",
                """
                ---
                skill_id: self_improve
                name: Self Improve
                description: synthesize lesson candidates from repeated failures and later recoveries
                enabled: true
                agents: [main]
                channels: [http, feishu]
                tags: [self_improve, lessons, diagnostics]
                ---
                Body
                """,
            )
            loader = SkillLoader([str(shared)])
            visible = filter_skills(
                agent_id="main",
                channel_id="http",
                items=loader.load_all(),
                env={},
                config={},
            )

            activated = select_activated_skills(
                visible,
                "Run the self improve summarizer.",
                explicit_skill_ids=["self_improve"],
            )

        self.assertEqual([item.meta.skill_id for item in activated], ["self_improve"])

    def test_selector_does_not_activate_self_improve_for_normal_user_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shared = base / "skills"
            write_skill(
                shared,
                "self_improve",
                """
                ---
                skill_id: self_improve
                name: Self Improve
                description: synthesize lesson candidates from repeated failures and later recoveries
                enabled: true
                agents: [main]
                channels: [http, feishu]
                tags: [self_improve, lessons, diagnostics]
                ---
                Body
                """,
            )
            loader = SkillLoader([str(shared)])
            visible = filter_skills(
                agent_id="main",
                channel_id="http",
                items=loader.load_all(),
                env={},
                config={},
            )

            activated = select_activated_skills(
                visible,
                "帮我总结一下今天的 GitHub 热门项目。",
            )

        self.assertEqual(activated, [])


if __name__ == "__main__":
    unittest.main()
