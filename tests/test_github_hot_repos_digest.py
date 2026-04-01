import unittest
from pathlib import Path

from marten_runtime.skills.loader import SkillLoader


class GitHubHotReposDigestSkillTests(unittest.TestCase):
    def test_repo_skill_exists_with_broader_github_mcp_contract(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        loader = SkillLoader([str(repo_root / "skills")])

        skills = loader.load_all(include_bodies=True)
        skill = next(item for item in skills if item.meta.skill_id == "github_hot_repos_digest")

        self.assertEqual(skill.meta.name, "GitHub Assistant")
        self.assertIn("GitHub 热门项目摘要", skill.meta.aliases)
        self.assertIn("GitHub trending", skill.meta.aliases)
        self.assertIn("GitHub MCP", skill.body)
        self.assertIn("search_repositories", skill.body)
        self.assertIn("list_issues", skill.body)
        self.assertIn("create_pull_request", skill.body)
        self.assertIn("Issue / PR work", skill.body)
        self.assertIn("register_automation", skill.body)
        self.assertIn("read before write", skill.body.lower())
        self.assertIn("top 10", skill.body.lower())
        self.assertIn("today", skill.body.lower())
        self.assertIn("recent activity", skill.body.lower())
        self.assertIn("not an official github trending feed", skill.body.lower())

    def test_automation_management_skill_stays_narrow_and_clarifying(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        loader = SkillLoader([str(repo_root / "skills")])

        skills = loader.load_all(include_bodies=True)
        skill = next(item for item in skills if item.meta.skill_id == "automation_management")

        self.assertEqual(skill.meta.name, "Automation Management")
        self.assertIn("自动任务", skill.meta.description)
        self.assertIn("list_automations", skill.body)
        self.assertIn("builtin tools", skill.body.lower())
        self.assertIn("automation_id", skill.body)
        self.assertIn("clarification question", skill.body.lower())
        self.assertIn("do not run the task content", skill.body.lower())


if __name__ == "__main__":
    unittest.main()
