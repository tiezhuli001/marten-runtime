import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.apps.bootstrap_prompt import load_bootstrap_prompt
from marten_runtime.apps.manifest import load_app_manifest


class BootstrapPromptTests(unittest.TestCase):
    def test_bootstrap_prompt_stays_runtime_focused_and_compact(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        manifest = load_app_manifest(str(repo_root / "apps/example_assistant/app.toml"))

        prompt = load_bootstrap_prompt(repo_root=repo_root, manifest=manifest)

        self.assertIn("不要自称 Cursor、Claude、ChatGPT 或 Codex", prompt)
        self.assertIn("优先调用 `automation`，并使用 `action=register` 完成注册", prompt)
        self.assertIn("不要先展示一次结果再询问是否注册", prompt)
        self.assertIn("优先依赖当前可见 skill 的描述、别名和工具描述", prompt)
        self.assertNotIn("github_trending_digest", prompt)
        self.assertNotIn("general-purpose agent platform", prompt)
        self.assertNotIn("harness-thin, policy-hard, workflow-light", prompt)
        self.assertNotIn("[Mission]", prompt)
        self.assertNotIn("[Product Direction]", prompt)

    def test_bootstrap_prompt_includes_progressive_disclosure_operating_rules(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        manifest = load_app_manifest(str(repo_root / "apps/example_assistant/app.toml"))

        prompt = load_bootstrap_prompt(repo_root=repo_root, manifest=manifest)

        self.assertIn("先阅读当前可见的 skill summaries", prompt)
        self.assertIn("只在某个 skill 明显适用且 summary 不足时，再调用 `skill`", prompt)
        self.assertIn("不要一次加载多个 skill 正文", prompt)
        self.assertIn("只有在 server、tool 或参数仍不明确时", prompt)
        self.assertIn("如果 capability catalog 已经暴露了精确的 server_id、tool_name 和参数形状", prompt)
        self.assertIn("直接使用匹配的 `mcp` 调用", prompt)

    def test_bootstrap_prompt_keeps_mcp_guidance_contract_based_instead_of_github_route(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        manifest = load_app_manifest(str(repo_root / "apps/example_assistant/app.toml"))

        prompt = load_bootstrap_prompt(repo_root=repo_root, manifest=manifest)

        self.assertNotIn("GitHub repo URL", prompt)
        self.assertNotIn("owner/repo", prompt)
        self.assertNotIn("直接 `mcp.call`", prompt)

    def test_bootstrap_prompt_appends_runtime_learned_lessons_when_present(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        manifest = load_app_manifest(str(repo_root / "apps/example_assistant/app.toml"))

        with TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            app_root = temp_root / "apps/example_assistant"
            app_root.mkdir(parents=True)
            for filename in ("BOOTSTRAP.md", "SOUL.md", "AGENTS.md", "TOOLS.md"):
                source = repo_root / "apps/example_assistant" / filename
                (app_root / filename).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            (app_root / "SYSTEM_LESSONS.md").write_text(
                "# Runtime Lessons\n\n- 遇到重复失败时先读取最近失败证据再决定下一步。\n",
                encoding="utf-8",
            )

            prompt = load_bootstrap_prompt(repo_root=temp_root, manifest=manifest)

        self.assertIn("[Runtime Learned Lessons]", prompt)
        self.assertIn("遇到重复失败时先读取最近失败证据再决定下一步。", prompt)

    def test_bootstrap_prompt_ignores_empty_runtime_learned_lessons(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        manifest = load_app_manifest(str(repo_root / "apps/example_assistant/app.toml"))

        with TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            app_root = temp_root / "apps/example_assistant"
            app_root.mkdir(parents=True)
            for filename in ("BOOTSTRAP.md", "SOUL.md", "AGENTS.md", "TOOLS.md"):
                source = repo_root / "apps/example_assistant" / filename
                (app_root / filename).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            (app_root / "SYSTEM_LESSONS.md").write_text("   \n", encoding="utf-8")

            prompt = load_bootstrap_prompt(repo_root=temp_root, manifest=manifest)

        self.assertNotIn("[Runtime Learned Lessons]", prompt)

    def test_bootstrap_prompt_treats_system_lessons_as_active_only_export(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        manifest = load_app_manifest(str(repo_root / "apps/example_assistant/app.toml"))

        with TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            app_root = temp_root / "apps/example_assistant"
            app_root.mkdir(parents=True)
            for filename in ("BOOTSTRAP.md", "SOUL.md", "AGENTS.md", "TOOLS.md"):
                source = repo_root / "apps/example_assistant" / filename
                (app_root / filename).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            (app_root / "SYSTEM_LESSONS.md").write_text(
                (
                    "# Runtime Learned Lessons\n\n"
                    "<!-- active lessons only; superseded/rejected lessons stay in SQLite -->\n\n"
                    "- 遇到相同失败先查 evidence。\n"
                ),
                encoding="utf-8",
            )

            prompt = load_bootstrap_prompt(repo_root=temp_root, manifest=manifest)

        self.assertIn("[Runtime Learned Lessons]", prompt)
        self.assertIn("active lessons only", prompt)
        self.assertIn("遇到相同失败先查 evidence。", prompt)


if __name__ == "__main__":
    unittest.main()
