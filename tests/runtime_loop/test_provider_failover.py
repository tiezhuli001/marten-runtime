import unittest

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.config.models_loader import ModelProfile
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.registry import ToolRegistry
from tests.support.finalization_contracts import contracted_final_reply


class AlwaysTimeoutLLMClient:
    provider_name = "openai"
    model_name = "gpt-5.4"
    profile_name = "openai_gpt_5_4"

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("provider_transport_error:connection reset")


class Gpt5ChatFallbackTimeoutLLMClient:
    provider_name = "openai"
    model_name = "gpt-5.4"
    profile_name = "openai_gpt_5_4"

    class Provider:
        supports_responses_api = False
        supports_chat_completions = True

    provider = Provider()

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("provider_transport_error:connection reset")


class EmptyReplyLLMClient:
    provider_name = "openai"
    model_name = "gpt-5.4"
    profile_name = "openai_gpt_5_4"

    def complete(self, request):  # noqa: ANN001
        return contracted_final_reply("")


class ToolThenTimeoutLLMClient:
    provider_name = "openai"
    model_name = "gpt-5.4"
    profile_name = "openai_gpt_5_4"

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
    profile_name = "openai_gpt_5_4"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request):  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            return LLMReply(tool_name="time", tool_payload={"timezone": "UTC"})
        return contracted_final_reply("")


class ToolThenRetryableSummaryThenTimeoutLLMClient:
    provider_name = "openai"
    model_name = "gpt-5.4"
    profile_name = "openai_gpt_5_4"

    def __init__(self, summary_text: str) -> None:
        self.calls = 0
        self.summary_text = summary_text

    def complete(self, request):  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            return LLMReply(
                tool_name="mcp",
                tool_payload={
                    "action": "call",
                    "server_id": "github",
                    "tool_name": "get_file_contents",
                    "arguments": {
                        "owner": "tiezhuli001",
                        "repo": "marten-runtime",
                        "path": "README.md",
                    },
                },
            )
        if self.calls == 2:
            return LLMReply(final_text=self.summary_text)
        raise TimeoutError("upstream timeout")


