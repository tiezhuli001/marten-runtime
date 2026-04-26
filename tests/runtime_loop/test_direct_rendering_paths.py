import threading
import unittest
from itertools import chain, repeat
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.store import SessionStore
from marten_runtime.self_improve.models import LessonCandidate, SystemLesson
from marten_runtime.tools.builtins.automation_tool import run_automation_tool
from marten_runtime.tools.builtins.runtime_tool import run_runtime_tool
from marten_runtime.tools.builtins.session_tool import run_session_tool
from marten_runtime.tools.builtins.self_improve_tool import (
    run_delete_lesson_candidate_tool,
    run_list_lesson_candidates_tool,
    run_self_improve_tool,
)
from marten_runtime.tools.builtins.skill_tool import run_skill_tool
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.registry import ToolRegistry
from marten_runtime.skills.service import SkillService
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.session.models import SessionMessage
from tests.support.domain_builders import build_self_improve_adapter
from tests.support.scripted_llm import ConcurrentInterleavingLLMClient, ObservedLLMClient


class RuntimeLoopDirectRenderingPathTests(unittest.TestCase):

    def test_runtime_keeps_per_run_llm_request_count_under_concurrent_overlap(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ConcurrentInterleavingLLMClient()
        runtime = RuntimeLoop(llm, tools, history)
        blocked = threading.Event()
        release = threading.Event()
        run_ids: dict[str, str] = {}

        def blocking_summary(*, user_message, **kwargs):  # noqa: ANN001
            if user_message == "first":
                blocked.set()
                release.wait(timeout=2)

        runtime._append_post_turn_summary = blocking_summary  # type: ignore[method-assign]

        def run_first() -> None:
            events = runtime.run(
                session_id="sess_first", message="first", trace_id="trace_first"
            )
            run_ids["first"] = events[0].run_id

        thread = threading.Thread(target=run_first)
        thread.start()
        self.assertTrue(blocked.wait(timeout=2))
        second_events = runtime.run(
            session_id="sess_second", message="second", trace_id="trace_second"
        )
        run_ids["second"] = second_events[0].run_id
        release.set()
        thread.join(timeout=2)

        self.assertEqual(history.get(run_ids["first"]).llm_request_count, 2)
        self.assertEqual(history.get(run_ids["second"]).llm_request_count, 1)

    def test_runtime_records_provider_attempt_diagnostics_on_run(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ObservedLLMClient()
        runtime = RuntimeLoop(llm, tools, history)

        events = runtime.run(
            session_id="sess_provider", message="hello", trace_id="trace_provider"
        )

        run = history.get(events[0].run_id)
        self.assertEqual(len(run.provider_calls), 1)
        provider_call = run.provider_calls[0]
        self.assertEqual(provider_call["stage"], "llm_first")
        self.assertEqual(provider_call["request_kind"], "interactive")
        self.assertEqual(provider_call["timeout_seconds"], 20)
        self.assertEqual(provider_call["max_attempts"], 2)
        self.assertEqual(provider_call["attempts"][0]["elapsed_ms"], 123)

    def test_runtime_propagates_selected_agent_identity_into_llm_request(self) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="done")])
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="coding",
            role="coding_agent",
            app_id="code_assistant",
            allowed_tools=["time"],
            prompt_mode="child",
        )

        runtime.run(
            session_id="sess_agent",
            message="fix it",
            trace_id="trace_agent",
            agent=agent,
        )

        self.assertEqual(llm.requests[0].agent_id, "coding")
        self.assertEqual(llm.requests[0].app_id, "code_assistant")
        self.assertEqual(llm.requests[0].prompt_mode, "child")
        self.assertEqual(llm.requests[0].available_tools, ["time"])

    def test_plain_message_returns_progress_then_final(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="hello")])
        runtime = RuntimeLoop(llm, tools, history)

        with patch(
            "marten_runtime.runtime.loop.time.perf_counter",
            side_effect=chain([10.0, 11.0, 11.12, 11.25], repeat(11.25)),
        ):
            events = runtime.run(
                session_id="sess_1", message="hello", trace_id="trace_plain"
            )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[0].trace_id, "trace_plain")
        self.assertEqual(events[0].run_id, events[1].run_id)
        self.assertEqual(events[1].payload["text"], "hello")
        self.assertEqual(llm.requests[0].available_tools, [])
        self.assertIsNone(llm.requests[0].finalization_evidence_ledger)

        run = history.get(events[0].run_id)
        self.assertEqual(run.trace_id, "trace_plain")
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.delivery_status, "final")
        self.assertEqual(run.finalization.assessment, "accepted")
        self.assertEqual(run.finalization.request_kind, "interactive")
        self.assertEqual(run.finalization.required_evidence_count, 0)
        self.assertFalse(run.finalization.retry_triggered)
        self.assertGreater(run.timings.llm_first_ms, 0)
        self.assertEqual(run.timings.tool_ms, 0)
        self.assertEqual(run.timings.llm_second_ms, 0)
        self.assertEqual(run.timings.total_ms, 1250)

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
        run = history.get(history.list_runs()[0].run_id)
        self.assertEqual(run.context_snapshot_id, llm.requests[0].context_snapshot_id)

    def test_runtime_rebinds_same_turn_followup_request_and_runtime_tool_after_session_resume(
        self,
    ) -> None:
        store = SessionStore()
        source = store.create(
            session_id="sess_source",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        target = store.create(
            session_id="sess_target",
            conversation_id="conv-target",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.append_message(source.session_id, SessionMessage.user("source user"))
        store.append_message(source.session_id, SessionMessage.assistant("source assistant"))
        store.append_message(target.session_id, SessionMessage.user("target user"))
        store.append_message(target.session_id, SessionMessage.assistant("target assistant"))

        history = InMemoryRunHistory()
        source_previous_run = history.start(
            session_id=source.session_id,
            trace_id="trace_source_previous",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_actual_usage(
            source_previous_run.run_id,
            NormalizedUsage(input_tokens=30, output_tokens=10, total_tokens=40),
            stage="llm_first",
        )
        history.finish(source_previous_run.run_id, "final")
        target_previous_run = history.start(
            session_id=target.session_id,
            trace_id="trace_target_previous",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_actual_usage(
            target_previous_run.run_id,
            NormalizedUsage(input_tokens=80, output_tokens=20, total_tokens=100),
            stage="llm_first",
        )
        history.finish(target_previous_run.run_id, "final")

        tools = ToolRegistry()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="session",
                    tool_payload={"action": "resume", "session_id": target.session_id},
                ),
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(final_text="已切换并查看完成"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload, *, tool_context=None, session_store=store: run_session_tool(
                payload,
                session_store=session_store,
                tool_context=tool_context,
            ),
        )
        tools.register(
            "runtime",
            lambda payload, *, tool_context=None, runtime_loop=runtime, run_history=history: run_runtime_tool(
                payload,
                tool_context=tool_context,
                runtime_loop=runtime_loop,
                run_history=run_history,
            ),
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session", "runtime"],
        )

        events = runtime.run(
            session_id=source.session_id,
            message=f"恢复到 {target.session_id} 后告诉我当前上下文窗口",
            trace_id="trace_rebind_resume",
            agent=agent,
            channel_id="http",
            conversation_id="conv-current",
            session_messages=store.get(source.session_id).history,
            session_store=store,
        )

        self.assertEqual(events[-1].event_type, "final")
        self.assertEqual(llm.requests[1].session_id, target.session_id)
        self.assertEqual(
            [item.content for item in llm.requests[1].conversation_messages],
            ["target user", "target assistant"],
        )
        run = history.get(events[-1].run_id)
        self.assertEqual(run.tool_calls[1]["tool_name"], "runtime")
        self.assertEqual(
            run.tool_calls[1]["tool_result"]["last_completed_run"]["run_id"],
            target_previous_run.run_id,
        )

    def test_runtime_passes_skill_heads_and_activated_bodies_into_llm_request(
        self,
    ) -> None:
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

        self.assertEqual(
            llm.requests[0].skill_heads_text,
            "Visible skills:\n- repo_helper: repo assistance",
        )
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["time"],
        )

        with patch(
            "marten_runtime.runtime.loop.time.perf_counter",
            side_effect=chain(
                [10.0, 11.0, 11.1, 11.2, 11.34, 12.0, 12.17, 12.5],
                repeat(12.5),
            ),
        ):
            events = runtime.run(
                session_id="sess_1",
                message="tell me now",
                trace_id="trace_tool",
                agent=agent,
            )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[0].run_id, events[1].run_id)
        self.assertEqual(events[1].payload["text"], "time=ok")
        self.assertEqual(llm.requests[0].available_tools, ["time"])
        self.assertIn("time", llm.requests[0].tool_snapshot.builtin_tools)
        run = history.get(events[0].run_id)
        self.assertEqual(
            run.tool_snapshot_id, llm.requests[0].tool_snapshot.tool_snapshot_id
        )
        self.assertGreater(run.timings.llm_first_ms, 0)
        self.assertGreater(run.timings.tool_ms, 0)
        self.assertEqual(run.timings.llm_second_ms, 0)
        self.assertEqual(run.timings.total_ms, 2500)

    def test_runtime_uses_llm_first_for_natural_language_time_query(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={}),
                LLMReply(final_text="现在是测试时间"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["time"],
        )

        events = runtime.run(
            session_id="sess_time_direct",
            message="当前几点",
            trace_id="trace_time_direct",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(events[-1].payload["text"], "现在是测试时间")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual(run.tool_calls[0]["tool_name"], "time")
        self.assertEqual(run.peak_preflight_stage, "tool_followup")

    def test_runtime_uses_combined_followup_reply_and_summary_without_third_llm(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "UTC"}),
                LLMReply(
                    final_text=(
                        "现在是 UTC 时间\n\n```tool_episode_summary\n"
                        '{"summary":"上一轮调用了 time 工具获取当前时间。","facts":[],"volatile":true,"keep_next_turn":false,"refresh_hint":"若再次询问当前时间，应重新调用工具。"}'
                        "\n```"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["time"],
        )

        events = runtime.run(
            session_id="sess_runtime_rule_summary",
            message="tell me now",
            trace_id="trace_runtime_rule_summary",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "现在是 UTC 时间")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual(len(run.tool_outcome_summaries), 1)
        self.assertTrue(run.tool_outcome_summaries[0].volatile)

    def test_runtime_direct_renders_spawn_subagent_acceptance_without_followup_llm(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "spawn_subagent",
            lambda payload: {
                "ok": True,
                "status": "accepted",
                "task_id": "task_spawn_ack",
                "child_session_id": "sess_child_ack",
                "effective_tool_profile": "standard",
                "queue_state": "running",
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="spawn_subagent",
                    tool_payload={
                        "task": "run child task",
                        "label": "child-task",
                        "tool_profile": "standard",
                        "notify_on_finish": True,
                        "finalize_response": True,
                    },
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["spawn_subagent"],
        )

        events = runtime.run(
            session_id="sess_spawn_ack",
            message="start background task",
            trace_id="trace_spawn_ack",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "已受理，子 agent 正在后台执行，完成后会通知你结果。")
        self.assertEqual(len(llm.requests), 1)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.finalization.assessment, "accepted")
        self.assertEqual(run.finalization.request_kind, "interactive")
        self.assertEqual(run.finalization.required_evidence_count, 1)
        self.assertEqual(run.tool_calls[0]["tool_name"], "spawn_subagent")

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
                    "agents: [main]\n"
                    "channels: [http]\n"
                    "---\n"
                    "Read repository files before proposing edits.\n"
                ),
                encoding="utf-8",
            )
            tools = ToolRegistry()
            tools.register(
                "skill",
                lambda payload: run_skill_tool(
                    payload, SkillService([str(skills_root)])
                ),
            )
            history = InMemoryRunHistory()
            llm = ScriptedLLMClient(
                [
                    LLMReply(
                        tool_name="skill",
                        tool_payload={"action": "load", "skill_id": "repo_helper"},
                    ),
                    LLMReply(final_text="ok"),
                ]
            )
            runtime = RuntimeLoop(llm, tools, history)
            agent = AgentSpec(
                agent_id="main",
                role="general_assistant",
                app_id="main_agent",
                allowed_tools=["skill"],
            )

            events = runtime.run(
                session_id="sess_skill",
                message="Need repo help",
                trace_id="trace_skill",
                agent=agent,
            )

            self.assertEqual(
                [event.event_type for event in events], ["progress", "final"]
            )
            self.assertEqual(llm.requests[0].available_tools, ["skill"])
            self.assertEqual(llm.requests[1].tool_history[0].tool_name, "skill")
            self.assertEqual(
                llm.requests[1].tool_history[0].tool_result["skill_id"], "repo_helper"
            )
            self.assertIn(
                "Read repository files before proposing edits.",
                llm.requests[1].tool_history[0].tool_result["body"],
            )

    def test_runtime_can_use_self_improve_candidate_tools_without_affecting_active_lessons(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = build_self_improve_adapter(Path(tmpdir))
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_1",
                    agent_id="main",
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
                    agent_id="main",
                    topic_key="provider_timeout",
                    lesson_text="keep this active lesson",
                    source_fingerprints=["fp_timeout"],
                    active=True,
                )
            )
            tools = ToolRegistry()
            tools.register(
                "self_improve",
                lambda payload: run_self_improve_tool(payload, adapter, store),
            )
            history = InMemoryRunHistory()
            llm = ScriptedLLMClient(
                [
                    LLMReply(
                        tool_name="self_improve",
                        tool_payload={
                            "action": "list_candidates",
                            "agent_id": "main",
                        },
                    ),
                    LLMReply(
                        tool_name="self_improve",
                        tool_payload={
                            "action": "delete_candidate",
                            "candidate_id": "cand_1",
                        },
                    ),
                    LLMReply(final_text="已删除这个候选规则。"),
                ]
            )
            runtime = RuntimeLoop(llm, tools, history)
            agent = AgentSpec(
                agent_id="main",
                role="general_assistant",
                app_id="main_agent",
                allowed_tools=["self_improve"],
            )

            events = runtime.run(
                session_id="sess_candidates",
                message="删除这个候选规则",
                trace_id="trace_candidates",
                agent=agent,
            )
            remaining_candidates = store.list_candidates(agent_id="main", limit=10)
            active_lessons = store.list_active_lessons(agent_id="main")

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "已删除这个候选规则。")
        self.assertEqual(remaining_candidates, [])
        self.assertEqual(len(active_lessons), 1)
        self.assertEqual(active_lessons[0].lesson_id, "lesson_1")


if __name__ == "__main__":
    unittest.main()
