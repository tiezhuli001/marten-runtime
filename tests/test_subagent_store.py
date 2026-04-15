import unittest

from marten_runtime.session.store import SessionStore


class SubagentTaskStoreContractTests(unittest.TestCase):
    def test_subagent_task_model_and_store_contract_is_present(self) -> None:
        try:
            from marten_runtime.subagents.models import SubagentTask
            from marten_runtime.subagents.store import InMemorySubagentStore
        except ModuleNotFoundError as exc:
            self.fail(f"subagent model/store module missing: {exc}")

        store = InMemorySubagentStore()
        self.assertTrue(hasattr(store, "create"))
        self.assertTrue(hasattr(store, "get"))
        self.assertTrue(hasattr(store, "list_tasks"))
        self.assertTrue(hasattr(store, "mark_running"))
        self.assertTrue(hasattr(store, "mark_succeeded"))
        self.assertTrue(hasattr(store, "mark_failed"))
        self.assertTrue(hasattr(store, "mark_cancelled"))
        self.assertTrue(hasattr(store, "mark_timed_out"))
        self.assertTrue(hasattr(store, "attach_child_run"))
        self.assertTrue(hasattr(store, "set_terminal_payload"))

        task = store.create(
            label="background-research",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            child_session_id="sess_child",
            app_id="main_agent",
            agent_id="main",
            tool_profile="restricted",
            effective_tool_profile="restricted",
            context_mode="brief_only",
            task_prompt="research this in background",
            notify_on_finish=True,
        )

        self.assertIsInstance(task, SubagentTask)
        self.assertEqual(task.status, "queued")
        self.assertEqual(task.parent_session_id, "sess_parent")
        self.assertEqual(task.parent_run_id, "run_parent")
        self.assertEqual(task.child_session_id, "sess_child")
        self.assertEqual(task.tool_profile, "restricted")
        self.assertEqual(task.context_mode, "brief_only")
        self.assertIsNone(task.child_run_id)
        self.assertIsNone(task.result_summary)
        self.assertIsNone(task.error_text)

        listed = store.list_tasks()
        self.assertEqual([item.task_id for item in listed], [task.task_id])
        fetched = store.get(task.task_id)
        self.assertEqual(fetched.task_id, task.task_id)

    def test_subagent_store_supports_lifecycle_transitions_and_terminal_payloads(self) -> None:
        try:
            from marten_runtime.subagents.store import InMemorySubagentStore
        except ModuleNotFoundError as exc:
            self.fail(f"subagent store module missing: {exc}")

        store = InMemorySubagentStore()
        task = store.create(
            label="bg-task",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            child_session_id="sess_child",
            app_id="main_agent",
            agent_id="main",
            tool_profile="restricted",
            effective_tool_profile="restricted",
            context_mode="brief_only",
            task_prompt="do work",
            notify_on_finish=True,
        )

        running = store.mark_running(task.task_id)
        self.assertEqual(running.status, "running")
        self.assertIsNotNone(running.started_at)

        attached = store.attach_child_run(task.task_id, "run_child")
        self.assertEqual(attached.child_run_id, "run_child")

        succeeded = store.mark_succeeded(task.task_id)
        succeeded = store.set_terminal_payload(
            task.task_id,
            result_summary="done in background",
        )
        self.assertEqual(succeeded.status, "succeeded")
        self.assertEqual(succeeded.result_summary, "done in background")
        self.assertIsNotNone(succeeded.finished_at)

        failed_task = store.create(
            label="bg-task-fail",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            child_session_id="sess_child_2",
            app_id="main_agent",
            agent_id="main",
            tool_profile="restricted",
            effective_tool_profile="restricted",
            context_mode="brief_only",
            task_prompt="do work",
            notify_on_finish=True,
        )
        store.mark_running(failed_task.task_id)
        failed = store.mark_failed(failed_task.task_id)
        failed = store.set_terminal_payload(
            failed_task.task_id,
            error_text="provider failed",
        )
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error_text, "provider failed")

        cancelled_task = store.create(
            label="bg-task-cancel",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            child_session_id="sess_child_3",
            app_id="main_agent",
            agent_id="main",
            tool_profile="restricted",
            effective_tool_profile="restricted",
            context_mode="brief_only",
            task_prompt="do work",
            notify_on_finish=True,
        )
        cancelled = store.mark_cancelled(cancelled_task.task_id)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertIsNotNone(cancelled.finished_at)

        timed_out_task = store.create(
            label="bg-task-timeout",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            child_session_id="sess_child_4",
            app_id="main_agent",
            agent_id="main",
            tool_profile="restricted",
            effective_tool_profile="restricted",
            context_mode="brief_only",
            task_prompt="do work",
            notify_on_finish=True,
        )
        timed_out = store.mark_timed_out(timed_out_task.task_id)
        self.assertEqual(timed_out.status, "timed_out")
        self.assertIsNotNone(timed_out.finished_at)


class SessionStoreSubagentChildContractTests(unittest.TestCase):
    def test_session_store_creates_child_subagent_session_with_lineage(self) -> None:
        store = SessionStore()
        parent = store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )

        create_child = getattr(store, "create_child_session", None)
        if create_child is None:
            self.fail("SessionStore.create_child_session is missing")

        child = create_child(
            parent_session_id=parent.session_id,
            conversation_id="subagent:task_1",
            session_id="sess_child",
        )

        self.assertEqual(child.parent_session_id, parent.session_id)
        self.assertEqual(child.session_kind, "subagent")
        self.assertEqual(child.lineage_depth, parent.lineage_depth + 1)
        self.assertEqual(child.conversation_id, "subagent:task_1")
        self.assertEqual(child.session_id, "sess_child")


if __name__ == "__main__":
    unittest.main()
