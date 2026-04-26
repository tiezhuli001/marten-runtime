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


class SessionResumeToolFallbackLLMClient:
    provider_name = "minimax"
    model_name = "MiniMax-M2.5"
    profile_name = "minimax_m25"

    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        return LLMReply(
            tool_name="session",
            tool_payload={
                "action": "resume",
                "session_id": "sess_dcce8f9c",
                "finalize_response": True,
            },
        )


class SessionListThenSpawnFallbackLLMClient:
    provider_name = "minimax"
    model_name = "MiniMax-M2.5"
    profile_name = "minimax_m25"

    def __init__(self) -> None:
        self.requests = []
        self.calls = 0

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        self.calls += 1
        if self.calls == 1:
            return LLMReply(tool_name="session", tool_payload={"action": "list"})
        return LLMReply(
            tool_name="spawn_subagent",
            tool_payload={
                "task": "查询 tiezhuli001/codex-skills 最近一次提交时间",
                "label": "github-last-commit",
                "tool_profile": "standard",
                "notify_on_finish": True,
                "finalize_response": True,
            },
        )


class SpawnAcceptanceThenSpawnFallbackLLMClient:
    provider_name = "minimax"
    model_name = "MiniMax-M2.5"
    profile_name = "minimax_m25"

    def __init__(self) -> None:
        self.requests = []
        self.calls = 0

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        self.calls += 1
        if self.calls == 1:
            return LLMReply(final_text="已受理，子 agent 正在后台执行，完成后会通知你结果。")
        return LLMReply(
            tool_name="spawn_subagent",
            tool_payload={
                "task": "查询 tiezhuli001/codex-skills 最近一次提交时间",
                "label": "github-last-commit",
                "tool_profile": "standard",
                "notify_on_finish": True,
                "finalize_response": True,
            },
        )


