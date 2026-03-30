import unittest

from marten_runtime.automation.store import AutomationStore
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.session.models import SessionMessage
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.tools.builtins.register_automation_tool import run_register_automation_tool
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
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "TOOL_NOT_ALLOWED")

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
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(FailingLLMClient(), tools, history)

        events = runtime.run(session_id="sess_fail", message="hello", trace_id="trace_fail")

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(events[-1].payload["text"], "暂时没有生成可见回复，请重试。")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "PROVIDER_TRANSPORT_ERROR")

    def test_runtime_keeps_runtime_loop_failed_for_unknown_internal_exceptions(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(BrokenInternalLLMClient(), tools, history)

        events = runtime.run(session_id="sess_fail_internal", message="hello", trace_id="trace_fail_internal")

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "RUNTIME_LOOP_FAILED")
        self.assertEqual(events[-1].payload["text"], "暂时没有生成可见回复，请重试。")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "RUNTIME_LOOP_FAILED")

    def test_runtime_allows_main_agent_to_register_automation_via_builtin_tool(self) -> None:
        store = AutomationStore()
        tools = ToolRegistry()
        tools.register(
            "register_automation",
            lambda payload: run_register_automation_tool(payload, store),
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="register_automation",
                    tool_payload={
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
            allowed_tools=["register_automation"],
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
        self.assertEqual(llm.requests[0].available_tools, ["register_automation"])


if __name__ == "__main__":
    unittest.main()
