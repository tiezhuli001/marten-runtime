import unittest

from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.session.store import SessionStore
from marten_runtime.tools.registry import ToolRegistry


class SubagentRuntimeLoopIntegrationTests(unittest.TestCase):
    def _build_service_with_runtime(self):
        from marten_runtime.subagents.service import SubagentService

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        run_history = InMemoryRunHistory()
        runtime_loop = RuntimeLoop(
            ScriptedLLMClient([LLMReply(final_text="child finished")]),
            ToolRegistry(),
            run_history,
        )
        service = SubagentService(
            session_store=session_store,
            run_history=run_history,
            tool_registry=ToolRegistry(),
            runtime_loop=runtime_loop,
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
        )
        return service, runtime_loop, session_store, run_history

    def _build_service_with_mcp_child(self):
        from marten_runtime.subagents.service import SubagentService

        session_store = SessionStore()
        parent = session_store.create(
            session_id="sess_parent_mcp",
            conversation_id="conv-parent-mcp",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        session_store.append_message(
            parent.session_id,
            SessionMessage.user("parent-only context"),
        )
        run_history = InMemoryRunHistory()
        tool_registry = ToolRegistry()
        tool_registry.register(
            "mcp",
            lambda payload: {
                "ok": True,
                "tool_name": "mcp",
                "result_text": "repo_count=42",
            },
        )
        runtime_loop = RuntimeLoop(
            ScriptedLLMClient(
                [
                    LLMReply(tool_name="mcp", tool_payload={"action": "call"}),
                    LLMReply(final_text="child mcp summary: repo_count=42"),
                ]
            ),
            tool_registry,
            run_history,
        )
        service = SubagentService(
            session_store=session_store,
            run_history=run_history,
            tool_registry=tool_registry,
            runtime_loop=runtime_loop,
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
        )
        return service, runtime_loop, session_store, run_history

    def test_service_executes_child_run_with_subagent_request_kind_and_parent_run_linkage(self) -> None:
        service, runtime_loop, _session_store, run_history = self._build_service_with_runtime()
        accepted = service.spawn(
            task="inspect repo in background",
            label="inspect",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            context_mode="brief_only",
            notify_on_finish=True,
        )

        execute_next = getattr(service, "run_next_queued_task", None)
        if execute_next is None:
            self.fail("SubagentService.run_next_queued_task is missing")

        execute_next()

        task = service.store.get(accepted["task_id"])
        self.assertEqual(task.status, "succeeded")
        self.assertIsNotNone(task.child_run_id)
        child_run = run_history.get(task.child_run_id)
        self.assertEqual(child_run.parent_run_id, "run_parent")
        child_session = _session_store.get(task.child_session_id)
        self.assertEqual(child_session.last_run_id, task.child_run_id)
        self.assertEqual(runtime_loop.llm.requests[-1].request_kind, "subagent")
        self.assertEqual(runtime_loop.llm.requests[-1].message, "inspect repo in background")

    def test_parent_session_receives_only_terminal_system_summary(self) -> None:
        service, _runtime_loop, session_store, _run_history = self._build_service_with_runtime()
        accepted = service.spawn(
            task="inspect repo in background",
            label="inspect",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            context_mode="brief_only",
            notify_on_finish=True,
        )

        service.run_next_queued_task()

        parent = session_store.get("sess_parent")
        self.assertEqual(parent.history[-1].role, "system")
        self.assertIn("subagent task completed", parent.history[-1].content)
        self.assertNotIn("tool_name", parent.history[-1].content)
        self.assertNotIn("tool_result", parent.history[-1].content)
        task = service.store.get(accepted["task_id"])
        child = session_store.get(task.child_session_id)
        self.assertTrue(all(item.role != "assistant" for item in parent.history[1:-1]))
        self.assertGreaterEqual(len(child.history), 1)

    def test_brief_plus_snapshot_includes_compacted_context_without_forking_parent_history(self) -> None:
        service, runtime_loop, session_store, _run_history = self._build_service_with_runtime()
        session_store.set_compacted_context(
            "sess_parent",
            CompactedContext(
                compact_id="cmp_parent",
                session_id="sess_parent",
                summary_text="Parent compact summary.",
                source_message_range=[0, 1],
            ),
        )
        accepted = service.spawn(
            task="inspect repo in background",
            label="inspect-snapshot",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            context_mode="brief_plus_snapshot",
            notify_on_finish=True,
        )

        service.run_next_queued_task()

        request = runtime_loop.llm.requests[-1]
        self.assertEqual(request.request_kind, "subagent")
        self.assertIn("Parent compact summary.", request.compact_summary_text or "")
        task = service.store.get(accepted["task_id"])
        child = session_store.get(task.child_session_id)
        self.assertEqual(child.parent_session_id, "sess_parent")
        self.assertEqual([item.role for item in child.history], ["system"])

    def test_child_can_call_mcp_with_standard_profile_without_polluting_parent_history(self) -> None:
        service, runtime_loop, session_store, run_history = self._build_service_with_mcp_child()
        accepted = service.spawn(
            task="use mcp in background",
            label="inspect-mcp",
            parent_session_id="sess_parent_mcp",
            parent_run_id="run_parent_mcp",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="standard",
            parent_allowed_tools=["automation", "mcp", "runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        service.run_next_queued_task()

        task = service.store.get(accepted["task_id"])
        self.assertEqual(task.status, "succeeded")
        child_run = run_history.get(task.child_run_id)
        self.assertEqual(child_run.parent_run_id, "run_parent_mcp")
        self.assertEqual(child_run.tool_calls[0]["tool_name"], "mcp")
        self.assertEqual(runtime_loop.llm.requests[-1].tool_result["tool_name"], "mcp")
        parent = session_store.get("sess_parent_mcp")
        self.assertEqual(parent.history[-1].role, "system")
        self.assertNotIn("tool_name", parent.history[-1].content)
        self.assertNotIn("result_text", parent.history[-1].content)
        self.assertTrue(all(item.role != "assistant" for item in parent.history[1:-1]))
        child = session_store.get(task.child_session_id)
        self.assertEqual(child.last_run_id, task.child_run_id)

    def test_hidden_review_child_does_not_append_parent_terminal_summary(self) -> None:
        service, _runtime_loop, session_store, _run_history = self._build_service_with_runtime()
        accepted = service.spawn(
            task="return review json",
            label="self-improve-review:trigger_1",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            context_mode="brief_only",
            notify_on_finish=False,
            include_parent_session_message=False,
        )

        service.run_next_queued_task()

        parent = session_store.get("sess_parent")
        task = service.store.get(accepted["task_id"])
        self.assertEqual(task.status, "succeeded")
        self.assertEqual([item.role for item in parent.history], ["system"])
        self.assertEqual(parent.history[0].content, "created")


if __name__ == "__main__":
    unittest.main()
