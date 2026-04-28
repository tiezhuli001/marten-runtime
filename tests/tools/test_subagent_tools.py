import threading
import time
import unittest

from tests.http_app_support import build_test_app


class SubagentBuiltinToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._apps = []
        self._thread_errors: list[BaseException] = []
        self._original_excepthook = threading.excepthook

        def _capture(args):  # noqa: ANN001
            self._thread_errors.append(args.exc_value)
            self._original_excepthook(args)

        threading.excepthook = _capture

    def _build_app(self):
        app = build_test_app()
        self._apps.append(app)
        return app

    def tearDown(self) -> None:
        for app in reversed(self._apps):
            runtime = getattr(app.state, "runtime", None)
            if runtime is not None:
                if getattr(runtime, "compaction_worker", None) is not None:
                    runtime.compaction_worker.stop()
                if getattr(runtime, "subagent_service", None) is not None:
                    runtime.subagent_service.shutdown()
            temp_dir = getattr(app.state, "_temp_dir", None)
            if temp_dir is not None:
                temp_dir.cleanup()
        time.sleep(0.05)
        threading.excepthook = self._original_excepthook
        self.assertEqual(self._thread_errors, [])

    def test_runtime_bootstrap_registers_subagent_tools(self) -> None:
        app = self._build_app()

        self.assertIn("spawn_subagent", app.state.runtime.tool_registry.list())
        self.assertIn("cancel_subagent", app.state.runtime.tool_registry.list())

    def test_spawn_subagent_tool_uses_tool_context_and_returns_acceptance_payload(self) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool",
            conversation_id="conv-parent-tool",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.list_runs()[-1]

        result = runtime.tool_registry.call(
            "spawn_subagent",
            {
                "task": "inspect the repository in background",
                "label": "repo-inspect",
            },
            tool_context={
                "session_id": session.session_id,
                "run_id": parent_run.run_id,
                "agent_id": "main",
                "app_id": "main_agent",
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["effective_tool_profile"], "restricted")
        task = runtime.subagent_service.store.get(result["task_id"])
        self.assertEqual(task.parent_session_id, session.session_id)
        self.assertEqual(task.parent_run_id, parent_run.run_id)
        self.assertIsNone(task.origin_delivery_target)

    def test_spawn_subagent_tool_sets_feishu_delivery_target_only_for_websocket_ingress(
        self,
    ) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool_feishu_target",
            conversation_id="conv-parent-tool-feishu-target",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool_feishu_target",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )

        live_result = runtime.tool_registry.call(
            "spawn_subagent",
            {
                "task": "inspect the repository in background",
                "label": "repo-inspect-live-feishu",
            },
            tool_context={
                "session_id": session.session_id,
                "run_id": parent_run.run_id,
                "agent_id": "main",
                "app_id": "main_agent",
                "channel_id": "feishu",
                "conversation_id": "oc_real_chat",
                "source_transport": "feishu_websocket",
            },
        )
        live_task = runtime.subagent_service.store.get(live_result["task_id"])
        self.assertEqual(live_task.origin_delivery_target, "oc_real_chat")

        simulated_result = runtime.tool_registry.call(
            "spawn_subagent",
            {
                "task": "inspect the repository in background",
                "label": "repo-inspect-sim-feishu",
            },
            tool_context={
                "session_id": session.session_id,
                "run_id": parent_run.run_id,
                "agent_id": "main",
                "app_id": "main_agent",
                "channel_id": "feishu",
                "conversation_id": "feishu-simulated-chat",
                "source_transport": "http_api",
            },
        )
        simulated_task = runtime.subagent_service.store.get(simulated_result["task_id"])
        self.assertIsNone(simulated_task.origin_delivery_target)

    def test_spawn_subagent_tool_respects_parent_allowed_tools_ceiling(self) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool_ceiling",
            conversation_id="conv-parent-tool-ceiling",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool_ceiling",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )

        result = runtime.tool_registry.call(
            "spawn_subagent",
            {
                "task": "inspect the repository in background",
                "label": "repo-inspect-ceiling",
                "tool_profile": "elevated",
            },
            tool_context={
                "session_id": session.session_id,
                "run_id": parent_run.run_id,
                "agent_id": "main",
                "app_id": "main_agent",
                "allowed_tools": ["runtime", "skill", "time"],
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["effective_tool_profile"], "restricted")

    def test_spawn_subagent_tool_rejects_removed_default_tool_profile_alias(
        self,
    ) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool_default_alias",
            conversation_id="conv-parent-tool-default-alias",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool_default_alias",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )

        with self.assertRaisesRegex(ValueError, "unknown tool profile: default"):
            runtime.tool_registry.call(
                "spawn_subagent",
                {
                    "task": "查询 codex-skills 最近一次提交",
                    "label": "github-last-commit-default-alias",
                    "tool_profile": "default",
                },
                tool_context={
                    "session_id": session.session_id,
                    "run_id": parent_run.run_id,
                    "agent_id": "main",
                    "app_id": "main_agent",
                    "allowed_tools": ["automation", "mcp", "runtime", "skill", "time", "spawn_subagent", "cancel_subagent"],
                },
            )

    def test_spawn_subagent_tool_normalizes_placeholder_agent_id(self) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool_placeholders",
            conversation_id="conv-parent-tool-placeholders",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool_placeholders",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )

        result = runtime.tool_registry.call(
            "spawn_subagent",
            {
                "task": "后台整理这段说明",
                "label": "normalize-placeholders",
                "agent_id": "default",
            },
            tool_context={
                "session_id": session.session_id,
                "run_id": parent_run.run_id,
                "agent_id": "main",
                "app_id": "main_agent",
                "allowed_tools": ["automation", "mcp", "runtime", "skill", "time", "spawn_subagent", "cancel_subagent"],
            },
        )

        self.assertTrue(result["ok"])
        task = runtime.subagent_service.store.get(result["task_id"])
        self.assertEqual(task.agent_id, "main")

    def test_spawn_subagent_tool_canonicalizes_legacy_assistant_agent_id(self) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool_assistant_alias",
            conversation_id="conv-parent-tool-assistant-alias",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool_assistant_alias",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )

        result = runtime.tool_registry.call(
            "spawn_subagent",
            {
                "task": "inspect the repository in background",
                "label": "repo-inspect-assistant-alias",
                "agent_id": "assistant",
            },
            tool_context={
                "session_id": session.session_id,
                "run_id": parent_run.run_id,
                "agent_id": "assistant",
                "app_id": "main_agent",
                "allowed_tools": ["automation", "mcp", "runtime", "skill", "time", "spawn_subagent", "cancel_subagent"],
            },
        )

        self.assertTrue(result["ok"])
        task = runtime.subagent_service.store.get(result["task_id"])
        self.assertEqual(task.parent_agent_id, "main")
        self.assertEqual(task.agent_id, "main")
        self.assertEqual(task.context_mode, "brief_only")

    def test_spawn_subagent_tool_rejects_removed_minimal_context_mode_alias(self) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool_removed_minimal",
            conversation_id="conv-parent-tool-removed-minimal",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool_removed_minimal",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )

        with self.assertRaisesRegex(ValueError, "unknown context mode: minimal"):
            runtime.tool_registry.call(
                "spawn_subagent",
                {
                    "task": "后台整理这段说明",
                    "label": "removed-minimal",
                    "context_mode": "minimal",
                },
                tool_context={
                    "session_id": session.session_id,
                    "run_id": parent_run.run_id,
                    "agent_id": "main",
                    "app_id": "main_agent",
                    "allowed_tools": ["automation", "mcp", "runtime", "skill", "time", "spawn_subagent", "cancel_subagent"],
                },
            )

    def test_spawn_subagent_tool_keeps_explicit_restricted_profile_for_broader_tool_task(self) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool_promote",
            conversation_id="conv-parent-tool-promote",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool_promote",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )

        result = runtime.tool_registry.call(
            "spawn_subagent",
            {
                "task": "查询今日 GitHub trending top10 是什么，使用 github_trending MCP 工具获取最新数据",
                "label": "github-trending",
                "tool_profile": "restricted",
            },
            tool_context={
                "session_id": session.session_id,
                "run_id": parent_run.run_id,
                "agent_id": "main",
                "app_id": "main_agent",
                "allowed_tools": ["automation", "mcp", "runtime", "skill", "time", "spawn_subagent", "cancel_subagent"],
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["effective_tool_profile"], "restricted")

    def test_spawn_subagent_tool_falls_back_to_parent_agent_when_payload_agent_id_is_unknown(self) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool_unknown_agent",
            conversation_id="conv-parent-tool-unknown-agent",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool_unknown_agent",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )

        result = runtime.tool_registry.call(
            "spawn_subagent",
            {
                "task": "查询 codex-skills 最近一次提交",
                "label": "github-last-commit",
                "agent_id": "github-subagent",
            },
            tool_context={
                "session_id": session.session_id,
                "run_id": parent_run.run_id,
                "agent_id": "main",
                "app_id": "main_agent",
                "allowed_tools": ["automation", "mcp", "runtime", "skill", "time", "spawn_subagent", "cancel_subagent"],
            },
        )

        self.assertTrue(result["ok"])
        task = runtime.subagent_service.store.get(result["task_id"])
        self.assertEqual(task.agent_id, "main")
        self.assertEqual(task.app_id, "main_agent")

    def test_spawn_subagent_tool_defaults_to_standard_profile_for_simple_background_tasks(self) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool_default",
            conversation_id="conv-parent-tool-default",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool_default",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )

        result = runtime.tool_registry.call(
            "spawn_subagent",
            {
                "task": "整理这段说明并给出一个简短摘要",
                "label": "simple-summary",
            },
            tool_context={
                "session_id": session.session_id,
                "run_id": parent_run.run_id,
                "agent_id": "main",
                "app_id": "main_agent",
                "allowed_tools": ["automation", "mcp", "runtime", "skill", "time", "spawn_subagent", "cancel_subagent"],
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["effective_tool_profile"], "standard")

    def test_cancel_subagent_tool_reports_existing_terminal_status(self) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_cancel_terminal",
            conversation_id="conv-parent-cancel-terminal",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_cancel_terminal",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        accepted = runtime.subagent_service.spawn(
            task="background task",
            label="already-done",
            parent_session_id=session.session_id,
            parent_run_id=parent_run.run_id,
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            context_mode="brief_only",
            notify_on_finish=True,
        )
        runtime.subagent_service.store.mark_succeeded(accepted["task_id"])

        result = runtime.tool_registry.call(
            "cancel_subagent",
            {"task_id": accepted["task_id"]},
            tool_context={"session_id": session.session_id, "run_id": parent_run.run_id},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "succeeded")
        self.assertFalse(result["cancelled"])

    def test_cancel_subagent_tool_cancels_known_task(self) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_cancel",
            conversation_id="conv-parent-cancel",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_cancel",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        accepted = runtime.subagent_service.spawn(
            task="background task",
            label="to-cancel",
            parent_session_id=session.session_id,
            parent_run_id=parent_run.run_id,
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            context_mode="brief_only",
            notify_on_finish=True,
        )

        result = runtime.tool_registry.call(
            "cancel_subagent",
            {"task_id": accepted["task_id"]},
            tool_context={"session_id": session.session_id, "run_id": parent_run.run_id},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(runtime.subagent_service.store.get(accepted["task_id"]).status, "cancelled")

    def test_cancel_subagent_tool_rejects_foreign_task(self) -> None:
        app = self._build_app()
        runtime = app.state.runtime
        owner_session = runtime.session_store.create(
            session_id="sess_parent_cancel_owner",
            conversation_id="conv-parent-cancel-owner",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        foreign_session = runtime.session_store.create(
            session_id="sess_parent_cancel_foreign",
            conversation_id="conv-parent-cancel-foreign",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        owner_run = runtime.run_history.start(
            session_id=owner_session.session_id,
            trace_id="trace_parent_cancel_owner",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        foreign_run = runtime.run_history.start(
            session_id=foreign_session.session_id,
            trace_id="trace_parent_cancel_foreign",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        accepted = runtime.subagent_service.spawn(
            task="background task",
            label="foreign-cancel",
            parent_session_id=owner_session.session_id,
            parent_run_id=owner_run.run_id,
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            context_mode="brief_only",
            notify_on_finish=True,
        )

        with self.assertRaisesRegex(
            ValueError, "subagent task is not owned by current session"
        ):
            runtime.tool_registry.call(
                "cancel_subagent",
                {"task_id": accepted["task_id"]},
                tool_context={
                    "session_id": foreign_session.session_id,
                    "run_id": foreign_run.run_id,
                },
            )


if __name__ == "__main__":
    unittest.main()
