import unittest

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.config.models_loader import ModelProfile
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.registry import ToolRegistry


class AlwaysTimeoutLLMClient:
    provider_name = "openai"
    model_name = "gpt-5.4"
    profile_name = "openai_gpt5"

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("provider_transport_error:connection reset")


class EmptyReplyLLMClient:
    provider_name = "openai"
    model_name = "gpt-5.4"
    profile_name = "openai_gpt5"

    def complete(self, request):  # noqa: ANN001
        return LLMReply(final_text="")


class ToolThenTimeoutLLMClient:
    provider_name = "openai"
    model_name = "gpt-5.4"
    profile_name = "openai_gpt5"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request):  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            return LLMReply(tool_name="time", tool_payload={"timezone": "UTC"})
        raise RuntimeError("provider_transport_error:connection reset")


class ToolThenEmptyLLMClient:
    provider_name = "openai"
    model_name = "gpt-5.4"
    profile_name = "openai_gpt5"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request):  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            return LLMReply(tool_name="time", tool_payload={"timezone": "UTC"})
        return LLMReply(final_text="")


class RuntimeLoopProviderFailoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = ToolRegistry()
        self.tools.register("time", run_time_tool)
        self.agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["time"],
        )
        self.profiles = {
            "openai_gpt5": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["kimi_k2"],
                tokenizer_family="openai_o200k",
            ),
            "kimi_k2": ModelProfile(
                provider_ref="kimi",
                model="kimi-k2",
                tokenizer_family="openai_o200k",
            ),
        }

    def test_first_turn_provider_error_falls_back_before_any_tool_call(self) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient([LLMReply(final_text="fallback hello")])
        fallback.provider_name = "kimi"
        fallback.model_name = "kimi-k2"
        fallback.profile_name = "kimi_k2"
        runtime = RuntimeLoop(
            AlwaysTimeoutLLMClient(),
            self.tools,
            history,
            profile_runtime_resolver=lambda name: (self._client_map(name, fallback), self.profiles[name]),
        )

        events = runtime.run(
            session_id="sess_failover_first_error",
            message="hello",
            trace_id="trace_failover_first_error",
            agent=self.agent,
            model_profile_name="openai_gpt5",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "fallback hello")
        self.assertEqual(run.tool_calls, [])
        self.assertEqual(run.attempted_profiles, ["openai_gpt5", "kimi_k2"])
        self.assertEqual(run.attempted_providers, ["openai", "kimi"])
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "kimi")

    def test_first_turn_empty_output_falls_back_before_any_tool_call(self) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient([LLMReply(final_text="fallback hello")])
        fallback.provider_name = "kimi"
        fallback.model_name = "kimi-k2"
        fallback.profile_name = "kimi_k2"
        runtime = RuntimeLoop(
            EmptyReplyLLMClient(),
            self.tools,
            history,
            profile_runtime_resolver=lambda name: (self._client_map(name, fallback), self.profiles[name]),
        )

        events = runtime.run(
            session_id="sess_failover_first_empty",
            message="hello",
            trace_id="trace_failover_first_empty",
            agent=self.agent,
            model_profile_name="openai_gpt5",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "fallback hello")
        self.assertEqual(run.tool_calls, [])
        self.assertEqual(run.failover_trigger, "EMPTY_FINAL_RESPONSE")
        self.assertEqual(run.failover_stage, "llm_first")

    def test_second_turn_provider_error_reuses_existing_tool_result(self) -> None:
        history = InMemoryRunHistory()
        primary = ToolThenTimeoutLLMClient()
        fallback = ScriptedLLMClient([LLMReply(final_text="time=2026-03-27T00:00:00Z")])
        fallback.provider_name = "kimi"
        fallback.model_name = "kimi-k2"
        fallback.profile_name = "kimi_k2"
        runtime = RuntimeLoop(
            primary,
            self.tools,
            history,
            profile_runtime_resolver=lambda name: (self._client_map(name, fallback, primary), self.profiles[name]),
        )

        events = runtime.run(
            session_id="sess_failover_second_error",
            message="what time is it",
            trace_id="trace_failover_second_error",
            agent=self.agent,
            model_profile_name="openai_gpt5",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "time=2026-03-27T00:00:00Z")
        self.assertEqual(len(run.tool_calls), 1)
        self.assertEqual(run.llm_request_count, 3)
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_second")
        self.assertEqual(fallback.requests[0].requested_tool_name, "time")
        self.assertIn("iso_time", fallback.requests[0].tool_result)

    def test_second_turn_empty_output_reuses_existing_tool_result(self) -> None:
        history = InMemoryRunHistory()
        primary = ToolThenEmptyLLMClient()
        fallback = ScriptedLLMClient([LLMReply(final_text="time=2026-03-27T00:00:00Z")])
        fallback.provider_name = "kimi"
        fallback.model_name = "kimi-k2"
        fallback.profile_name = "kimi_k2"
        runtime = RuntimeLoop(
            primary,
            self.tools,
            history,
            profile_runtime_resolver=lambda name: (self._client_map(name, fallback, primary), self.profiles[name]),
        )

        events = runtime.run(
            session_id="sess_failover_second_empty",
            message="what time is it",
            trace_id="trace_failover_second_empty",
            agent=self.agent,
            model_profile_name="openai_gpt5",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "time=2026-03-27T00:00:00Z")
        self.assertEqual(len(run.tool_calls), 1)
        self.assertEqual(run.failover_trigger, "EMPTY_FINAL_RESPONSE")
        self.assertEqual(run.failover_stage, "llm_second")
        self.assertEqual(fallback.requests[0].requested_tool_name, "time")
        self.assertIn("iso_time", fallback.requests[0].tool_result)

    @staticmethod
    def _client_map(name: str, fallback, primary=None):
        if name == "kimi_k2":
            return fallback
        if primary is not None:
            return primary
        return AlwaysTimeoutLLMClient()


if __name__ == "__main__":
    unittest.main()
