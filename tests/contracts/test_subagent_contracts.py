import unittest

from fastapi.testclient import TestClient

from tests.http_app_support import build_test_app


class SubagentContractTests(unittest.TestCase):
    def test_subagent_diagnostics_endpoints_expose_task_and_lineage(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_contract_parent",
            conversation_id="conv-contract-parent",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_contract_parent",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        accepted = runtime.subagent_service.spawn(
            task="inspect contract flow",
            label="contract-check",
            parent_session_id=session.session_id,
            parent_run_id=parent_run.run_id,
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            context_mode="brief_only",
            notify_on_finish=True,
        )
        runtime.subagent_service.run_next_queued_task()

        with TestClient(app) as client:
            listing = client.get("/diagnostics/subagents")
            detail = client.get(f"/diagnostics/subagent/{accepted['task_id']}")

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(listing.json()["count"], 1)
        item = detail.json()
        self.assertEqual(item["task_id"], accepted["task_id"])
        self.assertEqual(item["parent_session_id"], session.session_id)
        self.assertEqual(item["parent_run_id"], parent_run.run_id)
        self.assertEqual(item["status"], "succeeded")
        self.assertTrue(item["child_session_id"])
        self.assertTrue(item["child_run_id"])

    def test_parent_session_receives_terminal_system_message_after_subagent_completion(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_contract_parent_2",
            conversation_id="conv-contract-parent-2",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_contract_parent_2",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        accepted = runtime.subagent_service.spawn(
            task="inspect contract flow",
            label="contract-check-2",
            parent_session_id=session.session_id,
            parent_run_id=parent_run.run_id,
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            context_mode="brief_only",
            notify_on_finish=True,
        )
        runtime.subagent_service.run_next_queued_task()
        task = runtime.subagent_service.store.get(accepted["task_id"])

        with TestClient(app) as client:
            parent_session = client.get(f"/diagnostics/session/{session.session_id}")
            child_run = client.get(f"/diagnostics/run/{task.child_run_id}")

        self.assertEqual(parent_session.status_code, 200)
        self.assertEqual(child_run.status_code, 200)
        history = parent_session.json()["history"]
        self.assertEqual(history[-1]["role"], "system")
        self.assertIn("subagent task completed", history[-1]["content"])
        self.assertEqual(child_run.json()["parent_run_id"], parent_run.run_id)


if __name__ == "__main__":
    unittest.main()
