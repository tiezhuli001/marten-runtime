from __future__ import annotations

import unittest
from unittest.mock import Mock

from marten_runtime.interfaces.http.bootstrap_runtime import (
    build_http_runtime,
    resolve_repo_root,
)
from marten_runtime.interfaces.http.runtime_diagnostics import serialize_runtime_diagnostics
from marten_runtime.runtime.capabilities import (
    get_capability_declarations,
    render_capability_catalog_for_request,
)


class BaziRuntimeRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = build_http_runtime(
            env={"OPENAI_API_KEY": "test", "MINIMAX_API_KEY": "test"},
            load_env_file=False,
        )

    def tearDown(self) -> None:
        self.runtime.compaction_worker.stop()
        self.runtime.subagent_service.shutdown()

    def test_runtime_registers_bazi_with_the_capability_schema(self) -> None:
        self.assertIn("bazi", self.runtime.tool_registry.list())
        descriptor = self.runtime.tool_registry._descriptors["bazi"]
        self.assertEqual(
            descriptor.parameters_schema,
            get_capability_declarations()["bazi"].parameters_schema,
        )
        self.assertEqual(descriptor.observation_policy, "sensitive_bazi")

    def test_relative_repo_root_resolves_to_absolute_path(self) -> None:
        self.assertEqual(resolve_repo_root("."), resolve_repo_root())
        self.assertTrue(resolve_repo_root(".").is_absolute())

    def test_existing_agents_do_not_receive_bazi_in_their_tool_snapshot(self) -> None:
        for agent_id in self.runtime.agent_runtimes:
            if agent_id == "bazi":
                continue
            agent = self.runtime.agent_registry.get(agent_id)
            snapshot = self.runtime.tool_registry.build_snapshot(agent.allowed_tools)
            self.assertNotIn("bazi", snapshot.available_tools())
            catalog = render_capability_catalog_for_request(
                get_capability_declarations(), available_tools=agent.allowed_tools
            )
            self.assertNotIn("- bazi:", catalog)

    def test_clock_chart_runs_through_registered_handler(self) -> None:
        result = self.runtime.tool_registry.call(
            "bazi",
            {
                "action": "chart",
                "gender": "male",
                "birthYear": 1988,
                "birthMonth": 2,
                "birthDay": 15,
                "birthHour": 23,
                "birthMinute": 30,
            },
            tool_context={"turn_tool_state": {}},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["resultSchemaVersion"], "bazi.chart.v1")
        self.assertEqual(result["engine"]["patchId"], "sect1-v1")

    def test_diagnostics_are_secret_free_and_report_bazi_readiness(self) -> None:
        diagnostics = self.runtime.bazi_bridge_manager.diagnostics_summary()

        self.assertTrue(diagnostics["bridge"]["configured"])
        self.assertEqual(diagnostics["bridge"]["protocol_version"], "1")
        self.assertEqual(diagnostics["bridge"]["max_stdout_bytes"], 1_048_576)
        self.assertFalse(diagnostics["place_resolution"]["configured"])
        self.assertEqual(diagnostics["place_resolution"]["reason"], "credential_missing")
        self.assertNotIn("test", str(diagnostics))

        request = Mock()
        request.base_url = "http://127.0.0.1:8000/"
        body = serialize_runtime_diagnostics(self.runtime, request)
        self.assertEqual(body["bazi"], diagnostics)


if __name__ == "__main__":
    unittest.main()
