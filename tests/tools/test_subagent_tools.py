import unittest

from marten_runtime.session.models import SessionMessage
from tests.http_app_support import build_test_app


class SubagentBuiltinToolTests(unittest.TestCase):
    def test_runtime_bootstrap_registers_subagent_tools(self) -> None:
        app = build_test_app()

        self.assertIn("spawn_subagent", app.state.runtime.tool_registry.list())
        self.assertIn("cancel_subagent", app.state.runtime.tool_registry.list())

    def test_spawn_subagent_tool_uses_tool_context_and_returns_acceptance_payload(self) -> None:
        app = build_test_app()
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

    def test_spawn_subagent_tool_respects_parent_allowed_tools_ceiling(self) -> None:
        app = build_test_app()
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
        task = runtime.subagent_service.store.get(result["task_id"])
        self.assertEqual(task.effective_tool_profile, "restricted")

    def test_spawn_subagent_tool_infers_standard_profile_from_explicit_user_subagent_intent(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool_intent",
            conversation_id="conv-parent-tool-intent",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        runtime.session_store.append_message(
            session.session_id,
            SessionMessage.user("请开启子代理在后台处理这个任务"),
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool_intent",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )

        result = runtime.tool_registry.call(
            "spawn_subagent",
            {
                "task": "处理一个需要后台执行的检查任务",
                "label": "background-check",
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
        task = runtime.subagent_service.store.get(result["task_id"])
        self.assertEqual(task.tool_profile, "standard")
        self.assertEqual(task.effective_tool_profile, "standard")

    def test_spawn_subagent_tool_promotes_explicit_restricted_to_standard_for_broader_tool_task(self) -> None:
        app = build_test_app()
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
        self.assertEqual(result["effective_tool_profile"], "standard")
        task = runtime.subagent_service.store.get(result["task_id"])
        self.assertEqual(task.tool_profile, "standard")
        self.assertEqual(task.effective_tool_profile, "standard")

    def test_spawn_subagent_tool_falls_back_to_parent_agent_when_payload_agent_id_is_unknown(self) -> None:
        app = build_test_app()
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

    def test_spawn_subagent_tool_normalizes_mcp_prefixed_profile_to_standard(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        session = runtime.session_store.create(
            session_id="sess_parent_tool_prefixed_profile",
            conversation_id="conv-parent-tool-prefixed-profile",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )
        parent_run = runtime.run_history.start(
            session_id=session.session_id,
            trace_id="trace_parent_tool_prefixed_profile",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        )

        result = runtime.tool_registry.call(
            "spawn_subagent",
            {
                "task": "查询 codex-skills 最近一次提交",
                "label": "github-last-commit-prefixed-profile",
                "tool_profile": "mcp:github-or-web",
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
        task = runtime.subagent_service.store.get(result["task_id"])
        self.assertEqual(task.tool_profile, "standard")
        self.assertEqual(task.effective_tool_profile, "standard")

    def test_spawn_subagent_tool_keeps_restricted_default_without_explicit_intent_or_broader_hints(self) -> None:
        app = build_test_app()
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
        self.assertEqual(result["effective_tool_profile"], "restricted")
        task = runtime.subagent_service.store.get(result["task_id"])
        self.assertEqual(task.tool_profile, "restricted")
        self.assertEqual(task.effective_tool_profile, "restricted")

    def test_cancel_subagent_tool_reports_existing_terminal_status(self) -> None:
        app = build_test_app()
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
        app = build_test_app()
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
        app = build_test_app()
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
