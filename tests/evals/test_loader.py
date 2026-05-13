import tempfile
import unittest
from pathlib import Path

from marten_runtime.evals.loader import load_case_spec, load_suite_spec


class EvalLoaderTests(unittest.TestCase):
    def test_load_case_spec_from_repo_file(self) -> None:
        case = load_case_spec(Path("evals/cases/main_chain_core/direct_answer_cn.toml"))

        self.assertEqual(case.case_id, "direct_answer_cn")
        self.assertEqual(case.turns[0].content, "你好")

    def test_load_suite_spec_from_repo_file(self) -> None:
        suite = load_suite_spec(Path("evals/suites/main_chain_core.toml"))

        self.assertEqual(suite.suite_id, "main_chain_core")
        self.assertEqual(len(suite.cases), 15)
        self.assertEqual(suite.required_dependencies, ["provider"])
        self.assertEqual(suite.grader_id, "main_chain_core")
        self.assertTrue(all(case.grader_id == "main_chain_core" for case in suite.cases))
        self.assertTrue(suite.suite_fingerprint)

    def test_load_family_scored_suites_from_repo_files(self) -> None:
        memory_suite = load_suite_spec(Path("evals/suites/memory_long_horizon.toml"))
        subagent_suite = load_suite_spec(Path("evals/suites/subagent_task_progress.toml"))
        external_mcp_suite = load_suite_spec(Path("evals/suites/subagent_external_mcp_completion.toml"))

        self.assertEqual(memory_suite.grader_id, "memory_long_horizon")
        self.assertEqual(subagent_suite.grader_id, "subagent_task_progress")
        self.assertEqual(external_mcp_suite.grader_id, "subagent_task_progress")
        self.assertEqual(len(memory_suite.cases), 7)
        self.assertEqual(len(subagent_suite.cases), 6)
        self.assertEqual(len(external_mcp_suite.cases), 1)
        self.assertTrue(all(case.grader_id == "memory_long_horizon" for case in memory_suite.cases))
        self.assertTrue(all(case.grader_id == "subagent_task_progress" for case in subagent_suite.cases))
        self.assertEqual(memory_suite.cases[0].component_weights["capture"], 70)
        self.assertEqual(subagent_suite.required_dependencies, ["provider", "subagent"])
        self.assertEqual(external_mcp_suite.required_dependencies, ["provider", "subagent", "mcp"])
        self.assertTrue(all(case.gate_components for case in subagent_suite.cases))

    def test_load_suite_spec_rejects_missing_case_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            suite_path = root / "suite.toml"
            suite_path.write_text(
                'suite_id = "suite_1"\n'
                'description = "demo"\n'
                'default_mode = "live"\n'
                'scripted_supported = true\n'
                'required_dependencies = ["provider"]\n'
                'baseline_policy = "latest_passed_auto"\n'
                'case_files = ["missing.toml"]\n',
                encoding="utf-8",
            )

            with self.assertRaises(FileNotFoundError):
                load_suite_spec(suite_path)

    def test_load_suite_spec_rejects_missing_fixture_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "cases").mkdir()
            case_path = root / "cases" / "case.toml"
            case_path.write_text(
                'case_id = "case_1"\n'
                'suite_id = "suite_1"\n'
                'family = "direct_answer"\n'
                'enabled = true\n'
                'required = true\n'
                'description = "demo"\n'
                'agent_id = "main"\n'
                'profile_name = "openai_gpt_5_4"\n'
                'tags = []\n\n'
                '[[turns]]\n'
                'role = "user"\n'
                'content = "hello"\n\n'
                '[setup]\n'
                'session_history_fixture = "missing.md"\n'
                'memory_fixture = "none"\n'
                'automation_fixture = "none"\n\n'
                '[expectations.final_text]\n'
                'contains_any = ["hello"]\n\n'
                '[weights]\n'
                'outcome = 100\n'
                'tool_path = 0\n'
                'efficiency = 0\n'
                'context = 0\n',
                encoding="utf-8",
            )
            suite_path = root / "suite.toml"
            suite_path.write_text(
                'suite_id = "suite_1"\n'
                'description = "demo"\n'
                'default_mode = "live"\n'
                'scripted_supported = true\n'
                'required_dependencies = ["provider"]\n'
                'baseline_policy = "latest_passed_auto"\n'
                f'case_files = ["{case_path.as_posix()}"]\n',
                encoding="utf-8",
            )

            with self.assertRaises(FileNotFoundError):
                load_suite_spec(suite_path)


if __name__ == "__main__":
    unittest.main()
