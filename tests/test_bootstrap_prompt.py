import unittest
from pathlib import Path

from marten_runtime.apps.bootstrap_prompt import load_bootstrap_prompt
from marten_runtime.apps.manifest import load_app_manifest


class BootstrapPromptTests(unittest.TestCase):
    def test_bootstrap_prompt_includes_product_mission_and_runtime_shape(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        manifest = load_app_manifest(str(repo_root / "apps/example_assistant/app.toml"))

        prompt = load_bootstrap_prompt(repo_root=repo_root, manifest=manifest)

        self.assertIn("general-purpose agent platform", prompt)
        self.assertIn("LLM + agent loop + MCP + skills", prompt)
        self.assertIn("harness-thin, policy-hard, workflow-light", prompt)
        self.assertIn("不要自称 Cursor、Claude、ChatGPT 或 Codex", prompt)
        self.assertIn("优先调用 `register_automation` 完成注册", prompt)
        self.assertIn("不要先展示一次结果再询问是否注册", prompt)
        self.assertIn("优先依赖当前可见 skill 的描述、别名和工具描述", prompt)
        self.assertNotIn("github_hot_repos_digest", prompt)


if __name__ == "__main__":
    unittest.main()
