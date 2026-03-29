import tempfile
import textwrap
import unittest
from pathlib import Path

from marten_runtime.skills.filter import filter_skills
from marten_runtime.skills.loader import SkillLoader
from marten_runtime.skills.render import build_skill_heads, render_always_on_skills
from marten_runtime.skills.selector import select_activated_skills
from marten_runtime.skills.service import SkillService
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.skills.usage import SkillUsage


def write_skill(root: Path, skill_id: str, body: str) -> None:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")


class SkillTests(unittest.TestCase):
    def test_loader_merges_with_system_shared_app_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            system = base / "system"
            shared = base / "shared"
            app = base / "app"
            write_skill(
                system,
                "example_time",
                """
                ---
                skill_id: example_time
                name: Example Time
                description: system version
                enabled: true
                agents: [assistant]
                channels: [http]
                tags: [time]
                ---
                System body
                """,
            )
            write_skill(
                app,
                "example_time",
                """
                ---
                skill_id: example_time
                name: Example Time App
                description: app version
                enabled: true
                agents: [assistant]
                channels: [http]
                tags: [time]
                ---
                App body
                """,
            )
            loader = SkillLoader([str(system), str(shared), str(app)])

            skills = loader.load_all()

            self.assertEqual([skill.meta.skill_id for skill in skills], ["example_time"])
            self.assertEqual(skills[0].meta.description, "app version")
            self.assertEqual(skills[0].meta.source_scope, "app")

    def test_filter_render_and_snapshot_keep_only_visible_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            system = base / "system"
            write_skill(
                system,
                "example_time",
                """
                ---
                skill_id: example_time
                name: Example Time
                description: visible skill
                enabled: true
                always_on: true
                agents: [assistant]
                channels: [http]
                tags: [time]
                ---
                Always on body
                """,
            )
            write_skill(
                system,
                "repo_helper",
                """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: hidden from http
                enabled: true
                agents: [assistant]
                channels: [cli]
                tags: [repo]
                requires_env: [REPO_TOKEN]
                ---
                Helper body
                """,
            )
            loader = SkillLoader([str(system)])
            visible = filter_skills(
                agent_id="assistant",
                channel_id="http",
                items=loader.load_all(),
                env={},
                config={},
            )
            heads = build_skill_heads(visible)
            snapshot = SkillSnapshot.from_skills("skill_snapshot_1", visible)
            usage = SkillUsage(skill_id="example_time", use_count=1, reject_count=0)

            self.assertEqual([item.meta.skill_id for item in visible], ["example_time"])
            self.assertEqual(render_always_on_skills(visible), "Always on body")
            self.assertEqual(heads, [])
            self.assertEqual(snapshot.always_on_ids, ["example_time"])
            self.assertEqual(usage.use_count, 1)

    def test_skill_service_builds_startup_snapshot_and_always_on_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            system = base / "system"
            write_skill(
                system,
                "example_time",
                """
                ---
                skill_id: example_time
                name: Example Time
                description: visible skill
                enabled: true
                always_on: true
                agents: [assistant]
                channels: [http]
                tags: [time]
                ---
                Always on body
                """,
            )
            write_skill(
                system,
                "repo_helper",
                """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: repo assistance
                enabled: true
                agents: [assistant]
                channels: [http]
                tags: [repo]
                ---
                Repo helper body
                """,
            )
            service = SkillService([str(system)])

            runtime = service.build_runtime(agent_id="assistant", channel_id="http", env={}, config={})

            self.assertEqual(runtime.snapshot.always_on_ids, ["example_time"])
            self.assertEqual([head.skill_id for head in runtime.snapshot.heads], ["repo_helper"])
            self.assertEqual(runtime.always_on_text, "Always on body")

    def test_selector_activates_skill_by_id_name_and_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            system = base / "system"
            write_skill(
                system,
                "repo_helper",
                """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: repo assistance
                enabled: true
                agents: [assistant]
                channels: [http]
                tags: [repo, git]
                ---
                Repo helper body
                """,
            )
            loader = SkillLoader([str(system)])
            visible = filter_skills(
                agent_id="assistant",
                channel_id="http",
                items=loader.load_all(),
                env={},
                config={},
            )

            activated = select_activated_skills(visible, "Use repo_helper to inspect the git repo.")

            self.assertEqual([item.meta.skill_id for item in activated], ["repo_helper"])


if __name__ == "__main__":
    unittest.main()
