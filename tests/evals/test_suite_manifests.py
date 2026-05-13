import unittest
from pathlib import Path

from marten_runtime.evals.loader import load_suite_spec


class EvalSuiteManifestTests(unittest.TestCase):
    def test_all_declared_suites_load_from_repo(self) -> None:
        suite_paths = [
            Path("evals/suites/main_chain_core.toml"),
            Path("evals/suites/main_chain_mcp.toml"),
            Path("evals/suites/main_chain_subagent.toml"),
            Path("evals/suites/memory_long_horizon.toml"),
            Path("evals/suites/subagent_task_progress.toml"),
            Path("evals/suites/subagent_external_mcp_completion.toml"),
        ]

        suites = [load_suite_spec(path) for path in suite_paths]

        self.assertEqual([suite.suite_id for suite in suites], [
            "main_chain_core",
            "main_chain_mcp",
            "main_chain_subagent",
            "memory_long_horizon",
            "subagent_task_progress",
            "subagent_external_mcp_completion",
        ])

    def test_main_chain_core_manifest_has_15_cases_and_existing_fixtures(self) -> None:
        suite = load_suite_spec(Path("evals/suites/main_chain_core.toml"))

        self.assertEqual(len(suite.cases), 15)
        for case in suite.cases:
            self.assertEqual(case.weights.total(), 100)
            for fixture_path in case.resolved_fixtures.values():
                self.assertTrue(Path(fixture_path).exists(), fixture_path)

    def test_main_chain_mcp_and_subagent_manifests_have_expected_case_counts(self) -> None:
        mcp_suite = load_suite_spec(Path("evals/suites/main_chain_mcp.toml"))
        subagent_suite = load_suite_spec(Path("evals/suites/main_chain_subagent.toml"))

        self.assertEqual(len(mcp_suite.cases), 4)
        self.assertEqual(len(subagent_suite.cases), 3)

    def test_memory_and_subagent_progress_manifests_have_expected_case_counts(self) -> None:
        memory_suite = load_suite_spec(Path("evals/suites/memory_long_horizon.toml"))
        subagent_suite = load_suite_spec(Path("evals/suites/subagent_task_progress.toml"))
        external_mcp_suite = load_suite_spec(Path("evals/suites/subagent_external_mcp_completion.toml"))

        self.assertEqual(len(memory_suite.cases), 7)
        self.assertEqual(len(subagent_suite.cases), 6)
        self.assertEqual(len(external_mcp_suite.cases), 1)
        self.assertEqual(subagent_suite.required_dependencies, ["provider", "subagent"])
        self.assertEqual(external_mcp_suite.required_dependencies, ["provider", "subagent", "mcp"])
        for case in memory_suite.cases:
            self.assertEqual(sum(case.component_weights.values()), 100)
            for fixture_path in case.resolved_fixtures.values():
                self.assertTrue(Path(fixture_path).exists(), fixture_path)
        for case in subagent_suite.cases:
            self.assertEqual(sum(case.component_weights.values()), 100)
            self.assertTrue(case.gate_components)


if __name__ == "__main__":
    unittest.main()