class SessionResumeToolFallbackLLMClient:
    provider_name = "minimax"
    model_name = "MiniMax-M2.5"
    profile_name = "minimax_m2_7_highspeed"

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
    profile_name = "minimax_m2_7_highspeed"

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
    profile_name = "minimax_m2_7_highspeed"

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
        self.tools.register(
            "time",
            lambda payload: {
                "timezone": str(payload.get("timezone") or "UTC"),
                "iso_time": "2026-03-27T00:00:00+00:00",
                "ok": True,
            },
        )
        self.agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            allowed_tools=["time"],
        )
        self.profiles = {
            "openai_gpt_5_4": ModelProfile(
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
        fallback = ScriptedLLMClient([contracted_final_reply("fallback hello")])
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
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "fallback hello")
        self.assertEqual(run.tool_calls, [])
        self.assertEqual(run.attempted_profiles, ["openai_gpt_5_4", "kimi_k2"])
        self.assertEqual(run.attempted_providers, ["openai", "kimi"])
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "kimi")
        self.assertEqual(run.provider_error_count, 1)
        self.assertEqual(run.provider_calls[0]["final_error_code"], "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.provider_calls[0]["provider_name"], "openai")
        self.assertEqual(run.provider_calls[0]["profile_name"], "openai_gpt_5_4")
        self.assertEqual(run.provider_calls[0]["timeout_seconds"], 20)
        self.assertEqual(run.provider_calls[0]["error_kind"], "transient")

    def test_first_turn_provider_error_records_gpt_5_chat_fallback_timeout(self) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient([contracted_final_reply("fallback hello")])
        fallback.provider_name = "kimi"
        fallback.model_name = "kimi-k2"
        fallback.profile_name = "kimi_k2"
        runtime = RuntimeLoop(
            Gpt5ChatFallbackTimeoutLLMClient(),
            self.tools,
            history,
            profile_runtime_resolver=lambda name: (self._client_map(name, fallback), self.profiles[name]),
        )

        events = runtime.run(
            session_id="sess_failover_gpt5_chat_fallback",
            message="hello",
            trace_id="trace_failover_gpt5_chat_fallback",
            agent=self.agent,
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "fallback hello")
        self.assertEqual(run.provider_calls[0]["timeout_seconds"], 40)
        self.assertEqual(run.provider_calls[0]["error_kind"], "transient")

    def test_first_turn_empty_output_falls_back_before_any_tool_call(self) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient([contracted_final_reply("fallback hello")])
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
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "fallback hello")
        self.assertEqual(run.tool_calls, [])
        self.assertEqual(run.failover_trigger, "EMPTY_FINAL_RESPONSE")
        self.assertEqual(run.failover_stage, "llm_first")

    def test_first_turn_failover_repairs_plain_followup_continuation_contract(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient(
            [
                LLMReply(final_text="已继续跟进部署告警排查任务。"),
                contracted_final_reply("已继续跟进部署告警排查任务。"),
            ]
        )
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
            session_id="sess_failover_plain_followup",
            message="继续跟进上一轮那个部署告警排查任务。",
            trace_id="trace_failover_plain_followup",
            agent=self.agent,
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
            session_messages=[
                SessionMessage.user("先简单打个招呼，后面我还要继续跟进部署告警排查任务。"),
                SessionMessage.assistant("你好，收到。后面可以继续跟进部署告警排查任务。"),
            ],
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "已继续跟进部署告警排查任务。")
        self.assertEqual(len(fallback.requests), 2)
        self.assertEqual(run.tool_calls, [])
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_outcome, "final_text")
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "kimi")

    def test_first_turn_failover_repairs_plain_compaction_continuation_contract(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient(
            [
                LLMReply(final_text="压缩后继续完成当前任务。"),
                contracted_final_reply("压缩后继续完成当前任务。"),
            ]
        )
        fallback.provider_name = "kimi"
        fallback.model_name = "kimi-k2"
        fallback.profile_name = "kimi_k2"
        compaction_agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            allowed_tools=["mcp", "runtime", "session", "skill"],
        )
        runtime = RuntimeLoop(
            AlwaysTimeoutLLMClient(),
            self.tools,
            history,
            profile_runtime_resolver=lambda name: (self._client_map(name, fallback), self.profiles[name]),
        )

        events = runtime.run(
            session_id="sess_failover_plain_compaction",
            message="在压缩后的上下文里继续执行。",
            trace_id="trace_failover_plain_compaction",
            agent=compaction_agent,
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
            compacted_context=CompactedContext(
                compact_id="cmp_failover_plain_compaction",
                session_id="sess_failover_plain_compaction",
                summary_text=(
                    "当前任务：日报同步告警排查。\n"
                    "当前未完成事项：补失败摘要、核对卡片渲染差异、写出下一步动作。\n"
                    "继续时直接沿着这三步推进，不要要求用户重复任务名。"
                ),
                source_message_range=[0, 40],
                preserved_tail_user_turns=1,
                trigger_kind="context_pressure_proactive",
            ),
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "压缩后继续完成当前任务。")
        self.assertEqual(len(fallback.requests), 2)
        self.assertEqual(run.tool_calls, [])
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_outcome, "final_text")
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "kimi")

    def test_first_turn_failover_repairs_plain_memory_readback_contract(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient(
            [
                LLMReply(final_text="当前偏好：以后始终用中文回复。"),
                contracted_final_reply("当前偏好：以后始终用中文回复。"),
            ]
        )
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
            session_id="sess_failover_memory_readback",
            message="读取刚才记住的偏好。",
            trace_id="trace_failover_memory_readback",
            agent=self.agent,
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
            memory_text="User memory:\n# MEMORY\n\n## preferences\n- 以后始终用中文回复。",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "当前偏好：以后始终用中文回复。")
        self.assertEqual(len(fallback.requests), 2)
        self.assertEqual(run.tool_calls, [])
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_outcome, "final_text")
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "kimi")

    def test_first_turn_failover_repairs_plain_safe_self_intro_contract(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient(
            [
                LLMReply(final_text="我是 marten-runtime 中的默认主执行代理，负责处理当前会话里的任务。"),
                contracted_final_reply("我是 marten-runtime 中的默认主执行代理，负责处理当前会话里的任务。"),
            ]
        )
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
            session_id="sess_failover_plain_intro",
            message="用一句话介绍你自己。",
            trace_id="trace_failover_plain_intro",
            agent=self.agent,
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(
            events[-1].payload["text"],
            "我是 marten-runtime 中的默认主执行代理，负责处理当前会话里的任务。",
        )
        self.assertEqual(len(fallback.requests), 2)
        self.assertEqual(run.tool_calls, [])
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_outcome, "final_text")
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "kimi")

    def test_first_turn_failover_repairs_plain_memory_rule_recap_contract(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient(
            [
                LLMReply(final_text="周报默认先给结论后给细节。"),
                contracted_final_reply("周报默认先给结论后给细节。"),
            ]
        )
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
            session_id="sess_failover_memory_rule_recap",
            message="把我刚才设定的周报顺序完整复述一遍，明确先后顺序。",
            trace_id="trace_failover_memory_rule_recap",
            agent=self.agent,
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
            memory_text="User memory:\n# MEMORY\n\n## preferences\n- 周报默认先给结论后给细节。",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "周报默认先给结论后给细节。")
        self.assertEqual(len(fallback.requests), 2)
        self.assertEqual(run.tool_calls, [])
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_outcome, "final_text")
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "kimi")

    def test_first_turn_failover_repairs_plain_memory_output_policy_contract(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient(
            [
                LLMReply(final_text="以后日报先给风险，再给结论。"),
                contracted_final_reply("以后日报先给风险，再给结论。"),
            ]
        )
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
            session_id="sess_failover_memory_output_policy",
            message="现在日报该怎么组织？",
            trace_id="trace_failover_memory_output_policy",
            agent=self.agent,
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
            memory_text="User memory:\n# MEMORY\n\n## preferences\n- 以后日报先给风险，再给结论。",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "以后日报先给风险，再给结论。")
        self.assertEqual(len(fallback.requests), 2)
        self.assertEqual(run.tool_calls, [])
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_outcome, "final_text")
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "kimi")

    def test_first_turn_failover_repairs_plain_subagent_completion_contract(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient(
            [
                LLMReply(final_text="子任务已梳理仓库结构，结论是当前可用 MCP 服务共 0 个。"),
                contracted_final_reply("子任务已梳理仓库结构，结论是当前可用 MCP 服务共 0 个。"),
            ]
        )
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
            session_id="sess_failover_subagent_completion_recap",
            message="子任务完成了吗？直接给我一句中文摘要，明确它梳理的对象和结论。",
            trace_id="trace_failover_subagent_completion_recap",
            agent=self.agent,
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
            session_messages=[
                SessionMessage.system(
                    "subagent task completed: 仓库结构梳理\nsummary: 当前可用 MCP 服务共 0 个。"
                )
            ],
            recent_tool_outcome_summaries=[
                {
                    "summary_text": "子任务 仓库结构梳理 已完成，结论是当前可用 MCP 服务共 0 个。",
                    "keep_next_turn": True,
                    "volatile": False,
                    "tool_name": "spawn_subagent",
                }
            ],
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(
            events[-1].payload["text"],
            "子任务已梳理仓库结构，结论是当前可用 MCP 服务共 0 个。",
        )
        self.assertEqual(len(fallback.requests), 2)
        self.assertEqual(run.tool_calls, [])
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_outcome, "final_text")
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "kimi")

    def test_first_turn_failover_repairs_plain_subagent_absorbed_result_contract(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        fallback = ScriptedLLMClient(
            [
                LLMReply(final_text="最近提交主要集中在评测和报告。"),
                contracted_final_reply("最近提交主要集中在评测和报告。"),
            ]
        )
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
            session_id="sess_failover_subagent_absorbed_result",
            message="直接告诉我你吸收后的结论，明确最近提交主要在改什么。",
            trace_id="trace_failover_subagent_absorbed_result",
            agent=self.agent,
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
            session_messages=[
                SessionMessage.system(
                    "subagent task completed: recent-commit-review\nsummary: 最近提交主要集中在评测和报告。"
                )
            ],
            recent_tool_outcome_summaries=[
                {
                    "summary_text": "子任务 recent-commit-review 已完成，结论是最近提交主要集中在评测和报告。",
                    "keep_next_turn": True,
                    "volatile": False,
                    "tool_name": "spawn_subagent",
                }
            ],
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "最近提交主要集中在评测和报告。")
        self.assertEqual(len(fallback.requests), 2)
        self.assertEqual(run.tool_calls, [])
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_outcome, "final_text")
        self.assertEqual(run.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(run.failover_stage, "llm_first")
        self.assertEqual(run.final_provider_ref, "kimi")

    def test_second_turn_provider_error_reuses_existing_tool_result(self) -> None:
        history = InMemoryRunHistory()
        primary = ToolThenTimeoutLLMClient()
        fallback = ScriptedLLMClient([contracted_final_reply("现在是UTC 2026年3月27日 00:00")])
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
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "现在是UTC 2026年3月27日 00:00")
        self.assertEqual(len(run.tool_calls), 1)

    def test_finalization_retry_provider_timeout_reuses_retryable_invalid_summary(self) -> None:
        history = InMemoryRunHistory()
        richer_summary = (
            "已查看 `tiezhuli001/marten-runtime` 默认分支的 `README.md`。"
            "主要章节包括快速开始、离线评测、仓库结构。"
        )
        primary = ToolThenRetryableSummaryThenTimeoutLLMClient(richer_summary)
        fallback = AlwaysTimeoutKimiLLMClient()
        tools = ToolRegistry()
        tools.register(
            "mcp",
            lambda payload: {
                "ok": True,
                "action": "call",
                "server_id": "github",
                "tool_name": "get_file_contents",
                "arguments": dict(payload.get("arguments") or {}),
                "payload": {
                    "owner": "tiezhuli001",
                    "repo": "marten-runtime",
                    "path": "README.md",
                },
                "content": [
                    {
                        "type": "text",
                        "text": "successfully downloaded text file (SHA: deadbeef)",
                    }
                ],
                "result_text": "successfully downloaded text file (SHA: deadbeef)",
            },
        )
        runtime = RuntimeLoop(
            primary,
            tools,
            history,
            profile_runtime_resolver=lambda name: (
                self._client_map(name, fallback, primary),
                self.profiles[name],
            ),
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_failover_finalization_retry_timeout",
            message="查看当前任务所指仓库的 README 结构，概括主要章节与组织方式，保留可复述摘要。",
            trace_id="trace_failover_finalization_retry_timeout",
            agent=agent,
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], richer_summary)
        self.assertEqual(run.finalization.assessment, "accepted")
        self.assertTrue(run.finalization.retry_triggered)
        self.assertTrue(run.finalization.recovered_from_fragments)
        self.assertEqual(run.finalization.invalid_final_text, richer_summary)
        self.assertEqual(run.llm_request_count, 4)
        self.assertEqual(run.failover_trigger, "PROVIDER_TIMEOUT")
        self.assertEqual(run.failover_stage, "llm_second")
        self.assertEqual(run.attempted_profiles, ["openai_gpt_5_4", "kimi_k2"])
        self.assertEqual(run.attempted_providers, ["openai", "kimi"])

    def test_second_turn_empty_output_finalizes_locally_then_reuses_existing_tool_result(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        primary = ToolThenEmptyLLMClient()
        fallback = ScriptedLLMClient([contracted_final_reply("现在是UTC 2026年3月27日 00:00")])
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
            model_profile_name="openai_gpt_5_4",
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
        fallback = ScriptedLLMClient([contracted_final_reply("fallback via minimax")])
        fallback.provider_name = "minimax"
        fallback.model_name = "MiniMax-M2.5"
        fallback.profile_name = "minimax_m2_7_highspeed"
        profiles = {
            "openai_gpt_5_4": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["kimi_k2", "minimax_m2_7_highspeed"],
                tokenizer_family="openai_o200k",
            ),
            "kimi_k2": ModelProfile(
                provider_ref="kimi",
                model="kimi-k2",
                tokenizer_family="openai_o200k",
            ),
            "minimax_m2_7_highspeed": ModelProfile(
                provider_ref="minimax",
                model="MiniMax-M2.5",
                tokenizer_family="openai_o200k",
            ),
        }

        def resolver(name: str):
            if name == "kimi_k2":
                raise ValueError("missing_llm_api_key:KIMI_API_KEY")
            if name == "minimax_m2_7_highspeed":
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
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "fallback via minimax")
        self.assertEqual(run.attempted_profiles, ["openai_gpt_5_4", "kimi_k2", "minimax_m2_7_highspeed"])
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
        minimax = ScriptedLLMClient([contracted_final_reply("fallback via minimax")])
        minimax.provider_name = "minimax"
        minimax.model_name = "MiniMax-M2.5"
        minimax.profile_name = "minimax_m2_7_highspeed"
        profiles = {
            "openai_gpt_5_4": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["kimi_k2", "minimax_m2_7_highspeed"],
                tokenizer_family="openai_o200k",
            ),
            "kimi_k2": ModelProfile(
                provider_ref="kimi",
                model="kimi-k2",
                tokenizer_family="openai_o200k",
            ),
            "minimax_m2_7_highspeed": ModelProfile(
                provider_ref="minimax",
                model="MiniMax-M2.5",
                tokenizer_family="openai_o200k",
            ),
        }

        def resolver(name: str):
            if name == "kimi_k2":
                return AlwaysTimeoutKimiLLMClient(), profiles[name]
            if name == "minimax_m2_7_highspeed":
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
            model_profile_name="openai_gpt_5_4",
            tokenizer_family="openai_o200k",
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(events[-1].payload["text"], "fallback via minimax")
        self.assertEqual(run.attempted_profiles, ["openai_gpt_5_4", "kimi_k2", "minimax_m2_7_highspeed"])
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
            "openai_gpt_5_4": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["minimax_m2_7_highspeed"],
                tokenizer_family="openai_o200k",
            ),
            "minimax_m2_7_highspeed": ModelProfile(
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
                fallback if name == "minimax_m2_7_highspeed" else AlwaysTimeoutLLMClient(),
                profiles[name],
            ),
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_failover_session_switch",
            message="切换到sess_dcce8f9c",
            trace_id="trace_failover_session_switch",
            agent=agent,
            model_profile_name="openai_gpt_5_4",
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
            "openai_gpt_5_4": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["minimax_m2_7_highspeed"],
                tokenizer_family="openai_o200k",
            ),
            "minimax_m2_7_highspeed": ModelProfile(
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
                fallback if name == "minimax_m2_7_highspeed" else AlwaysTimeoutLLMClient(),
                profiles[name],
            ),
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            allowed_tools=["session", "spawn_subagent"],
        )

        events = runtime.run(
            session_id="sess_failover_wrong_session_list_recover",
            message="开启子代理查询 github 上 tiezhuli001/codex-skills 最近一次提交是什么时候",
            trace_id="trace_failover_wrong_session_list_recover",
            agent=agent,
            model_profile_name="openai_gpt_5_4",
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
            "openai_gpt_5_4": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["minimax_m2_7_highspeed"],
                tokenizer_family="openai_o200k",
            ),
            "minimax_m2_7_highspeed": ModelProfile(
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
                fallback if name == "minimax_m2_7_highspeed" else AlwaysTimeoutLLMClient(),
                profiles[name],
            ),
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            allowed_tools=["spawn_subagent"],
        )

        events = runtime.run(
            session_id="sess_failover_spawn_contract_repair",
            message="开启子代理查询 github 上 tiezhuli001/codex-skills 最近一次提交是什么时候",
            trace_id="trace_failover_spawn_contract_repair",
            agent=agent,
            model_profile_name="openai_gpt_5_4",
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
