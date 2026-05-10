import json
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from marten_runtime.evals.loader import load_suite_spec


class RunEvalScriptTests(unittest.TestCase):
    def test_run_eval_list_suites(self) -> None:
        result = subprocess.run(
            [
                ".venv/bin/python",
                "scripts/run_eval.py",
                "--list-suites",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("main_chain_core", result.stdout)
        self.assertIn("memory_long_horizon", result.stdout)
        self.assertIn("subagent_task_progress", result.stdout)

    def test_run_eval_scripted_core_supports_latest_passed_compare(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "evals.sqlite3"
            report_root = Path(tmpdir) / "reports"
            first = subprocess.run(
                [
                    ".venv/bin/python",
                    "scripts/run_eval.py",
                    "--suite",
                    "main_chain_core",
                    "--mode",
                    "scripted",
                    "--profile",
                    "openai_gpt_5_4",
                    "--db-path",
                    str(db_path),
                    "--report-root",
                    str(report_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            second = subprocess.run(
                [
                    ".venv/bin/python",
                    "scripts/run_eval.py",
                    "--suite",
                    "main_chain_core",
                    "--mode",
                    "scripted",
                    "--profile",
                    "openai_gpt_5_4",
                    "--baseline",
                    "latest_passed",
                    "--db-path",
                    str(db_path),
                    "--report-root",
                    str(report_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            latest_report = sorted(report_root.iterdir())[-1]
            summary = json.loads((latest_report / "summary.json").read_text(encoding="utf-8"))
            self.assertIn("compare_result", summary)
            self.assertEqual(summary["compare_result"]["baseline_source"], "latest_passed")
            self.assertEqual(summary["stability_result"]["sample_size"], 2)
            self.assertIn("## Baseline Compare", (latest_report / "summary.md").read_text(encoding="utf-8"))

    def test_run_eval_live_mcp_suite_returns_blocked_when_mcp_dependency_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            self._copy_eval_repo(repo_root)
            mcps_json = repo_root / "mcps.json"
            mcps_example = repo_root / "mcps.example.json"
            if mcps_json.exists():
                mcps_json.unlink()
            if mcps_example.exists():
                mcps_example.unlink()
            report_root = Path(tmpdir) / "reports"
            db_path = Path(tmpdir) / "evals.sqlite3"
            env = dict(**__import__('os').environ)
            env["MARTEN_EVAL_REPO_ROOT"] = str(repo_root)
            env["OPENAI_API_KEY"] = "test-key"
            result = subprocess.run(
                [
                    ".venv/bin/python",
                    "scripts/run_eval.py",
                    "--suite",
                    "main_chain_mcp",
                    "--mode",
                    "live",
                    "--profile",
                    "openai_gpt_5_4",
                    "--db-path",
                    str(db_path),
                    "--report-root",
                    str(report_root),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 2)
            latest_report = sorted(report_root.iterdir())[-1]
            summary = json.loads((latest_report / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "blocked")
            self.assertIn("mcp", json.dumps(summary, ensure_ascii=False))

    def test_run_eval_live_subagent_suite_returns_blocked_when_subagent_surface_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            self._copy_eval_repo(repo_root)
            agents_path = repo_root / "config" / "agents.toml"
            agents_path.write_text(
                agents_path.read_text(encoding="utf-8").replace('"spawn_subagent", ', '').replace(', "cancel_subagent"', ''),
                encoding="utf-8",
            )
            report_root = Path(tmpdir) / "reports"
            db_path = Path(tmpdir) / "evals.sqlite3"
            env = dict(**__import__('os').environ)
            env["MARTEN_EVAL_REPO_ROOT"] = str(repo_root)
            result = subprocess.run(
                [
                    ".venv/bin/python",
                    "scripts/run_eval.py",
                    "--suite",
                    "main_chain_subagent",
                    "--mode",
                    "live",
                    "--profile",
                    "openai_gpt_5_4",
                    "--db-path",
                    str(db_path),
                    "--report-root",
                    str(report_root),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 2)
            latest_report = sorted(report_root.iterdir())[-1]
            summary = json.loads((latest_report / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "blocked")
            self.assertIn("subagent", json.dumps(summary, ensure_ascii=False))

    def test_run_eval_live_subagent_progress_suite_returns_blocked_when_mcp_dependency_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            self._copy_eval_repo(repo_root)
            mcps_json = repo_root / "mcps.json"
            mcps_example = repo_root / "mcps.example.json"
            if mcps_json.exists():
                mcps_json.unlink()
            if mcps_example.exists():
                mcps_example.unlink()
            report_root = Path(tmpdir) / "reports"
            db_path = Path(tmpdir) / "evals.sqlite3"
            env = dict(**__import__('os').environ)
            env["MARTEN_EVAL_REPO_ROOT"] = str(repo_root)
            result = subprocess.run(
                [
                    ".venv/bin/python",
                    "scripts/run_eval.py",
                    "--suite",
                    "subagent_task_progress",
                    "--mode",
                    "live",
                    "--profile",
                    "openai_gpt_5_4",
                    "--db-path",
                    str(db_path),
                    "--report-root",
                    str(report_root),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 2)
            latest_report = sorted(report_root.iterdir())[-1]
            summary = json.loads((latest_report / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "blocked")
            self.assertIn("mcp", json.dumps(summary, ensure_ascii=False))

    def test_run_eval_scripted_memory_suite_supports_latest_passed_compare(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "evals.sqlite3"
            report_root = Path(tmpdir) / "reports"
            first = subprocess.run(
                [
                    ".venv/bin/python",
                    "scripts/run_eval.py",
                    "--suite",
                    "memory_long_horizon",
                    "--mode",
                    "scripted",
                    "--profile",
                    "openai_gpt_5_4",
                    "--db-path",
                    str(db_path),
                    "--report-root",
                    str(report_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            second = subprocess.run(
                [
                    ".venv/bin/python",
                    "scripts/run_eval.py",
                    "--suite",
                    "memory_long_horizon",
                    "--mode",
                    "scripted",
                    "--profile",
                    "openai_gpt_5_4",
                    "--baseline",
                    "latest_passed",
                    "--db-path",
                    str(db_path),
                    "--report-root",
                    str(report_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            latest_report = sorted(report_root.iterdir())[-1]
            summary = json.loads((latest_report / "summary.json").read_text(encoding="utf-8"))
            component_summary = list((summary.get("compare_result") or {}).get("component_summary") or [])
            self.assertTrue(any(item.get("key") == "utility_gain" for item in component_summary))

    def test_run_eval_scripted_subagent_suite_supports_latest_passed_compare(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "evals.sqlite3"
            report_root = Path(tmpdir) / "reports"
            first = subprocess.run(
                [
                    ".venv/bin/python",
                    "scripts/run_eval.py",
                    "--suite",
                    "subagent_task_progress",
                    "--mode",
                    "scripted",
                    "--profile",
                    "openai_gpt_5_4",
                    "--db-path",
                    str(db_path),
                    "--report-root",
                    str(report_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            second = subprocess.run(
                [
                    ".venv/bin/python",
                    "scripts/run_eval.py",
                    "--suite",
                    "subagent_task_progress",
                    "--mode",
                    "scripted",
                    "--profile",
                    "openai_gpt_5_4",
                    "--baseline",
                    "latest_passed",
                    "--db-path",
                    str(db_path),
                    "--report-root",
                    str(report_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            latest_report = sorted(report_root.iterdir())[-1]
            summary = json.loads((latest_report / "summary.json").read_text(encoding="utf-8"))
            component_summary = list((summary.get("compare_result") or {}).get("component_summary") or [])
            self.assertTrue(any(item.get("key") == "parent_integration" for item in component_summary))

    def test_run_eval_live_memory_suite_returns_blocked_when_provider_dependency_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            self._copy_eval_repo(repo_root)
            providers_path = repo_root / "config" / "providers.toml"
            providers_path.write_text(
                providers_path.read_text(encoding="utf-8").replace(
                    'api_key_env = "OPENAI_API_KEY"',
                    'api_key_env = "MARTEN_EVAL_MISSING_OPENAI_KEY"',
                ),
                encoding="utf-8",
            )
            report_root = Path(tmpdir) / "reports"
            db_path = Path(tmpdir) / "evals.sqlite3"
            env = dict(**__import__("os").environ)
            env["MARTEN_EVAL_REPO_ROOT"] = str(repo_root)
            env.pop("MARTEN_EVAL_MISSING_OPENAI_KEY", None)
            result = subprocess.run(
                [
                    ".venv/bin/python",
                    "scripts/run_eval.py",
                    "--suite",
                    "memory_long_horizon",
                    "--mode",
                    "live",
                    "--profile",
                    "openai_gpt_5_4",
                    "--db-path",
                    str(db_path),
                    "--report-root",
                    str(report_root),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 2)
            latest_report = sorted(report_root.iterdir())[-1]
            summary = json.loads((latest_report / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "blocked")
            self.assertIn("provider", json.dumps(summary, ensure_ascii=False))
            self.assertEqual(summary["artifact_root"], str(latest_report))

    def test_resolve_suite_dependency_block_loads_repo_env_for_provider_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            self._copy_eval_repo(repo_root)
            providers_path = repo_root / "config" / "providers.toml"
            providers_path.write_text(
                providers_path.read_text(encoding="utf-8").replace(
                    'api_key_env = "OPENAI_API_KEY"',
                    'api_key_env = "MARTEN_EVAL_DOTENV_OPENAI_KEY"',
                ),
                encoding="utf-8",
            )
            (repo_root / ".env").write_text("MARTEN_EVAL_DOTENV_OPENAI_KEY=test-key\n", encoding="utf-8")
            suite = load_suite_spec(repo_root / "evals" / "suites" / "memory_long_horizon.toml")
            module = self._load_run_eval_module()
            env = __import__("os").environ
            old_value = env.pop("MARTEN_EVAL_DOTENV_OPENAI_KEY", None)
            try:
                module.load_repo_env(repo_root)
                blocked = module.resolve_suite_dependency_block(
                    repo_root=repo_root,
                    suite=suite,
                    mode="live",
                    profile_name="openai_gpt_5_4",
                    env=dict(env),
                )
            finally:
                env.pop("MARTEN_EVAL_DOTENV_OPENAI_KEY", None)
                if old_value is not None:
                    env["MARTEN_EVAL_DOTENV_OPENAI_KEY"] = old_value

            self.assertIsNone(blocked)

    def test_run_eval_live_subagent_progress_suite_returns_blocked_when_subagent_surface_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            self._copy_eval_repo(repo_root)
            agents_path = repo_root / "config" / "agents.toml"
            agents_path.write_text(
                agents_path.read_text(encoding="utf-8").replace('"spawn_subagent", ', '').replace(', "cancel_subagent"', ''),
                encoding="utf-8",
            )
            report_root = Path(tmpdir) / "reports"
            db_path = Path(tmpdir) / "evals.sqlite3"
            env = dict(**__import__('os').environ)
            env["MARTEN_EVAL_REPO_ROOT"] = str(repo_root)
            result = subprocess.run(
                [
                    ".venv/bin/python",
                    "scripts/run_eval.py",
                    "--suite",
                    "subagent_task_progress",
                    "--mode",
                    "live",
                    "--profile",
                    "openai_gpt_5_4",
                    "--db-path",
                    str(db_path),
                    "--report-root",
                    str(report_root),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 2)
            latest_report = sorted(report_root.iterdir())[-1]
            summary = json.loads((latest_report / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "blocked")
            self.assertIn("subagent", json.dumps(summary, ensure_ascii=False))

    def _copy_eval_repo(self, target: Path) -> None:
        source = Path.cwd()
        for name in ("config", "apps", "skills", "evals"):
            shutil.copytree(source / name, target / name)
        for name in ("mcps.json", "mcps.example.json"):
            path = source / name
            if path.exists():
                shutil.copy2(path, target / name)
        (target / "data").mkdir(parents=True, exist_ok=True)

    def _load_run_eval_module(self):
        script_path = Path.cwd() / "scripts" / "run_eval.py"
        spec = importlib.util.spec_from_file_location("run_eval_test_module", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
