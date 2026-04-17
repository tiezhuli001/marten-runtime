import unittest

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.observability.langfuse import build_langfuse_observer
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.tools.registry import ToolRegistry
from tests.support.scripted_llm import FailingLLMClient


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.traces: list[dict] = []
        self.generations: list[dict] = []
        self.tool_spans: list[dict] = []
        self.finalizations: list[dict] = []

    def create_trace(self, payload: dict) -> dict:
        self.traces.append(payload)
        return {
            "trace_id": payload.get("trace_id") or "lf-generated",
            "url": f"https://langfuse.example/trace/{payload.get('trace_id') or 'lf-generated'}",
        }

    def record_generation(self, payload: dict) -> None:
        self.generations.append(payload)

    def record_tool_span(self, payload: dict) -> None:
        self.tool_spans.append(payload)

    def finalize_trace(self, payload: dict) -> None:
        self.finalizations.append(payload)

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class ThrowingLangfuseClient:
    def create_trace(self, payload: dict) -> dict:
        del payload
        raise RuntimeError("langfuse create boom")

    def record_generation(self, payload: dict) -> None:
        del payload
        raise RuntimeError("langfuse generation boom")

    def record_tool_span(self, payload: dict) -> None:
        del payload
        raise RuntimeError("langfuse tool boom")

    def finalize_trace(self, payload: dict) -> None:
        del payload
        raise RuntimeError("langfuse finalize boom")

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class RuntimeLoopLangfuseObservabilityTests(unittest.TestCase):
    def _build_observer(self, fake_client: FakeLangfuseClient):
        return build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=fake_client,
        )

    def test_plain_chat_starts_and_finalizes_root_trace_with_single_generation(self) -> None:
        fake_client = FakeLangfuseClient()
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(
            ScriptedLLMClient([LLMReply(final_text="plain-ok")]),
            ToolRegistry(),
            history,
            langfuse_observer=self._build_observer(fake_client),
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=[],
        )

        events = runtime.run(
            session_id="sess_plain",
            message="hello",
            trace_id="trace_plain",
            agent=agent,
        )
        run = history.get(events[-1].run_id)

        self.assertEqual(len(fake_client.traces), 1)
        self.assertEqual(fake_client.traces[0]["trace_id"], "trace_plain")
        self.assertEqual(len(fake_client.generations), 1)
        self.assertEqual(fake_client.generations[0]["name"], "llm.first")
        self.assertEqual(fake_client.generations[0]["status"], "success")
        self.assertEqual(fake_client.generations[0]["output_payload"]["final_text"], "plain-ok")
        self.assertEqual(len(fake_client.finalizations), 1)
        self.assertEqual(fake_client.finalizations[0]["status"], "succeeded")
        self.assertEqual(run.external_observability.langfuse_trace_id, "trace_plain")
        self.assertEqual(
            run.external_observability.langfuse_url,
            "https://langfuse.example/trace/trace_plain",
        )

    def test_provider_failure_records_error_generation_and_failed_trace(self) -> None:
        fake_client = FakeLangfuseClient()
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(
            FailingLLMClient(),
            ToolRegistry(),
            history,
            langfuse_observer=self._build_observer(fake_client),
        )

        events = runtime.run(
            session_id="sess_fail",
            message="hello",
            trace_id="trace_fail",
        )
        run = history.get(events[-1].run_id)

        self.assertEqual(run.status, "failed")
        self.assertEqual(len(fake_client.traces), 1)
        self.assertEqual(len(fake_client.generations), 1)
        self.assertEqual(fake_client.generations[0]["status"], "error")
        self.assertEqual(fake_client.generations[0]["error_code"], "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(len(fake_client.finalizations), 1)
        self.assertEqual(fake_client.finalizations[0]["status"], "failed")
        self.assertEqual(fake_client.finalizations[0]["error_code"], "PROVIDER_TRANSPORT_ERROR")

    def test_tool_followup_records_two_generations_with_stable_trace_ref(self) -> None:
        fake_client = FakeLangfuseClient()
        tools = ToolRegistry()
        tools.register("mock_tool", lambda payload: {"result_text": "done", "ok": True})
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(
            ScriptedLLMClient(
                [
                    LLMReply(tool_name="mock_tool", tool_payload={"query": "x"}),
                    LLMReply(final_text="tool-finish"),
                ]
            ),
            tools,
            history,
            langfuse_observer=self._build_observer(fake_client),
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["mock_tool"],
        )

        events = runtime.run(
            session_id="sess_tool",
            message="use tool",
            trace_id="trace_tool",
            agent=agent,
        )
        run = history.get(events[-1].run_id)

        self.assertEqual([item["name"] for item in fake_client.generations], ["llm.first", "llm.followup"])
        self.assertEqual(fake_client.generations[0]["output_payload"]["tool_name"], "mock_tool")
        self.assertEqual(fake_client.generations[1]["output_payload"]["final_text"], "tool-finish")
        self.assertEqual(run.external_observability.langfuse_trace_id, "trace_tool")

    def test_successful_builtin_tool_call_records_tool_span(self) -> None:
        fake_client = FakeLangfuseClient()
        tools = ToolRegistry()
        tools.register("time", lambda payload: {"iso_time": "2026-04-17T00:00:00Z", "ok": True})
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(
            ScriptedLLMClient([LLMReply(tool_name="time", tool_payload={"timezone": "UTC"}), LLMReply(final_text="done")]),
            tools,
            history,
            langfuse_observer=self._build_observer(fake_client),
        )
        agent = AgentSpec(agent_id="main", role="general_assistant", app_id="main_agent", allowed_tools=["time"])

        runtime.run(session_id="sess_builtin", message="time", trace_id="trace_builtin", agent=agent)

        self.assertEqual(len(fake_client.tool_spans), 1)
        self.assertEqual(fake_client.tool_spans[0]["tool_name"], "time")
        self.assertEqual(fake_client.tool_spans[0]["status"], "success")

    def test_successful_mcp_tool_call_records_tool_span(self) -> None:
        fake_client = FakeLangfuseClient()
        tools = ToolRegistry()
        tools.register(
            "mcp",
            lambda payload: {"server_id": "github", "result_text": "repo_count=42", "ok": True},
            source_kind="mcp",
            server_id="github",
        )
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(
            ScriptedLLMClient([LLMReply(tool_name="mcp", tool_payload={"action": "call"}), LLMReply(final_text="done")]),
            tools,
            history,
            langfuse_observer=self._build_observer(fake_client),
        )
        agent = AgentSpec(agent_id="main", role="general_assistant", app_id="main_agent", allowed_tools=["mcp"])

        runtime.run(session_id="sess_mcp", message="mcp", trace_id="trace_mcp", agent=agent)

        self.assertEqual(len(fake_client.tool_spans), 1)
        self.assertEqual(fake_client.tool_spans[0]["tool_name"], "mcp")
        self.assertEqual(fake_client.tool_spans[0]["status"], "success")
        self.assertEqual(fake_client.tool_spans[0]["metadata"]["source_kind"], "mcp")

    def test_rejected_tool_call_records_error_tool_span(self) -> None:
        fake_client = FakeLangfuseClient()
        tools = ToolRegistry()
        tools.register("time", lambda payload: {"iso_time": "2026-04-17T00:00:00Z", "ok": True})
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(
            ScriptedLLMClient([LLMReply(tool_name="time", tool_payload={"timezone": "UTC"})]),
            tools,
            history,
            langfuse_observer=self._build_observer(fake_client),
        )
        agent = AgentSpec(agent_id="main", role="general_assistant", app_id="main_agent", allowed_tools=[])

        events = runtime.run(session_id="sess_reject", message="time", trace_id="trace_reject", agent=agent)
        run = history.get(events[-1].run_id)

        self.assertEqual(run.status, "failed")
        self.assertEqual(len(fake_client.tool_spans), 1)
        self.assertEqual(fake_client.tool_spans[0]["status"], "error")
        self.assertEqual(fake_client.tool_spans[0]["error_code"], run.error_code)

    def test_failing_tool_call_records_error_tool_span(self) -> None:
        fake_client = FakeLangfuseClient()
        tools = ToolRegistry()
        def broken(_payload):
            raise RuntimeError("boom")
        tools.register("broken_tool", broken)
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(
            ScriptedLLMClient([LLMReply(tool_name="broken_tool", tool_payload={"value": "x"})]),
            tools,
            history,
            langfuse_observer=self._build_observer(fake_client),
        )
        agent = AgentSpec(agent_id="main", role="general_assistant", app_id="main_agent", allowed_tools=["broken_tool"])

        events = runtime.run(session_id="sess_broken", message="broken", trace_id="trace_broken", agent=agent)
        run = history.get(events[-1].run_id)

        self.assertEqual(run.status, "failed")
        self.assertEqual(len(fake_client.tool_spans), 1)
        self.assertEqual(fake_client.tool_spans[0]["status"], "error")
        self.assertEqual(fake_client.tool_spans[0]["error_code"], run.error_code)

    def test_langfuse_client_errors_do_not_break_successful_runtime_turn(self) -> None:
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(
            ScriptedLLMClient([LLMReply(final_text="plain-ok")]),
            ToolRegistry(),
            history,
            langfuse_observer=build_langfuse_observer(
                env={
                    "LANGFUSE_PUBLIC_KEY": "pk-test",
                    "LANGFUSE_SECRET_KEY": "sk-test",
                    "LANGFUSE_BASE_URL": "https://langfuse.example",
                },
                client=ThrowingLangfuseClient(),
            ),
        )

        events = runtime.run(
            session_id="sess_fail_open",
            message="hello",
            trace_id="trace_fail_open",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].event_type, "final")
        self.assertEqual(run.status, "succeeded")

    def test_trace_finalization_uses_cumulative_usage_for_tool_followup_run(self) -> None:
        fake_client = FakeLangfuseClient()
        tools = ToolRegistry()
        tools.register("mock_tool", lambda payload: {"result_text": "done", "ok": True})
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(
            ScriptedLLMClient(
                [
                    LLMReply(
                        tool_name="mock_tool",
                        tool_payload={"query": "x"},
                        usage=NormalizedUsage(
                            input_tokens=25,
                            output_tokens=5,
                            total_tokens=30,
                            provider_name="scripted",
                            model_name="test-double",
                        ),
                    ),
                    LLMReply(
                        final_text="tool-finish",
                        usage=NormalizedUsage(
                            input_tokens=20,
                            output_tokens=10,
                            total_tokens=30,
                            provider_name="scripted",
                            model_name="test-double",
                        ),
                    ),
                ]
            ),
            tools,
            history,
            langfuse_observer=self._build_observer(fake_client),
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["mock_tool"],
        )

        events = runtime.run(
            session_id="sess_usage",
            message="use tool",
            trace_id="trace_usage",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(fake_client.finalizations[-1]["usage"]["input_tokens"], 45)
        self.assertEqual(fake_client.finalizations[-1]["usage"]["output_tokens"], 15)
        self.assertEqual(fake_client.finalizations[-1]["usage"]["total_tokens"], 60)
        self.assertEqual(run.actual_cumulative_input_tokens, 45)
        self.assertEqual(run.actual_cumulative_output_tokens, 15)
        self.assertEqual(run.actual_cumulative_total_tokens, 60)


if __name__ == "__main__":
    unittest.main()
