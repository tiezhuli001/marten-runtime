import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.automation.store import AutomationStore
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.session.models import SessionMessage
from marten_runtime.self_improve.models import LessonCandidate, SystemLesson
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.skills.service import SkillService
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.tools.builtins.automation_tool import run_automation_tool
from marten_runtime.tools.builtins.delete_lesson_candidate_tool import run_delete_lesson_candidate_tool
from marten_runtime.tools.builtins.list_lesson_candidates_tool import run_list_lesson_candidates_tool
from marten_runtime.tools.builtins.self_improve_tool import run_self_improve_tool
from marten_runtime.tools.builtins.skill_tool import run_skill_tool
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.registry import ToolRegistry


class FailingLLMClient:
    provider_name = "failing"
    model_name = "failing-local"

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("provider_transport_error:connection reset")


class BrokenInternalLLMClient:
    provider_name = "broken"
    model_name = "broken-local"

    def complete(self, request):  # noqa: ANN001
        raise ValueError("boom")


class BrokenToolLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def complete(self, request):  # noqa: ANN001
        return LLMReply(tool_name="broken_tool", tool_payload={"value": "x"})


class RuntimeLoopTests(unittest.TestCase):
    def test_plain_message_returns_progress_then_final(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="hello")])
        runtime = RuntimeLoop(llm, tools, history)

        events = runtime.run(session_id="sess_1", message="hello", trace_id="trace_plain")

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[0].trace_id, "trace_plain")
        self.assertEqual(events[0].run_id, events[1].run_id)
        self.assertEqual(events[1].payload["text"], "hello")
        self.assertEqual(llm.requests[0].available_tools, [])

        run = history.get(events[0].run_id)
        self.assertEqual(run.trace_id, "trace_plain")
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.delivery_status, "final")

    def test_runtime_passes_system_prompt_to_llm_request(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="hello")])
        runtime = RuntimeLoop(llm, tools, history)

        runtime.run(
            session_id="sess_1",
            message="hello",
            trace_id="trace_plain",
            system_prompt="You are marten-runtime.",
        )

        self.assertEqual(llm.requests[0].system_prompt, "You are marten-runtime.")

    def test_runtime_replays_session_history_into_llm_request_context(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="hello again")])
        runtime = RuntimeLoop(llm, tools, history)

        runtime.run(
            session_id="sess_1",
            message="current turn",
            trace_id="trace_context",
            system_prompt="You are marten-runtime.",
            session_messages=[
                SessionMessage.system("created"),
                SessionMessage.user("previous question"),
                SessionMessage.assistant("previous answer"),
                SessionMessage.user("current turn"),
            ],
        )

        self.assertEqual(
            [item.content for item in llm.requests[0].conversation_messages],
            ["previous question", "previous answer"],
        )
        self.assertEqual(llm.requests[0].working_context["active_goal"], "current turn")
        run = history.get(llm.requests[0].trace_id.replace("trace_", "run_")) if False else history.get(
            history.list_runs()[0].run_id
        )
        self.assertEqual(run.context_snapshot_id, llm.requests[0].context_snapshot_id)

    def test_runtime_passes_skill_heads_and_activated_bodies_into_llm_request(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="hello again")])
        runtime = RuntimeLoop(llm, tools, history)

        runtime.run(
            session_id="sess_skills",
            message="help with git repo",
            trace_id="trace_skills",
            system_prompt="You are marten-runtime.",
            skill_snapshot=SkillSnapshot(
                skill_snapshot_id="skill_1",
                heads=[],
                always_on_ids=["always_on"],
            ),
            skill_heads_text="Visible skills:\n- repo_helper: repo assistance",
            always_on_skill_text="Always on body",
            activated_skill_ids=["repo_helper"],
            activated_skill_bodies=["Repo helper body"],
        )

        self.assertEqual(llm.requests[0].skill_heads_text, "Visible skills:\n- repo_helper: repo assistance")
        self.assertEqual(llm.requests[0].always_on_skill_text, "Always on body")
        self.assertEqual(llm.requests[0].activated_skill_bodies, ["Repo helper body"])
        self.assertEqual(llm.requests[0].activated_skill_ids, ["repo_helper"])
        self.assertEqual(llm.requests[0].skill_snapshot_id, "skill_1")
        run = history.get(history.list_runs()[0].run_id)
        self.assertEqual(run.skill_snapshot_id, "skill_1")

    def test_runtime_uses_structured_tool_call_and_agent_tool_contract(self) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "UTC"}),
                LLMReply(final_text="time=ok"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["time"],
        )

        events = runtime.run(session_id="sess_1", message="tell me now", trace_id="trace_tool", agent=agent)

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[0].run_id, events[1].run_id)
        self.assertEqual(events[1].payload["text"], "time=ok")
        self.assertEqual(llm.requests[0].available_tools, ["time"])
        self.assertIn("time", llm.requests[0].tool_snapshot.builtin_tools)
        self.assertEqual(history.get(events[0].run_id).tool_snapshot_id, llm.requests[0].tool_snapshot.tool_snapshot_id)

    def test_runtime_supports_multi_step_tool_loop_before_final(self) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        tools.register("mock_search", lambda payload: {"result_text": f"search:{payload['query']}"})
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "UTC"}),
                LLMReply(tool_name="mock_search", tool_payload={"query": "utc follow-up"}),
                LLMReply(final_text="done"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["time", "mock_search"],
        )

        events = runtime.run(session_id="sess_multi", message="tell me now", trace_id="trace_multi", agent=agent)

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "done")
        self.assertEqual(len(llm.requests), 3)
        self.assertEqual(llm.requests[1].tool_history[0].tool_name, "time")
        self.assertEqual(llm.requests[2].tool_history[1].tool_name, "mock_search")

    def test_runtime_returns_error_when_llm_requests_tool_outside_agent_contract(self) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(tool_name="time", tool_payload={"timezone": "UTC"})])
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=[],
        )

        events = runtime.run(session_id="sess_1", message="tell me now", trace_id="trace_denied", agent=agent)

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "TOOL_NOT_ALLOWED")
        self.assertEqual(events[-1].payload["text"], "当前操作未被允许，请换个说法或缩小范围。")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "TOOL_NOT_ALLOWED")

    def test_runtime_distinguishes_tool_execution_failure_from_generic_runtime_failure(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        tools.register("broken_tool", lambda payload: (_ for _ in ()).throw(ValueError("tool blew up")))
        runtime = RuntimeLoop(BrokenToolLLMClient(), tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["broken_tool"],
        )

        events = runtime.run(session_id="sess_tool_fail", message="run broken tool", trace_id="trace_tool_fail", agent=agent)

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "TOOL_EXECUTION_FAILED")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "TOOL_EXECUTION_FAILED")

    def test_runtime_returns_error_when_final_text_is_empty_after_tool_call(self) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "UTC"}),
                LLMReply(final_text=""),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["time"],
        )

        events = runtime.run(session_id="sess_empty", message="tell me now", trace_id="trace_empty", agent=agent)

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "EMPTY_FINAL_RESPONSE")
        self.assertEqual(events[-1].payload["text"], "暂时没有生成可见回复，请重试。")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "EMPTY_FINAL_RESPONSE")

    def test_runtime_exposes_provider_specific_error_codes_for_provider_failures(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tools = ToolRegistry()
            history = InMemoryRunHistory()
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            runtime = RuntimeLoop(
                FailingLLMClient(),
                tools,
                history,
                self_improve_recorder=SelfImproveRecorder(store),
            )

            events = runtime.run(session_id="sess_fail", message="hello", trace_id="trace_fail")
            failures = store.list_recent_failures(agent_id="assistant", limit=10)

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(events[-1].payload["text"], "暂时没有生成可见回复，请重试。")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].error_code, "PROVIDER_TRANSPORT_ERROR")

    def test_runtime_keeps_runtime_loop_failed_for_unknown_internal_exceptions(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tools = ToolRegistry()
            history = InMemoryRunHistory()
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            runtime = RuntimeLoop(
                BrokenInternalLLMClient(),
                tools,
                history,
                self_improve_recorder=SelfImproveRecorder(store),
            )

            events = runtime.run(session_id="sess_fail_internal", message="hello", trace_id="trace_fail_internal")
            failures = store.list_recent_failures(agent_id="assistant", limit=10)

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "RUNTIME_LOOP_FAILED")
        self.assertEqual(events[-1].payload["text"], "暂时没有生成可见回复，请重试。")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "RUNTIME_LOOP_FAILED")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].error_code, "RUNTIME_LOOP_FAILED")

    def test_runtime_records_recovery_after_later_success_on_compatible_message(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tools = ToolRegistry()
            history = InMemoryRunHistory()
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            recorder = SelfImproveRecorder(store)
            failing_runtime = RuntimeLoop(
                FailingLLMClient(),
                tools,
                history,
                self_improve_recorder=recorder,
            )
            success_runtime = RuntimeLoop(
                ScriptedLLMClient([LLMReply(final_text="done")]),
                tools,
                history,
                self_improve_recorder=recorder,
            )

            failing_runtime.run(session_id="sess_fail", message="hello", trace_id="trace_fail")
            success_runtime.run(session_id="sess_success", message="hello", trace_id="trace_success")
            recoveries = store.list_recent_recoveries(agent_id="assistant", limit=10)

        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0].recovery_kind, "same_fingerprint_success")

    def test_runtime_allows_main_agent_to_register_automation_via_family_tool(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteAutomationStore(Path(tmpdir) / "automations.sqlite3")
            adapter = DomainDataAdapter(
                self_improve_store=SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3"),
                automation_store=store,
            )
            tools = ToolRegistry()
            tools.register(
                "automation",
                lambda payload: run_automation_tool(payload, store, adapter),
            )
            history = InMemoryRunHistory()
            llm = ScriptedLLMClient(
                [
                    LLMReply(
                        tool_name="automation",
                        tool_payload={
                            "action": "register",
                            "automation_id": "daily_hot",
                            "name": "Daily GitHub Hot Repos",
                            "app_id": "example_assistant",
                            "agent_id": "assistant",
                            "prompt_template": "Summarize today's hot repositories.",
                            "schedule_kind": "daily",
                            "schedule_expr": "09:30",
                            "timezone": "Asia/Shanghai",
                            "session_target": "isolated",
                            "delivery_channel": "feishu",
                            "delivery_target": "oc_test_chat",
                            "skill_id": "github_hot_repos_digest",
                        },
                    ),
                    LLMReply(final_text="已为你创建每日 GitHub 热门项目推送。"),
                ]
            )
            runtime = RuntimeLoop(llm, tools, history)
            agent = AgentSpec(
                agent_id="assistant",
                role="general_assistant",
                app_id="example_assistant",
                allowed_tools=["automation"],
            )

            events = runtime.run(
                session_id="sess_register",
                message="请每天 09:30 给我推送 GitHub 热门项目。",
                trace_id="trace_register",
                agent=agent,
            )

            self.assertEqual([event.event_type for event in events], ["progress", "final"])
            enabled = store.list_enabled()
            self.assertEqual(len(enabled), 1)
            self.assertEqual(enabled[0].automation_id, "daily_hot")
            self.assertEqual(enabled[0].schedule_expr, "09:30")
            self.assertEqual(enabled[0].delivery_target, "oc_test_chat")
            self.assertEqual(llm.requests[0].available_tools, ["automation"])

    def test_runtime_can_load_skill_body_via_skill_tool(self) -> None:
        with TemporaryDirectory() as tmpdir:
            skills_root = Path(tmpdir) / "skills"
            skill_dir = skills_root / "repo_helper"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                (
                    "---\n"
                    "skill_id: repo_helper\n"
                    "name: Repo Helper\n"
                    "description: inspect repositories\n"
                    "enabled: true\n"
                    "agents: [assistant]\n"
                    "channels: [http]\n"
                    "---\n"
                    "Read repository files before proposing edits.\n"
                ),
                encoding="utf-8",
            )
            tools = ToolRegistry()
            tools.register(
                "skill",
                lambda payload: run_skill_tool(payload, SkillService([str(skills_root)])),
            )
            history = InMemoryRunHistory()
            llm = ScriptedLLMClient(
                [
                    LLMReply(tool_name="skill", tool_payload={"action": "load", "skill_id": "repo_helper"}),
                    LLMReply(final_text="ok"),
                ]
            )
            runtime = RuntimeLoop(llm, tools, history)
            agent = AgentSpec(
                agent_id="assistant",
                role="general_assistant",
                app_id="example_assistant",
                allowed_tools=["skill"],
            )

            events = runtime.run(
                session_id="sess_skill",
                message="Need repo help",
                trace_id="trace_skill",
                agent=agent,
            )

            self.assertEqual([event.event_type for event in events], ["progress", "final"])
            self.assertEqual(llm.requests[0].available_tools, ["skill"])
            self.assertEqual(llm.requests[1].tool_history[0].tool_name, "skill")
            self.assertEqual(llm.requests[1].tool_history[0].tool_result["skill_id"], "repo_helper")
            self.assertIn("Read repository files before proposing edits.", llm.requests[1].tool_history[0].tool_result["body"])

    def test_runtime_can_use_self_improve_candidate_tools_without_affecting_active_lessons(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            adapter = DomainDataAdapter(self_improve_store=store)
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_1",
                    agent_id="assistant",
                    source_fingerprints=["fp_one", "fp_one"],
                    candidate_text="candidate lesson",
                    rationale="candidate rationale",
                    status="pending",
                    score=0.9,
                )
            )
            store.save_lesson(
                SystemLesson(
                    lesson_id="lesson_1",
                    agent_id="assistant",
                    topic_key="provider_timeout",
                    lesson_text="keep this active lesson",
                    source_fingerprints=["fp_timeout"],
                    active=True,
                )
            )
            tools = ToolRegistry()
            tools.register("self_improve", lambda payload: run_self_improve_tool(payload, adapter, store))
            history = InMemoryRunHistory()
            llm = ScriptedLLMClient(
                [
                    LLMReply(
                        tool_name="self_improve",
                        tool_payload={"action": "list_candidates", "agent_id": "assistant"},
                    ),
                    LLMReply(
                        tool_name="self_improve",
                        tool_payload={"action": "delete_candidate", "candidate_id": "cand_1"},
                    ),
                    LLMReply(final_text="已删除这个候选规则。"),
                ]
            )
            runtime = RuntimeLoop(llm, tools, history)
            agent = AgentSpec(
                agent_id="assistant",
                role="general_assistant",
                app_id="example_assistant",
                allowed_tools=["self_improve"],
            )

            events = runtime.run(
                session_id="sess_candidates",
                message="删除这个候选规则",
                trace_id="trace_candidates",
                agent=agent,
            )
            remaining_candidates = store.list_candidates(agent_id="assistant", limit=10)
            active_lessons = store.list_active_lessons(agent_id="assistant")

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "已删除这个候选规则。")
        self.assertEqual(remaining_candidates, [])
        self.assertEqual(len(active_lessons), 1)
        self.assertEqual(active_lessons[0].lesson_id, "lesson_1")


if __name__ == "__main__":
    unittest.main()
