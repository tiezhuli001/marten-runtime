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
            Path("evals/suites/challenge_memory.toml"),
            Path("evals/suites/challenge_mcp.toml"),
            Path("evals/suites/challenge_subagent.toml"),
            Path("evals/suites/challenge_integrated.toml"),
        ]

        suites = [load_suite_spec(path) for path in suite_paths]

        self.assertEqual([suite.suite_id for suite in suites], [
            "main_chain_core",
            "main_chain_mcp",
            "main_chain_subagent",
            "memory_long_horizon",
            "subagent_task_progress",
            "subagent_external_mcp_completion",
            "challenge_memory",
            "challenge_mcp",
            "challenge_subagent",
            "challenge_integrated",
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

    def test_challenge_suite_manifests_have_expected_modes_and_dependencies(self) -> None:
        memory = load_suite_spec(Path("evals/suites/challenge_memory.toml"))
        mcp = load_suite_spec(Path("evals/suites/challenge_mcp.toml"))
        subagent = load_suite_spec(Path("evals/suites/challenge_subagent.toml"))
        integrated = load_suite_spec(Path("evals/suites/challenge_integrated.toml"))

        self.assertEqual(memory.grader_id, "challenge")
        self.assertEqual(memory.default_mode, "scripted")
        self.assertTrue(memory.scripted_supported)
        self.assertEqual(memory.required_dependencies, [])
        self.assertEqual(mcp.default_mode, "live")
        self.assertFalse(mcp.scripted_supported)
        self.assertEqual(mcp.required_dependencies, ["provider", "mcp"])
        self.assertEqual(subagent.default_mode, "scripted")
        self.assertTrue(subagent.scripted_supported)
        self.assertEqual(subagent.required_dependencies, ["subagent"])
        self.assertEqual(integrated.default_mode, "live")
        self.assertFalse(integrated.scripted_supported)
        self.assertEqual(integrated.required_dependencies, ["provider", "mcp", "subagent"])

    def test_challenge_memory_manifest_has_expected_cases(self) -> None:
        suite = load_suite_spec(Path("evals/suites/challenge_memory.toml"))

        self.assertEqual(len(suite.cases), 4)
        self.assertEqual([case.case_id for case in suite.cases], [
            "memory_interference_recall_cn",
            "memory_scope_isolation_cn",
            "memory_overwrite_conflict_cn",
            "memory_should_not_write_cn",
        ])
        for case in suite.cases:
            self.assertEqual(case.grader_id, "challenge")
            self.assertEqual(sum(case.component_weights.values()), 100)
            self.assertTrue(case.gate_components)

    def test_challenge_mcp_manifest_has_expected_cases(self) -> None:
        suite = load_suite_spec(Path("evals/suites/challenge_mcp.toml"))

        self.assertEqual(len(suite.cases), 3)
        self.assertEqual([case.case_id for case in suite.cases], [
            "mcp_multi_source_repo_evidence_cn",
            "mcp_empty_result_recovery_cn",
            "mcp_tool_result_attribution_cn",
        ])
        for case in suite.cases:
            self.assertEqual(case.grader_id, "challenge")
            self.assertEqual(sum(case.component_weights.values()), 100)
            self.assertTrue(case.gate_components)

    def test_challenge_subagent_manifest_has_expected_cases(self) -> None:
        suite = load_suite_spec(Path("evals/suites/challenge_subagent.toml"))

        self.assertEqual(len(suite.cases), 3)
        self.assertEqual([case.case_id for case in suite.cases], [
            "subagent_delegation_boundary_cn",
            "subagent_no_duplicate_dispatch_cn",
            "subagent_incomplete_child_handling_cn",
        ])
        for case in suite.cases:
            self.assertEqual(case.grader_id, "challenge")
            self.assertEqual(sum(case.component_weights.values()), 100)
            self.assertTrue(case.gate_components)

    def test_challenge_integrated_manifest_has_expected_cases(self) -> None:
        suite = load_suite_spec(Path("evals/suites/challenge_integrated.toml"))

        self.assertEqual(len(suite.cases), 4)
        self.assertEqual([case.case_id for case in suite.cases], [
            "integrated_memory_mcp_conflict_resolution_cn",
            "integrated_subagent_mcp_evidence_boundary_cn",
            "skill_required_multistep_apply_cn",
            "skill_unneeded_complex_direct_cn",
        ])
        for case in suite.cases:
            self.assertEqual(case.grader_id, "challenge")
            self.assertEqual(sum(case.component_weights.values()), 100)
            self.assertTrue(case.gate_components)

    def test_challenge_hard_cases_have_rubric_items(self) -> None:
        for suite_path in [
            Path("evals/suites/challenge_memory.toml"),
            Path("evals/suites/challenge_mcp.toml"),
            Path("evals/suites/challenge_subagent.toml"),
            Path("evals/suites/challenge_integrated.toml"),
        ]:
            suite = load_suite_spec(suite_path)
            for case in suite.cases:
                rubric_components = [
                    key
                    for key, value in (case.grader_case or {}).items()
                    if isinstance(value, dict) and value.get("rubric_items")
                ]
                self.assertTrue(rubric_components, f"{case.case_id} lacks rubric_items")

    def test_challenge_mcp_cases_are_live_hard_cases(self) -> None:
        suite = load_suite_spec(Path("evals/suites/challenge_mcp.toml"))

        self.assertFalse(suite.scripted_supported)
        self.assertEqual(suite.required_dependencies, ["provider", "mcp"])
        for case in suite.cases:
            tool_rules = case.grader_case.get("tool_path_quality") or {}
            self.assertIn("mcp", tool_rules.get("required_tools") or [])
            rubric = tool_rules.get("rubric_items") or []
            mcp_items = [item for item in rubric if "mcp" in (item.get("required_tools") or [])]
            self.assertGreaterEqual(len(mcp_items), 1, case.case_id)


if __name__ == "__main__":
    unittest.main()