class AlwaysTimeoutKimiLLMClient:
    provider_name = "kimi"
    model_name = "kimi-k2"
    profile_name = "kimi_k2"

    def complete(self, request):  # noqa: ANN001
        raise TimeoutError("upstream timeout")


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

    def test_second_turn_empty_output_finalizes_locally_then_reuses_existing_tool_result(
        self,
    ) -> None:
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
        self.assertIn("现在是UTC", events[-1].payload["text"])
        self.assertNotIn("本次请求共发生", events[-1].payload["text"])
        self.assertEqual(len(run.tool_calls), 1)
        self.assertEqual(run.llm_request_count, 3)
        self.assertIsNone(run.failover_trigger)
        self.assertIsNone(run.failover_stage)
        self.assertEqual(run.final_provider_ref, "openai")
        self.assertEqual(fallback.requests, [])

    def test_failover_skips_unavailable_fallback_profile_and_uses_next_available(self) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient([LLMReply(final_text="fallback via minimax")])
        fallback.provider_name = "minimax"
        fallback.model_name = "MiniMax-M2.5"
        fallback.profile_name = "minimax_m25"
        profiles = {
            "openai_gpt5": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["kimi_k2", "minimax_m25"],
                tokenizer_family="openai_o200k",
            ),
            "kimi_k2": ModelProfile(
                provider_ref="kimi",
                model="kimi-k2",
                tokenizer_family="openai_o200k",
            ),
            "minimax_m25": ModelProfile(
                provider_ref="minimax",
                model="MiniMax-M2.5",
                tokenizer_family="openai_o200k",
            ),
        }

        def resolver(name: str):
            if name == "kimi_k2":
                raise ValueError("missing_llm_api_key:KIMI_API_KEY")
            if name == "minimax_m25":
                return fallback, profiles[name]
            return AlwaysTimeoutLLMClient(), profiles[name]

        runtime = RuntimeLoop(
            AlwaysTimeoutLLMClient(),
            self.tools,
            history,
            profile_runtime_resolver=resolver,
        )

        events = runtime.run(
            session_id="sess_failover_skip_unavailable",
            message="hello",
            trace_id="trace_failover_skip_unavailable",
            agent=self.agent,
            model_profile_name="openai_gpt5",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "fallback via minimax")
        self.assertEqual(run.attempted_profiles, ["openai_gpt5", "kimi_k2", "minimax_m25"])
        self.assertEqual(run.attempted_providers, ["openai", "minimax"])
        self.assertEqual(
            run.failover_skipped_profiles,
            [
                {
                    "profile_name": "kimi_k2",
                    "reason": "missing_llm_api_key:KIMI_API_KEY",
                }
            ],
        )
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "minimax")

    def test_failover_tries_later_primary_fallback_after_first_resolved_fallback_errors(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        minimax = ScriptedLLMClient([LLMReply(final_text="fallback via minimax")])
        minimax.provider_name = "minimax"
        minimax.model_name = "MiniMax-M2.5"
        minimax.profile_name = "minimax_m25"
        profiles = {
            "openai_gpt5": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["kimi_k2", "minimax_m25"],
                tokenizer_family="openai_o200k",
            ),
            "kimi_k2": ModelProfile(
                provider_ref="kimi",
                model="kimi-k2",
                tokenizer_family="openai_o200k",
            ),
            "minimax_m25": ModelProfile(
                provider_ref="minimax",
                model="MiniMax-M2.5",
                tokenizer_family="openai_o200k",
            ),
        }

        def resolver(name: str):
            if name == "kimi_k2":
                return AlwaysTimeoutKimiLLMClient(), profiles[name]
            if name == "minimax_m25":
                return minimax, profiles[name]
            return AlwaysTimeoutLLMClient(), profiles[name]

        runtime = RuntimeLoop(
            AlwaysTimeoutLLMClient(),
            self.tools,
            history,
            profile_runtime_resolver=resolver,
        )

        events = runtime.run(
            session_id="sess_failover_later_primary_fallback",
            message="hello",
            trace_id="trace_failover_later_primary_fallback",
            agent=self.agent,
            model_profile_name="openai_gpt5",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "fallback via minimax")
        self.assertEqual(run.attempted_profiles, ["openai_gpt5", "kimi_k2", "minimax_m25"])
        self.assertEqual(run.attempted_providers, ["openai", "kimi", "minimax"])
        self.assertEqual(run.failover_trigger, "PROVIDER_TIMEOUT")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "minimax")

    def test_first_turn_failover_accepts_real_session_transition_from_fallback_provider(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "session",
            lambda payload: {
                "action": payload["action"],
                "transition": {
                    "mode": "switched",
                    "binding_changed": True,
                    "source_session_id": "sess_failover_session_switch",
                    "target_session_id": payload["session_id"],
                    "compaction_attempted": False,
                    "compaction_succeeded": False,
                    "compaction_reason": None,
                },
                "session": {
                    "session_id": payload["session_id"],
                    "session_title": "排查 Feishu 输出",
                    "session_preview": "切换到问题会话继续排查",
                    "message_count": 72,
                    "state": "running",
                    "created_at": "2026-04-19T15:30:41+00:00",
                },
            },
        )
        history = InMemoryRunHistory()
        fallback = SessionResumeToolFallbackLLMClient()
        profiles = {
            "openai_gpt5": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["minimax_m25"],
                tokenizer_family="openai_o200k",
            ),
            "minimax_m25": ModelProfile(
                provider_ref="minimax",
                model="MiniMax-M2.5",
                tokenizer_family="openai_o200k",
            ),
        }
        runtime = RuntimeLoop(
            AlwaysTimeoutLLMClient(),
            tools,
            history,
            profile_runtime_resolver=lambda name: (
                fallback if name == "minimax_m25" else AlwaysTimeoutLLMClient(),
                profiles[name],
            ),
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_failover_session_switch",
            message="切换到sess_dcce8f9c",
            trace_id="trace_failover_session_switch",
            agent=agent,
            model_profile_name="openai_gpt5",
            tokenizer_family="openai_o200k",
        )

        self.assertIn("已切换到会话 `sess_dcce8f9c`", events[-1].payload["text"])
        self.assertEqual(len(fallback.requests), 1)
        self.assertIsNone(fallback.requests[0].requested_tool_name)
        self.assertEqual(fallback.requests[0].requested_tool_payload, {})
        run = history.get(events[-1].run_id)
        self.assertEqual(run.tool_calls[0]["tool_name"], "session")
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "minimax")

    def test_first_turn_failover_recovers_after_wrong_session_list_from_fallback_provider(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "session",
            lambda payload: {
                "action": "list",
                "count": 1,
                "items": [
                    {
                        "session_id": "sess_dcce8f9c",
                        "session_title": "排查 Feishu 输出",
                        "message_count": 72,
                        "state": "running",
                    }
                ],
            },
        )
        tools.register(
            "spawn_subagent",
            lambda payload: {
                "ok": True,
                "status": "accepted",
                "task_id": "task_spawn_ack",
                "child_session_id": "sess_child_ack",
                "effective_tool_profile": payload.get("tool_profile", "standard"),
                "queue_state": "running",
            },
        )
        history = InMemoryRunHistory()
        fallback = SessionListThenSpawnFallbackLLMClient()
        profiles = {
            "openai_gpt5": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["minimax_m25"],
                tokenizer_family="openai_o200k",
            ),
            "minimax_m25": ModelProfile(
                provider_ref="minimax",
                model="MiniMax-M2.5",
                tokenizer_family="openai_o200k",
            ),
        }
        runtime = RuntimeLoop(
            AlwaysTimeoutLLMClient(),
            tools,
            history,
            profile_runtime_resolver=lambda name: (
                fallback if name == "minimax_m25" else AlwaysTimeoutLLMClient(),
                profiles[name],
            ),
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session", "spawn_subagent"],
        )

        events = runtime.run(
            session_id="sess_failover_wrong_session_list_recover",
            message="开启子代理查询 github 上 tiezhuli001/codex-skills 最近一次提交是什么时候",
            trace_id="trace_failover_wrong_session_list_recover",
            agent=agent,
            model_profile_name="openai_gpt5",
            tokenizer_family="openai_o200k",
        )

        self.assertEqual(events[-1].payload["text"], "已受理，子 agent 正在后台执行，完成后会通知你结果。")
        self.assertEqual(len(fallback.requests), 2)
        self.assertEqual(fallback.requests[1].requested_tool_name, "session")
        self.assertEqual(fallback.requests[1].requested_tool_payload, {"action": "list"})
        run = history.get(events[-1].run_id)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["session", "spawn_subagent"])
        self.assertEqual(run.llm_request_count, 3)
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "minimax")

    def test_first_turn_failover_repairs_unbacked_spawn_acceptance_from_fallback_provider(
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
                "effective_tool_profile": payload.get("tool_profile", "standard"),
                "queue_state": "running",
            },
        )
        history = InMemoryRunHistory()
        fallback = SpawnAcceptanceThenSpawnFallbackLLMClient()
        profiles = {
            "openai_gpt5": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["minimax_m25"],
                tokenizer_family="openai_o200k",
            ),
            "minimax_m25": ModelProfile(
                provider_ref="minimax",
                model="MiniMax-M2.5",
                tokenizer_family="openai_o200k",
            ),
        }
        runtime = RuntimeLoop(
            AlwaysTimeoutLLMClient(),
            tools,
            history,
            profile_runtime_resolver=lambda name: (
                fallback if name == "minimax_m25" else AlwaysTimeoutLLMClient(),
                profiles[name],
            ),
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["spawn_subagent"],
        )

        events = runtime.run(
            session_id="sess_failover_spawn_contract_repair",
            message="开启子代理查询 github 上 tiezhuli001/codex-skills 最近一次提交是什么时候",
            trace_id="trace_failover_spawn_contract_repair",
            agent=agent,
            model_profile_name="openai_gpt5",
            tokenizer_family="openai_o200k",
        )

        self.assertEqual(events[-1].payload["text"], "已受理，子 agent 正在后台执行，完成后会通知你结果。")
        self.assertEqual(len(fallback.requests), 2)
        self.assertEqual(fallback.requests[1].request_kind, "contract_repair")
        self.assertIsNone(fallback.requests[1].requested_tool_name)
        self.assertEqual(
            fallback.requests[1].invalid_final_text,
            "已受理，子 agent 正在后台执行，完成后会通知你结果。",
        )
        run = history.get(events[-1].run_id)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["spawn_subagent"])
        self.assertEqual(run.llm_request_count, 3)
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_reason, "invalid_first_turn_finalization_contract")
        self.assertEqual(run.contract_repair_attempt_count, 1)
        self.assertEqual(run.contract_repair_outcome, "tool_call")
        self.assertEqual(run.contract_repair_selected_tool, "spawn_subagent")
        self.assertEqual(run.contract_repair_provider_ref, "minimax")
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "minimax")

    @staticmethod
    def _client_map(name: str, fallback, primary=None):
        if name == "kimi_k2":
            return fallback
        if primary is not None:
            return primary
        return AlwaysTimeoutLLMClient()


if __name__ == "__main__":
    unittest.main()
