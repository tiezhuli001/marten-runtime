import unittest
from datetime import datetime, timezone
from threading import Event, Thread
from types import SimpleNamespace

from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.store import SessionStore
from marten_runtime.tools.registry import ToolRegistry
from tests.support.feishu_builders import FakeDeliveryClient


class SubagentServiceContractTests(unittest.TestCase):
    def _build_service(self):
        try:
            from marten_runtime.subagents.store import InMemorySubagentStore
            from marten_runtime.subagents.service import SubagentService
        except ModuleNotFoundError as exc:
            self.fail(f"subagent service/store module missing: {exc}")

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        return SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=None,
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
        )

    def test_spawn_reserves_slot_before_background_thread_starts(self) -> None:
        from marten_runtime.runtime.events import OutboundEvent
        from marten_runtime.subagents.service import SubagentService

        release = Event()

        class BlockingRuntimeLoop:
            def run(self, session_id, message, trace_id=None, agent=None, session_messages=None, compacted_context=None, request_kind="interactive", parent_run_id=None, **kwargs):  # noqa: ANN001,E501
                release.wait(timeout=1.0)
                return [
                    OutboundEvent(
                        session_id=session_id,
                        run_id="run_child_reserved",
                        event_id="evt_child_reserved",
                        event_type="final",
                        sequence=2,
                        trace_id=trace_id or "trace_child_reserved",
                        payload={"text": "child finished"},
                    )
                ]

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        service = SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=BlockingRuntimeLoop(),
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
            auto_start_background=True,
        )

        first = service.spawn(
            task="background followup 1",
            label="reserved-1",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )
        second = service.spawn(
            task="background followup 2",
            label="reserved-2",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        self.assertEqual(first["queue_state"], "running")
        self.assertEqual(second["queue_state"], "queued")

        release.set()
        import time
        for _ in range(20):
            if service.store.get(first["task_id"]).status == "succeeded":
                break
            time.sleep(0.01)

    def test_cancel_signals_cooperative_stop_to_runtime_loop(self) -> None:
        from marten_runtime.subagents.service import SubagentService

        entered = Event()
        stopped = Event()

        class CooperativeRuntimeLoop:
            def run(self, session_id, message, trace_id=None, agent=None, session_messages=None, compacted_context=None, request_kind="interactive", parent_run_id=None, stop_event=None, deadline_monotonic=None, timeout_seconds_override=None):  # noqa: ANN001,E501
                assert stop_event is not None
                assert deadline_monotonic is not None
                assert timeout_seconds_override is not None
                entered.set()
                stop_event.wait(timeout=1.0)
                if stop_event.is_set():
                    stopped.set()
                return []

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        service = SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=CooperativeRuntimeLoop(),
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
        )
        result = service.spawn(
            task="background followup",
            label="cooperative-cancel",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        worker = Thread(target=service.run_next_queued_task)
        worker.start()
        self.assertTrue(entered.wait(timeout=1.0))
        service.cancel_task(result["task_id"])
        worker.join(timeout=2.0)

        self.assertTrue(stopped.is_set())
        self.assertEqual(service.store.get(result["task_id"]).status, "cancelled")
        self.assertNotIn(result["task_id"], service._execution_threads)

    def test_timeout_signals_cooperative_stop_to_runtime_loop(self) -> None:
        from marten_runtime.subagents.service import SubagentService

        entered = Event()
        stopped = Event()

        class CooperativeRuntimeLoop:
            def run(self, session_id, message, trace_id=None, agent=None, session_messages=None, compacted_context=None, request_kind="interactive", parent_run_id=None, stop_event=None, deadline_monotonic=None, timeout_seconds_override=None):  # noqa: ANN001,E501
                assert stop_event is not None
                assert deadline_monotonic is not None
                assert timeout_seconds_override is not None
                entered.set()
                stop_event.wait(timeout=1.0)
                if stop_event.is_set():
                    stopped.set()
                return []

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        service = SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=CooperativeRuntimeLoop(),
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=0.05,
        )
        result = service.spawn(
            task="background followup",
            label="cooperative-timeout",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        service.run_next_queued_task()

        self.assertTrue(entered.is_set())
        self.assertTrue(stopped.wait(timeout=1.0))
        self.assertEqual(service.store.get(result["task_id"]).status, "timed_out")
        self.assertNotIn(result["task_id"], service._execution_threads)

    def test_spawn_returns_immediate_acceptance_and_captures_parent_lineage(self) -> None:
        service = self._build_service()
        result = service.spawn(
            task="research the repository structure",
            label="repo-research",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            context_mode="brief_only",
            notify_on_finish=True,
        )

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["effective_tool_profile"], "restricted")
        self.assertEqual(result["queue_state"], "running")
        self.assertTrue(result["task_id"].startswith("task_"))
        self.assertTrue(result["child_session_id"].startswith("sess_"))

        task = service.store.get(result["task_id"])
        self.assertEqual(task.parent_session_id, "sess_parent")
        self.assertEqual(task.parent_run_id, "run_parent")
        self.assertEqual(task.status, "queued")

    def test_subagent_execution_uses_registered_target_agent_runtime_assets(self) -> None:
        from marten_runtime.agents.registry import AgentRegistry
        from marten_runtime.agents.specs import AgentSpec
        from marten_runtime.config.models_loader import ModelProfile, ModelsConfig
        from marten_runtime.subagents.service import SubagentService

        captured: dict[str, object] = {}

        class CapturingRuntimeLoop:
            def run(self, session_id, message, **kwargs):  # noqa: ANN001
                captured["session_id"] = session_id
                captured["message"] = message
                captured.update(kwargs)
                from marten_runtime.runtime.events import OutboundEvent

                return [
                    OutboundEvent(
                        session_id=session_id,
                        run_id="run_child_target_agent",
                        event_id="evt_child_target_agent",
                        event_type="final",
                        sequence=1,
                        trace_id=kwargs.get("trace_id", "trace_child_target_agent"),
                        payload={"text": "child finished"},
                    )
                ]

        class FakeLLMFactory:
            def get(self, profile_name, *, default_client=None):  # noqa: ANN001
                captured["factory_profile_name"] = profile_name
                captured["factory_default_client"] = default_client
                return {"profile_name": profile_name}

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentSpec(
                agent_id="coding",
                role="coding_agent",
                app_id="main_agent",
                allowed_tools=["runtime", "skill", "time"],
                prompt_mode="child",
                model_profile="openai_gpt5",
            )
        )
        app_runtime = SimpleNamespace(
            system_prompt="coding child prompt",
            manifest=SimpleNamespace(bootstrap_manifest_id="boot_main_agent_child"),
        )
        service = SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=CapturingRuntimeLoop(),
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
            agent_registry=agent_registry,
            app_runtimes={"main_agent": app_runtime},
            llm_client_factory=FakeLLMFactory(),
            models_config=ModelsConfig(
                default_profile="openai_gpt5",
                profiles={
                    "openai_gpt5": ModelProfile(
                        provider_ref="openai",
                        model="gpt-4.1",
                        tokenizer_family="openai_o200k",
                    )
                },
            ),
        )

        result = service.spawn(
            task="write a child coding summary",
            label="coding-child",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="coding",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        service.run_task_by_id(result["task_id"])

        agent = captured["agent"]
        self.assertEqual(agent.agent_id, "coding")
        self.assertEqual(agent.role, "coding_agent")
        self.assertEqual(agent.prompt_mode, "child")
        self.assertEqual(agent.app_id, "main_agent")
        self.assertEqual(agent.allowed_tools, ["runtime", "skill", "time"])
        self.assertEqual(captured["system_prompt"], "coding child prompt")
        self.assertEqual(captured["bootstrap_manifest_id"], "boot_main_agent_child")
        self.assertEqual(captured["model_profile_name"], "openai_gpt5")
        self.assertEqual(captured["tokenizer_family"], "openai_o200k")
        self.assertEqual(captured["factory_profile_name"], "openai_gpt5")
        self.assertEqual(captured["llm_client"], {"profile_name": "openai_gpt5"})

    def test_spawn_persists_target_agent_app_id_in_task_record(self) -> None:
        from marten_runtime.agents.registry import AgentRegistry
        from marten_runtime.agents.specs import AgentSpec
        from marten_runtime.subagents.service import SubagentService

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentSpec(
                agent_id="coding",
                role="coding_agent",
                app_id="code_assistant",
                allowed_tools=["runtime", "skill", "time"],
                prompt_mode="child",
                model_profile="openai_gpt5",
            )
        )
        service = SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=None,
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
            agent_registry=agent_registry,
        )

        result = service.spawn(
            task="write a child coding summary",
            label="coding-child",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="coding",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        task = service.store.get(result["task_id"])
        self.assertEqual(task.agent_id, "coding")
        self.assertEqual(task.app_id, "code_assistant")

    def test_spawn_queues_when_concurrency_cap_is_reached(self) -> None:
        service = self._build_service()
        service._running_tasks.add("task_running")

        result = service.spawn(
            task="background followup",
            label="queued-followup",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            context_mode="brief_only",
            notify_on_finish=True,
        )

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["queue_state"], "queued")
        self.assertEqual(service.store.get(result["task_id"]).status, "queued")

    def test_spawn_rejects_invalid_tool_profile(self) -> None:
        service = self._build_service()

        with self.assertRaises(ValueError):
            service.spawn(
                task="background followup",
                label="bad-profile",
                parent_session_id="sess_parent",
                parent_run_id="run_parent",
                parent_agent_id="main",
                app_id="main_agent",
                agent_id="main",
                requested_tool_profile="definitely_invalid",
                context_mode="brief_only",
                notify_on_finish=True,
            )

    def test_service_exposes_terminal_update_and_shutdown_contract(self) -> None:
        service = self._build_service()
        self.assertTrue(hasattr(service, "complete_task_success"))
        self.assertTrue(hasattr(service, "complete_task_failure"))
        self.assertTrue(hasattr(service, "complete_task_timeout"))
        self.assertTrue(hasattr(service, "cancel_task"))
        self.assertTrue(hasattr(service, "shutdown"))

    def test_spawn_downgrades_effective_profile_to_parent_ceiling(self) -> None:
        service = self._build_service()

        result = service.spawn(
            task="background followup",
            label="ceiling-check",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="elevated",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        self.assertEqual(result["effective_tool_profile"], "restricted")
        task = service.store.get(result["task_id"])
        self.assertEqual(task.effective_tool_profile, "restricted")

    def test_spawn_accepts_default_profile_alias_and_normalizes_to_restricted(self) -> None:
        service = self._build_service()

        result = service.spawn(
            task="background followup",
            label="default-alias",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="default",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        self.assertEqual(result["effective_tool_profile"], "restricted")
        task = service.store.get(result["task_id"])
        self.assertEqual(task.tool_profile, "restricted")
        self.assertEqual(task.effective_tool_profile, "restricted")

    def test_spawn_accepts_mcp_profile_alias_and_normalizes_to_standard(self) -> None:
        service = self._build_service()

        result = service.spawn(
            task="query github repo in background",
            label="mcp-alias",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="mcp",
            parent_allowed_tools=["automation", "mcp", "runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        self.assertEqual(result["effective_tool_profile"], "standard")
        task = service.store.get(result["task_id"])
        self.assertEqual(task.tool_profile, "standard")
        self.assertEqual(task.effective_tool_profile, "standard")

    def test_spawn_accepts_mcp_prefixed_profile_alias_and_normalizes_to_standard(self) -> None:
        service = self._build_service()

        result = service.spawn(
            task="query github repo in background",
            label="mcp-prefixed-alias",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="mcp:github-or-web",
            parent_allowed_tools=["automation", "mcp", "runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        self.assertEqual(result["effective_tool_profile"], "standard")
        task = service.store.get(result["task_id"])
        self.assertEqual(task.tool_profile, "standard")
        self.assertEqual(task.effective_tool_profile, "standard")

    def test_cancelled_queued_task_does_not_run_later(self) -> None:
        service = self._build_service()
        service._running_tasks.add("task_running")
        result = service.spawn(
            task="background followup",
            label="queued-then-cancelled",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        service.cancel_task(result["task_id"])
        service._running_tasks.clear()
        service.run_next_queued_task()

        task = service.store.get(result["task_id"])
        self.assertEqual(task.status, "cancelled")
        self.assertIsNone(task.child_run_id)

    def test_cancel_running_task_wins_over_late_success(self) -> None:
        from marten_runtime.subagents.service import SubagentService

        release = Event()

        class BlockingRuntimeLoop:
            def run(self, session_id, message, trace_id=None, agent=None, session_messages=None, compacted_context=None, request_kind="interactive", parent_run_id=None):  # noqa: ANN001,E501
                release.wait(timeout=1.0)
                return [
                    OutboundEvent(
                        session_id=session_id,
                        run_id="run_child_blocked",
                        event_id="evt_child_blocked",
                        event_type="final",
                        sequence=2,
                        trace_id=trace_id or "trace_child_blocked",
                        payload={"text": "child finished too late"},
                    )
                ]

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        service = SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=BlockingRuntimeLoop(),
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=1,
        )
        result = service.spawn(
            task="background followup",
            label="cancel-running",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        worker = Thread(target=service.run_next_queued_task)
        worker.start()
        service.cancel_task(result["task_id"])
        release.set()
        worker.join(timeout=2.0)

        task = service.store.get(result["task_id"])
        self.assertEqual(task.status, "cancelled")
        self.assertIsNone(task.result_summary)
        self.assertIsNone(task.child_run_id)

    def test_timeout_marks_task_timed_out_and_ignores_late_success(self) -> None:
        from marten_runtime.subagents.service import SubagentService

        release = Event()

        class BlockingRuntimeLoop:
            def run(self, session_id, message, trace_id=None, agent=None, session_messages=None, compacted_context=None, request_kind="interactive", parent_run_id=None):  # noqa: ANN001,E501
                release.wait(timeout=1.0)
                return [
                    OutboundEvent(
                        session_id=session_id,
                        run_id="run_child_timeout",
                        event_id="evt_child_timeout",
                        event_type="final",
                        sequence=2,
                        trace_id=trace_id or "trace_child_timeout",
                        payload={"text": "child finished too late"},
                    )
                ]

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        service = SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=BlockingRuntimeLoop(),
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=0,
        )
        result = service.spawn(
            task="background followup",
            label="timeout-running",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        service.run_next_queued_task()
        release.set()

        task = service.store.get(result["task_id"])
        self.assertEqual(task.status, "timed_out")
        self.assertIsNone(task.result_summary)
        self.assertIsNone(task.child_run_id)

    def test_error_terminal_event_marks_task_failed_instead_of_succeeded(self) -> None:
        from marten_runtime.subagents.service import SubagentService

        class ErrorRuntimeLoop:
            def run(self, session_id, message, trace_id=None, agent=None, session_messages=None, compacted_context=None, request_kind="interactive", parent_run_id=None):  # noqa: ANN001,E501
                return [
                    OutboundEvent(
                        session_id=session_id,
                        run_id="run_child_error",
                        event_id="evt_child_error",
                        event_type="error",
                        sequence=2,
                        trace_id=trace_id or "trace_child_error",
                        payload={"code": "PROVIDER_TIMEOUT", "text": "child provider timeout"},
                        created_at=datetime.now(timezone.utc),
                    )
                ]

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        service = SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=ErrorRuntimeLoop(),
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
        )
        accepted = service.spawn(
            task="background followup",
            label="error-child",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        service.run_next_queued_task()

        task = service.store.get(accepted["task_id"])
        self.assertEqual(task.status, "failed")
        self.assertEqual(task.error_text, "child provider timeout")
        self.assertEqual(task.child_run_id, "run_child_error")

    def test_cancel_running_task_keeps_slot_reserved_until_worker_exits(self) -> None:
        from marten_runtime.subagents.service import SubagentService

        entered = Event()
        release = Event()

        class SlowStoppingRuntimeLoop:
            def run(self, session_id, message, trace_id=None, agent=None, session_messages=None, compacted_context=None, request_kind="interactive", parent_run_id=None, stop_event=None, deadline_monotonic=None, timeout_seconds_override=None):  # noqa: ANN001,E501
                entered.set()
                if stop_event is not None:
                    stop_event.wait(timeout=1.0)
                release.wait(timeout=1.0)
                return []

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        service = SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=SlowStoppingRuntimeLoop(),
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
            auto_start_background=True,
        )
        first = service.spawn(
            task="background followup 1",
            label="cancel-slow-1",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )
        second = service.spawn(
            task="background followup 2",
            label="cancel-slow-2",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        self.assertTrue(entered.wait(timeout=1.0))
        service.cancel_task(first["task_id"])
        self.assertEqual(service.store.get(first["task_id"]).status, "cancelled")
        self.assertEqual(service.store.get(second["task_id"]).status, "queued")
        self.assertIn(first["task_id"], service._running_tasks)

        release.set()
        import time
        for _ in range(50):
            if service.store.get(second["task_id"]).status != "queued":
                break
            time.sleep(0.02)

        self.assertNotEqual(service.store.get(second["task_id"]).status, "queued")

    def test_terminal_callback_failure_does_not_break_successful_task_completion(self) -> None:
        from marten_runtime.subagents.service import SubagentService

        class FinalRuntimeLoop:
            def run(self, session_id, message, trace_id=None, agent=None, session_messages=None, compacted_context=None, request_kind="interactive", parent_run_id=None):  # noqa: ANN001,E501
                return [
                    OutboundEvent(
                        session_id=session_id,
                        run_id="run_child_final",
                        event_id="evt_child_final",
                        event_type="final",
                        sequence=2,
                        trace_id=trace_id or "trace_child_final",
                        payload={"text": "child finished"},
                        created_at=datetime.now(timezone.utc),
                    )
                ]

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        service = SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=FinalRuntimeLoop(),
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
            terminal_callback=lambda task: (_ for _ in ()).throw(
                RuntimeError(f"boom:{task.task_id}")
            ),
        )
        accepted = service.spawn(
            task="background followup",
            label="callback-failure-child",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        service.run_next_queued_task()

        task = service.store.get(accepted["task_id"])
        self.assertEqual(task.status, "succeeded")
        self.assertEqual(task.result_summary, "child finished")
        self.assertNotIn(task.task_id, service._running_tasks)

    def test_terminal_callback_failure_does_not_escape_cancel_path(self) -> None:
        from marten_runtime.subagents.service import SubagentService

        service = SubagentService(
            session_store=SessionStore(),
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=None,
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
            terminal_callback=lambda task: (_ for _ in ()).throw(
                RuntimeError(f"boom:{task.task_id}")
            ),
        )
        service.session_store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        accepted = service.spawn(
            task="background followup",
            label="callback-failure-cancel",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        task = service.cancel_task(accepted["task_id"])

        self.assertEqual(task.status, "cancelled")

    def test_shutdown_cancels_outstanding_tasks_deterministically(self) -> None:
        service = self._build_service()
        service._running_tasks.add("task_running")
        first = service.spawn(
            task="first queued",
            label="queued-1",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )
        second = service.spawn(
            task="second queued",
            label="queued-2",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            context_mode="brief_only",
            notify_on_finish=True,
        )

        service.shutdown()

        self.assertEqual(service.store.get(first["task_id"]).status, "cancelled")
        self.assertEqual(service.store.get(second["task_id"]).status, "cancelled")

    def test_successful_feishu_origin_task_pushes_completion_message_when_notify_enabled(self) -> None:
        from marten_runtime.runtime.events import OutboundEvent
        from marten_runtime.subagents.service import SubagentService

        class SuccessRuntimeLoop:
            def run(self, session_id, message, trace_id=None, agent=None, session_messages=None, compacted_context=None, request_kind="interactive", parent_run_id=None):  # noqa: ANN001,E501
                return [
                    OutboundEvent(
                        session_id=session_id,
                        run_id="run_child_notify",
                        event_id="evt_child_notify",
                        event_type="final",
                        sequence=2,
                        trace_id=trace_id or "trace_child_notify",
                        payload={"text": "child finished summary"},
                        created_at=datetime.now(timezone.utc),
                    )
                ]

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="oc_test_chat",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        delivery = FakeDeliveryClient()
        service = SubagentService(
            session_store=session_store,
            run_history=InMemoryRunHistory(),
            tool_registry=ToolRegistry(),
            runtime_loop=SuccessRuntimeLoop(),
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
            feishu_delivery=delivery,
        )
        accepted = service.spawn(
            task="background followup",
            label="notify-feishu",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            origin_channel_id="feishu",
            context_mode="brief_only",
            notify_on_finish=True,
        )

        service.run_next_queued_task()

        task = service.store.get(accepted["task_id"])
        self.assertEqual(task.status, "succeeded")
        self.assertEqual(len(delivery.payloads), 1)
        payload = delivery.payloads[0]
        self.assertEqual(payload.chat_id, "oc_test_chat")
        self.assertEqual(payload.event_type, "final")
        self.assertEqual(payload.run_id, "run_child_notify")
        self.assertIn("后台任务已完成", payload.text)
        self.assertIn("child finished summary", payload.text)

    def test_successful_feishu_origin_task_notification_carries_child_run_usage_summary(self) -> None:
        from marten_runtime.runtime.events import OutboundEvent
        from marten_runtime.subagents.service import SubagentService

        history = InMemoryRunHistory()

        class SuccessRuntimeLoop:
            def run(self, session_id, message, trace_id=None, agent=None, session_messages=None, compacted_context=None, request_kind="interactive", parent_run_id=None):  # noqa: ANN001,E501
                run = history.start(
                    session_id=session_id,
                    trace_id=trace_id or "trace_child_notify_usage",
                    config_snapshot_id="cfg_bootstrap",
                    bootstrap_manifest_id="boot_default",
                    parent_run_id=parent_run_id,
                )
                history.set_actual_usage(
                    run.run_id,
                    NormalizedUsage(
                        input_tokens=700,
                        output_tokens=33,
                        total_tokens=733,
                        provider_name="test",
                        model_name="test-model",
                    ),
                    stage="llm_first",
                )
                history.set_actual_usage(
                    run.run_id,
                    NormalizedUsage(
                        input_tokens=900,
                        output_tokens=44,
                        total_tokens=944,
                        provider_name="test",
                        model_name="test-model",
                    ),
                    stage="llm_second",
                )
                return [
                    OutboundEvent(
                        session_id=session_id,
                        run_id=run.run_id,
                        event_id="evt_child_notify_usage",
                        event_type="final",
                        sequence=2,
                        trace_id=trace_id or "trace_child_notify_usage",
                        payload={"text": "child finished summary"},
                        created_at=datetime.now(timezone.utc),
                    )
                ]

        session_store = SessionStore()
        session_store.create(
            session_id="sess_parent",
            conversation_id="oc_test_chat",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        delivery = FakeDeliveryClient()
        service = SubagentService(
            session_store=session_store,
            run_history=history,
            tool_registry=ToolRegistry(),
            runtime_loop=SuccessRuntimeLoop(),
            max_concurrent_subagents=1,
            max_queued_subagents=4,
            subagent_timeout_seconds=5,
            feishu_delivery=delivery,
        )
        accepted = service.spawn(
            task="background followup",
            label="notify-feishu-usage",
            parent_session_id="sess_parent",
            parent_run_id="run_parent",
            parent_agent_id="main",
            app_id="main_agent",
            agent_id="main",
            requested_tool_profile="restricted",
            parent_allowed_tools=["runtime", "skill", "time"],
            origin_channel_id="feishu",
            context_mode="brief_only",
            notify_on_finish=True,
        )

        service.run_next_queued_task()

        task = service.store.get(accepted["task_id"])
        payload = delivery.payloads[0]
        self.assertEqual(task.status, "succeeded")
        self.assertEqual(payload.run_id, task.child_run_id)
        self.assertEqual(
            payload.usage_summary,
            {
                "input_tokens": 900,
                "output_tokens": 44,
                "peak_tokens": 944,
                "cumulative_input_tokens": 1600,
                "cumulative_output_tokens": 77,
                "cumulative_tokens": 1677,
                "estimated_only": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
