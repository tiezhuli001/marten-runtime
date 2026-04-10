import unittest
import threading
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from marten_runtime.automation.models import AutomationJob
from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.automation.store import AutomationStore
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.config.models_loader import ModelProfile
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import (
    LLMReply,
    ScriptedLLMClient,
    estimate_request_tokens,
)
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.runtime.usage_models import (
    ProviderCallDiagnostics,
    ProviderCallAttempt,
)
from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compaction_trigger import build_compaction_settings
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.self_improve.models import LessonCandidate, SystemLesson
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.skills.service import SkillService
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.tools.builtins.automation_tool import run_automation_tool
from marten_runtime.tools.builtins.self_improve_tool import (
    run_delete_lesson_candidate_tool,
    run_list_lesson_candidates_tool,
    run_self_improve_tool,
)
from marten_runtime.tools.builtins.skill_tool import run_skill_tool
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.builtins.runtime_tool import run_runtime_tool
from marten_runtime.tools.registry import ToolRegistry, ToolSnapshot


class FailingLLMClient:
    provider_name = "failing"
    model_name = "failing-local"

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("provider_transport_error:connection reset")


class FirstSuccessThenFailingLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def __init__(self, first_reply: LLMReply) -> None:
        self._first_reply = first_reply
        self._calls = 0

    def complete(self, request):  # noqa: ANN001
        self._calls += 1
        if self._calls == 1:
            return self._first_reply
        raise RuntimeError("provider_transport_error:connection reset")


class BrokenInternalLLMClient:
    provider_name = "broken"
    model_name = "broken-local"

    def complete(self, request):  # noqa: ANN001
        raise ValueError("boom")


class AuthFailingLLMClient:
    provider_name = "auth-failing"
    model_name = "auth-failing-local"

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("provider_http_error:401:unauthorized")


class BrokenToolLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def complete(self, request):  # noqa: ANN001
        return LLMReply(tool_name="broken_tool", tool_payload={"value": "x"})


class FirstSuccessThenDisallowedToolLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def __init__(self, first_reply: LLMReply) -> None:
        self._first_reply = first_reply
        self._calls = 0

    def complete(self, request):  # noqa: ANN001
        self._calls += 1
        if self._calls == 1:
            return self._first_reply
        return LLMReply(tool_name="time", tool_payload={"timezone": "UTC"})


class ObservedLLMClient:
    provider_name = "observed"
    model_name = "observed-local"

    def __init__(self) -> None:
        self.last_call_diagnostics = ProviderCallDiagnostics(
            request_kind="interactive",
            timeout_seconds=20,
            max_attempts=2,
            completed=True,
            final_error_code=None,
            attempts=[
                ProviderCallAttempt(
                    attempt=1,
                    elapsed_ms=123,
                    ok=True,
                    error_code=None,
                    error_detail=None,
                    retryable=False,
                )
            ],
        )

    def complete(self, request):  # noqa: ANN001
        return LLMReply(final_text="ok")


class PromptTooLongThenSuccessLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def __init__(self) -> None:
        self.requests = []
        self._calls = 0

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("provider_http_error:400:prompt too long")
        return LLMReply(final_text="recovered")


class ConcurrentInterleavingLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def complete(self, request):  # noqa: ANN001
        if request.message == "first":
            if request.tool_result is None:
                return LLMReply(tool_name="time", tool_payload={})
            return LLMReply(final_text="done-first")
        return LLMReply(final_text="done-second")


class RuntimeLoopTests(unittest.TestCase):
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
            side_effect=[10.0, 11.0, 11.12, 11.25, 11.25],
        ):
            events = runtime.run(
                session_id="sess_1", message="hello", trace_id="trace_plain"
            )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[0].trace_id, "trace_plain")
        self.assertEqual(events[0].run_id, events[1].run_id)
        self.assertEqual(events[1].payload["text"], "hello")
        self.assertEqual(llm.requests[0].available_tools, [])

        run = history.get(events[0].run_id)
        self.assertEqual(run.trace_id, "trace_plain")
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.delivery_status, "final")
        self.assertEqual(run.timings.llm_first_ms, 119)
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

    def test_compact_path_preserves_system_prompt_and_capability_scaffolding(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="hello again")])
        runtime = RuntimeLoop(llm, tools, history)

        runtime.run(
            session_id="sess_compact_scaffold",
            message="继续执行",
            trace_id="trace_compact_scaffold",
            system_prompt="You are marten-runtime.",
            session_messages=[
                SessionMessage.user("old 1"),
                SessionMessage.assistant("old 1 result"),
                SessionMessage.user("recent 1"),
                SessionMessage.assistant("recent 1 result"),
                SessionMessage.user("继续执行"),
            ],
            skill_heads_text="Visible skills:\n- repo_helper: repo assistance",
            capability_catalog_text="Capabilities:\n- time",
            compacted_context=CompactedContext(
                compact_id="cmp_scaffold",
                session_id="sess_compact_scaffold",
                summary_text="当前进展：old 1 已完成。",
                source_message_range=[0, 2],
                preserved_tail_count=2,
            ),
        )

        self.assertEqual(llm.requests[0].system_prompt, "You are marten-runtime.")
        self.assertEqual(
            llm.requests[0].skill_heads_text,
            "Visible skills:\n- repo_helper: repo assistance",
        )
        self.assertEqual(
            llm.requests[0].capability_catalog_text, "Capabilities:\n- time"
        )
        self.assertEqual(llm.requests[0].available_tools, ["time"])
        self.assertIn("当前进展", llm.requests[0].compact_summary_text or "")

    def test_runtime_reactively_compacts_and_retries_after_prompt_too_long(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = PromptTooLongThenSuccessLLMClient()
        compact_llm = ScriptedLLMClient(
            [LLMReply(final_text="当前进展：历史已压缩。\n明确下一步：继续执行。")]
        )
        runtime = RuntimeLoop(llm, tools, history)
        stored = []

        events = runtime.run(
            session_id="sess_reactive",
            message="继续长线程任务",
            trace_id="trace_reactive",
            system_prompt="You are marten-runtime.",
            session_messages=[
                SessionMessage.user("历史 1"),
                SessionMessage.assistant("历史 1 完成"),
                SessionMessage.user("历史 2"),
                SessionMessage.assistant("历史 2 完成"),
                SessionMessage.user("继续长线程任务"),
            ],
            compact_llm_client=compact_llm,
            on_compacted=lambda item: stored.append(item),
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "recovered")
        self.assertEqual(len(stored), 1)
        self.assertIn("当前进展", llm.requests[-1].compact_summary_text or "")

    def test_estimator_counts_scaffolding_and_history_inputs(self) -> None:
        from marten_runtime.runtime.llm_client import LLMRequest, ConversationMessage

        estimated = estimate_request_tokens(
            LLMRequest(
                session_id="sess_estimate",
                trace_id="trace_estimate",
                message="继续处理这个问题",
                agent_id="assistant",
                app_id="example_assistant",
                system_prompt="You are marten-runtime.",
                compact_summary_text="当前进展：已完成阶段 A。",
                skill_heads_text="Visible skills:\n- repo_helper",
                capability_catalog_text="Capabilities:\n- time",
                conversation_messages=[
                    ConversationMessage(role="user", content="前情提要")
                ],
                activated_skill_bodies=["Repo helper body"],
                tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            )
        )

        self.assertGreater(estimated, 10)

    def test_runtime_proactively_compacts_when_context_pressure_exceeds_threshold(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="done after proactive compact")])
        compact_llm = ScriptedLLMClient(
            [LLMReply(final_text="当前进展：长线程已压缩。")]
        )
        runtime = RuntimeLoop(llm, tools, history)
        stored = []

        events = runtime.run(
            session_id="sess_proactive",
            message="当前轮继续",
            trace_id="trace_proactive",
            system_prompt="You are marten-runtime.",
            session_messages=[
                SessionMessage.user("旧历史 1 " + "x" * 200),
                SessionMessage.assistant("旧历史 1 完成 " + "y" * 200),
                SessionMessage.user("旧历史 2 " + "x" * 200),
                SessionMessage.assistant("旧历史 2 完成 " + "y" * 200),
                SessionMessage.user("当前轮继续"),
            ],
            compact_llm_client=compact_llm,
            on_compacted=lambda item: stored.append(item),
            compact_settings=build_compaction_settings(
                ModelProfile(
                    provider="openai",
                    model="gpt-4.1",
                    context_window_tokens=400,
                    reserve_output_tokens=50,
                    compact_trigger_ratio=0.5,
                )
            ),
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(len(stored), 1)
        self.assertIn("当前进展", llm.requests[0].compact_summary_text or "")

    def test_runtime_does_not_proactively_compact_finished_turn_without_continuation_signal(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="done without compact")])
        compact_llm = ScriptedLLMClient([LLMReply(final_text="should not compact")])
        runtime = RuntimeLoop(llm, tools, history)
        stored = []

        events = runtime.run(
            session_id="sess_no_followup",
            message="这个问题已经完成，可以结束了。",
            trace_id="trace_no_followup",
            system_prompt="You are marten-runtime.",
            session_messages=[
                SessionMessage.user("旧历史 1 " + "x" * 200),
                SessionMessage.assistant("旧历史 1 完成 " + "y" * 200),
                SessionMessage.user("旧历史 2 " + "x" * 200),
                SessionMessage.assistant("旧历史 2 完成 " + "y" * 200),
                SessionMessage.user("这个问题已经完成，可以结束了。"),
            ],
            compact_llm_client=compact_llm,
            on_compacted=lambda item: stored.append(item),
            compact_settings=build_compaction_settings(
                ModelProfile(
                    provider="openai",
                    model="gpt-4.1",
                    context_window_tokens=400,
                    reserve_output_tokens=50,
                    compact_trigger_ratio=0.5,
                )
            ),
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "done without compact")
        self.assertEqual(len(stored), 0)
        self.assertEqual(len(compact_llm.requests), 0)
        self.assertIsNone(llm.requests[0].compact_summary_text)

    def test_runtime_records_compaction_diagnostics_and_reduces_estimated_tokens_after_compaction(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="done after proactive compact")])
        compact_llm = ScriptedLLMClient(
            [LLMReply(final_text="当前进展：长线程已压缩。")]
        )
        runtime = RuntimeLoop(llm, tools, history)

        events = runtime.run(
            session_id="sess_diag_compact",
            message="下一步：继续处理剩余问题",
            trace_id="trace_diag_compact",
            system_prompt="You are marten-runtime.",
            session_messages=[
                SessionMessage.user("todo：处理 chunk 1 " + "x" * 200),
                SessionMessage.assistant("chunk 1 完成，下一步继续 " + "y" * 200),
                SessionMessage.user("风险：注意不要覆盖 system prompt " + "x" * 200),
                SessionMessage.assistant("已收到风险，继续保留脚手架 " + "y" * 200),
                SessionMessage.user("下一步：继续处理剩余问题"),
            ],
            compact_llm_client=compact_llm,
            compact_settings=build_compaction_settings(
                ModelProfile(
                    provider="openai",
                    model="gpt-4.1",
                    context_window_tokens=400,
                    reserve_output_tokens=50,
                    compact_trigger_ratio=0.5,
                )
            ),
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(run.compaction.decision, "proactive")
        self.assertTrue(run.compaction.used_compacted_context)
        self.assertIsNotNone(run.compaction.compacted_context_id)
        self.assertGreater(
            run.compaction.estimated_input_tokens_before,
            run.compaction.estimated_input_tokens_after,
        )
        self.assertEqual(run.compaction.effective_window_tokens, 350)

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

        with patch(
            "marten_runtime.runtime.loop.time.perf_counter",
            side_effect=[10.0, 11.0, 11.1, 11.2, 11.34, 12.0, 12.17, 12.5, 12.5],
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
        self.assertEqual(run.timings.llm_first_ms, 99)
        self.assertEqual(run.timings.tool_ms, 140)
        self.assertEqual(run.timings.llm_second_ms, 169)
        self.assertEqual(run.timings.total_ms, 2500)

    def test_runtime_context_status_tool_returns_user_readable_summary_for_current_run(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="runtime", tool_payload={"action": "context_status"}
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "runtime",
            lambda payload, *, tool_context=None, runtime_loop=runtime, run_history=history: (
                run_runtime_tool(
                    payload,
                    tool_context=tool_context,
                    runtime_loop=runtime_loop,
                    run_history=run_history,
                )
            ),
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["runtime"],
        )

        events = runtime.run(
            session_id="sess_runtime",
            message="当前上下文窗口多大",
            trace_id="trace_runtime",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("当前上下文使用详情", events[-1].payload["text"])
        self.assertIn("下一次请求预计输入", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 1)
        tool_result = history.get(events[-1].run_id).tool_calls[0]["tool_result"]
        self.assertTrue(tool_result["ok"])
        self.assertEqual(tool_result["action"], "context_status")
        self.assertIn("model_profile", tool_result)
        self.assertIn("context_window", tool_result)
        self.assertIn("estimated_usage", tool_result)
        self.assertIn("effective_window", tool_result)
        self.assertIn("estimate_source", tool_result)
        self.assertIn("next_request_estimate", tool_result)
        self.assertIn("last_actual_usage", tool_result)
        self.assertIn("usage_percent", tool_result)
        self.assertIn("compaction_status", tool_result)
        self.assertIn("latest_checkpoint", tool_result)
        self.assertIn("summary", tool_result)
        self.assertNotIn("advisory_threshold_tokens", tool_result)
        self.assertGreater(tool_result["context_window"], 0)
        self.assertGreater(tool_result["effective_window"], 0)
        self.assertGreater(tool_result["estimated_usage"], 0)
        self.assertEqual(
            tool_result["next_request_estimate"]["input_tokens_estimate"],
            tool_result["estimated_usage"],
        )
        run = history.get(events[-1].run_id)
        self.assertEqual(
            tool_result["current_run"]["initial_input_tokens_estimate"],
            run.initial_preflight_input_tokens_estimate,
        )
        self.assertEqual(
            tool_result["current_run"]["peak_input_tokens_estimate"],
            run.peak_preflight_input_tokens_estimate,
        )
        self.assertEqual(
            tool_result["current_run"]["peak_stage"], run.peak_preflight_stage
        )
        self.assertEqual(tool_result["current_run"]["peak_stage"], "initial_request")
        self.assertNotIn("峰值主要来自工具结果注入后", tool_result["summary"])
        self.assertEqual(run.timings.llm_second_ms, 0)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_outcome_summaries, [])

    def test_runtime_uses_llm_first_for_natural_language_context_query(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [LLMReply(tool_name="runtime", tool_payload={"action": "context_status"})]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "runtime",
            lambda payload, *, tool_context=None, runtime_loop=runtime, run_history=history: (
                run_runtime_tool(
                    payload,
                    tool_context=tool_context,
                    runtime_loop=runtime_loop,
                    run_history=run_history,
                )
            ),
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["runtime"],
        )

        events = runtime.run(
            session_id="sess_runtime_direct",
            message="现在上下文用了多少，简短一点。",
            trace_id="trace_runtime_direct",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("当前上下文使用详情", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 1)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls[0]["tool_name"], "runtime")
        self.assertEqual(
            run.tool_calls[0]["tool_payload"], {"action": "context_status"}
        )

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
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
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

    def test_runtime_uses_llm_first_for_natural_language_automation_list_query(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteAutomationStore(Path(tmpdir) / "automations.sqlite3")
            adapter = DomainDataAdapter(
                self_improve_store=SQLiteSelfImproveStore(
                    Path(tmpdir) / "self_improve.sqlite3"
                ),
                automation_store=store,
            )
            store.save(
                AutomationJob(
                    automation_id="daily_hot",
                    name="GitHub热榜推荐",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="x",
                    schedule_kind="daily",
                    schedule_expr="22:20",
                    timezone="Asia/Shanghai",
                    enabled=True,
                    delivery_channel="feishu",
                    delivery_target="chat_1",
                    skill_id="",
                )
            )
            tools = ToolRegistry()
            tools.register(
                "automation",
                lambda payload: run_automation_tool(payload, store, adapter),
            )
            history = InMemoryRunHistory()
            llm = ScriptedLLMClient(
                [
                    LLMReply(tool_name="automation", tool_payload={"action": "list"}),
                    LLMReply(final_text="当前共有 1 个定时任务"),
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
                session_id="sess_automation_direct",
                message="现在有哪些定时任务",
                trace_id="trace_automation_direct",
                agent=agent,
            )

            self.assertEqual(
                [event.event_type for event in events], ["progress", "final"]
            )
            self.assertEqual(len(llm.requests), 1)
            self.assertIn("当前共有 1 个定时任务", events[-1].payload["text"])
            self.assertIn("GitHub热榜推荐｜已启用｜22:20", events[-1].payload["text"])
            run = history.get(events[-1].run_id)
            self.assertEqual(run.llm_request_count, 1)
            self.assertEqual(run.tool_calls[0]["tool_name"], "automation")
            self.assertEqual(run.tool_calls[0]["tool_payload"], {"action": "list"})

    def test_runtime_uses_llm_first_for_natural_language_automation_detail_query(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteAutomationStore(Path(tmpdir) / "automations.sqlite3")
            adapter = DomainDataAdapter(
                self_improve_store=SQLiteSelfImproveStore(
                    Path(tmpdir) / "self_improve.sqlite3"
                ),
                automation_store=store,
            )
            store.save(
                AutomationJob(
                    automation_id="github_trending_digest_2230",
                    name="GitHub热榜推荐",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="x",
                    schedule_kind="daily",
                    schedule_expr="22:30",
                    timezone="Asia/Shanghai",
                    enabled=True,
                    delivery_channel="feishu",
                    delivery_target="chat_1",
                    skill_id="",
                )
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
                            "action": "detail",
                            "automation_id": "github_trending_digest_2230",
                        },
                    ),
                    LLMReply(final_text="任务 github_trending_digest_2230 的详情已返回"),
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
                session_id="sess_automation_detail_direct",
                message="请看下 automation_id 为 github_trending_digest_2230 的定时任务详情",
                trace_id="trace_automation_detail_direct",
                agent=agent,
            )

            self.assertEqual(
                [event.event_type for event in events], ["progress", "final"]
            )
            self.assertEqual(len(llm.requests), 1)
            self.assertIn("github_trending_digest_2230", events[-1].payload["text"])
            self.assertIn("状态：已启用", events[-1].payload["text"])
            run = history.get(events[-1].run_id)
            self.assertEqual(run.llm_request_count, 1)
            self.assertEqual(run.tool_calls[0]["tool_name"], "automation")
            self.assertEqual(
                run.tool_calls[0]["tool_payload"],
                {"action": "detail", "automation_id": "github_trending_digest_2230"},
            )

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
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
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

    def test_runtime_records_preflight_and_actual_usage_on_run(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    final_text="done",
                    usage=NormalizedUsage(
                        input_tokens=120,
                        output_tokens=30,
                        total_tokens=150,
                        provider_name="openai",
                        model_name="gpt-4.1",
                        captured_at=datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc),
                    ),
                )
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)

        events = runtime.run(
            session_id="sess_usage_run",
            message="hello",
            trace_id="trace_usage_run",
        )

        run = history.get(events[-1].run_id)
        self.assertGreater(run.preflight_input_tokens_estimate, 0)
        self.assertIn(run.preflight_estimator_kind, {"tokenizer", "rough"})
        self.assertEqual(
            run.initial_preflight_input_tokens_estimate,
            run.preflight_input_tokens_estimate,
        )
        self.assertGreaterEqual(
            run.peak_preflight_input_tokens_estimate,
            run.initial_preflight_input_tokens_estimate,
        )
        self.assertEqual(run.actual_input_tokens, 120)
        self.assertEqual(run.actual_output_tokens, 30)
        self.assertEqual(run.actual_total_tokens, 150)

    def test_runtime_records_peak_preflight_after_tool_result_injection(self) -> None:
        tools = ToolRegistry()
        tools.register(
            "big_tool",
            lambda payload: {"result_text": "X" * 4000, "tool_name": "big_tool"},
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="big_tool", tool_payload={"query": "large"}),
                LLMReply(final_text="done"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["big_tool"],
        )

        events = runtime.run(
            session_id="sess_peak_preflight",
            message="请调用工具获取大量信息",
            trace_id="trace_peak_preflight",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertGreater(run.initial_preflight_input_tokens_estimate, 0)
        self.assertGreater(
            run.peak_preflight_input_tokens_estimate,
            run.initial_preflight_input_tokens_estimate,
        )
        self.assertEqual(run.peak_preflight_stage, "tool_followup")

    def test_runtime_records_actual_peak_total_on_followup_llm_call(self) -> None:
        tools = ToolRegistry()
        tools.register(
            "big_tool",
            lambda payload: {"result_text": "X" * 4000, "tool_name": "big_tool"},
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="big_tool",
                    tool_payload={"query": "large"},
                    usage=NormalizedUsage(
                        input_tokens=2400, output_tokens=120, total_tokens=2520
                    ),
                ),
                LLMReply(
                    final_text="done",
                    usage=NormalizedUsage(
                        input_tokens=13870, output_tokens=196, total_tokens=14066
                    ),
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["big_tool"],
        )

        events = runtime.run(
            session_id="sess_peak_actual",
            message="请调用工具获取大量信息",
            trace_id="trace_peak_actual",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(run.actual_input_tokens, 13870)
        self.assertEqual(run.actual_output_tokens, 196)
        self.assertEqual(run.actual_total_tokens, 14066)
        self.assertEqual(run.actual_peak_input_tokens, 13870)
        self.assertEqual(run.actual_peak_output_tokens, 196)
        self.assertEqual(run.actual_peak_total_tokens, 14066)
        self.assertEqual(run.actual_peak_stage, "llm_second")

    def test_runtime_does_not_generate_cross_turn_summary_for_runtime_context_status(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "runtime",
            lambda payload: {
                "action": "context_status",
                "ok": True,
                "estimated_usage": 1234,
                "effective_window": 184000,
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [LLMReply(tool_name="runtime", tool_payload={"action": "context_status"})]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["runtime"],
        )

        events = runtime.run(
            session_id="sess_runtime_no_summary_pollution",
            message="现在上下文窗口用多少了？",
            trace_id="trace_runtime_no_summary_pollution",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(run.tool_calls[0]["tool_name"], "runtime")
        self.assertEqual(run.tool_outcome_summaries, [])

    def test_runtime_generates_tool_outcome_summary_after_successful_tool_call(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "mock_search",
            lambda payload: {
                "repo": "openai/codex",
                "branch": "main",
                "issue_count": 12,
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="mock_search", tool_payload={"query": "codex"}),
                LLMReply(
                    final_text=(
                        "done\n\n```tool_episode_summary\n"
                        '{"summary":"上一轮通过 mock_search 查询了 openai/codex，确认默认分支为 main。",'
                        '"facts":[{"key":"repo","value":"openai/codex"},{"key":"branch","value":"main"}],'
                        '"volatile":false,"keep_next_turn":true,"refresh_hint":""}'
                        "\n```"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mock_search"],
        )

        events = runtime.run(
            session_id="sess_runtime_summary",
            message="查一下 codex",
            trace_id="trace_runtime_summary",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(len(run.tool_outcome_summaries), 1)
        self.assertIn("openai/codex", run.tool_outcome_summaries[0].summary_text)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual(len(llm.requests), 2)

    def test_runtime_falls_back_to_minimal_summary_when_summary_json_is_invalid(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "UTC"}),
                LLMReply(final_text="现在是 UTC 时间"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["time"],
        )

        events = runtime.run(
            session_id="sess_runtime_summary_fallback",
            message="tell me now",
            trace_id="trace_runtime_summary_fallback",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(len(run.tool_outcome_summaries), 1)
        self.assertTrue(run.tool_outcome_summaries[0].volatile)
        self.assertFalse(run.tool_outcome_summaries[0].keep_next_turn)
        self.assertEqual(len(llm.requests), 2)

    def test_runtime_merges_thin_structured_facts_when_summary_json_omits_them(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "mock_search",
            lambda payload: {
                "full_name": "CloudWide851/easy-agent",
                "default_branch": "main",
                "url": "https://github.com/CloudWide851/easy-agent",
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="mock_search", tool_payload={"query": "easy-agent"}),
                LLMReply(
                    final_text=(
                        "已完成检查\n\n```tool_episode_summary\n"
                        '{"summary":"已完成检查该仓库。","facts":[],"volatile":false,"keep_next_turn":true,"refresh_hint":""}'
                        "\n```"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mock_search"],
        )

        events = runtime.run(
            session_id="sess_runtime_merge_facts",
            message="查一下 easy-agent",
            trace_id="trace_runtime_merge_facts",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(
            [
                f"{item.key}={item.value}"
                for item in run.tool_outcome_summaries[0].facts
            ],
            [
                "full_name=CloudWide851/easy-agent",
                "default_branch=main",
                "url=https://github.com/CloudWide851/easy-agent",
            ],
        )

    def test_runtime_uses_followup_llm_summary_for_mcp_instead_of_rule_shortcut(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "mcp",
            lambda payload: {
                "server_id": "github",
                "result_text": '{"items":[{"full_name":"CloudWide851/easy-agent","default_branch":"main"}]}',
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="mcp", tool_payload={"action": "call"}),
                LLMReply(
                    final_text=(
                        "已完成检查\n\n```tool_episode_summary\n"
                        '{"summary":"上一轮通过 github MCP 查看了 easy-agent，并确认默认分支为 main。",'
                        '"facts":[{"key":"full_name","value":"CloudWide851/easy-agent"},{"key":"default_branch","value":"main"}],'
                        '"volatile":false,"keep_next_turn":true,"refresh_hint":""}'
                        "\n```"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_runtime_mcp_followup_summary",
            message="查一下 easy-agent",
            trace_id="trace_runtime_mcp_followup_summary",
            agent=agent,
        )

        summary = history.get(events[-1].run_id).tool_outcome_summaries[0]
        self.assertEqual(
            summary.summary_text,
            "上一轮通过 github MCP 查看了 easy-agent，并确认默认分支为 main。",
        )
        self.assertEqual(len(llm.requests), 2)

    def test_runtime_merges_missing_structured_facts_when_summary_json_is_partial(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "mock_search",
            lambda payload: {
                "full_name": "CloudWide851/easy-agent",
                "default_branch": "main",
                "url": "https://github.com/CloudWide851/easy-agent",
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="mock_search", tool_payload={"query": "easy-agent"}),
                LLMReply(
                    final_text=(
                        "已完成检查\n\n```tool_episode_summary\n"
                        '{"summary":"已完成检查该仓库。","facts":[{"key":"full_name","value":"CloudWide851/easy-agent"}],"volatile":false,"keep_next_turn":true,"refresh_hint":""}'
                        "\n```"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mock_search"],
        )

        events = runtime.run(
            session_id="sess_runtime_merge_partial_facts",
            message="查一下 easy-agent",
            trace_id="trace_runtime_merge_partial_facts",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(
            [
                f"{item.key}={item.value}"
                for item in run.tool_outcome_summaries[0].facts
            ],
            [
                "full_name=CloudWide851/easy-agent",
                "default_branch=main",
                "url=https://github.com/CloudWide851/easy-agent",
            ],
        )

    def test_runtime_ignores_wrong_volatile_flag_when_durable_repo_facts_exist(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "mock_search",
            lambda payload: {
                "full_name": "CloudWide851/easy-agent",
                "default_branch": "main",
                "url": "https://github.com/CloudWide851/easy-agent",
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="mock_search", tool_payload={"query": "easy-agent"}),
                LLMReply(
                    final_text=(
                        "已完成检查\n\n```tool_episode_summary\n"
                        '{"summary":"已完成检查该仓库。","facts":[{"key":"full_name","value":"CloudWide851/easy-agent"}],"volatile":true,"keep_next_turn":false,"refresh_hint":""}'
                        "\n```"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mock_search"],
        )

        events = runtime.run(
            session_id="sess_runtime_override_wrong_volatile",
            message="查一下 easy-agent",
            trace_id="trace_runtime_override_wrong_volatile",
            agent=agent,
        )

        summary = history.get(events[-1].run_id).tool_outcome_summaries[0]
        self.assertFalse(summary.volatile)
        self.assertTrue(summary.keep_next_turn)
        self.assertEqual(
            [f"{item.key}={item.value}" for item in summary.facts],
            [
                "full_name=CloudWide851/easy-agent",
                "default_branch=main",
                "url=https://github.com/CloudWide851/easy-agent",
            ],
        )

    def test_runtime_forces_volatile_flags_from_fallback_when_summary_json_is_wrong(
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
                        '{"summary":"调用了 time 工具并拿到了时间","facts":[],"volatile":false,"keep_next_turn":true,"refresh_hint":""}'
                        "\n```"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["time"],
        )

        events = runtime.run(
            session_id="sess_runtime_force_time_volatile",
            message="现在几点",
            trace_id="trace_runtime_force_time_volatile",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertTrue(run.tool_outcome_summaries[0].volatile)
        self.assertFalse(run.tool_outcome_summaries[0].keep_next_turn)
        self.assertEqual(
            run.tool_outcome_summaries[0].refresh_hint,
            "若再次询问当前时间，应重新调用工具。",
        )

    def test_runtime_keeps_next_turn_enabled_when_llm_summary_misclassifies_stable_result(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "mock_search",
            lambda payload: {
                "full_name": "CloudWide851/easy-agent",
                "default_branch": "main",
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="mock_search", tool_payload={"query": "easy-agent"}),
                LLMReply(
                    final_text=(
                        "已完成检查\n\n```tool_episode_summary\n"
                        '{"summary":"已完成检查该仓库。","facts":[],"volatile":false,"keep_next_turn":false,"refresh_hint":""}'
                        "\n```"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mock_search"],
        )

        events = runtime.run(
            session_id="sess_runtime_force_keep_next_turn",
            message="查一下 easy-agent",
            trace_id="trace_runtime_force_keep_next_turn",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertFalse(run.tool_outcome_summaries[0].volatile)
        self.assertTrue(run.tool_outcome_summaries[0].keep_next_turn)

    def test_runtime_merges_thin_structured_facts_from_nested_json_result_text(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "mcp",
            lambda payload: {
                "result_text": '{"items":[{"full_name":"CloudWide851/easy-agent","default_branch":"main","html_url":"https://github.com/CloudWide851/easy-agent"}]}'
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="mcp", tool_payload={"action": "call"}),
                LLMReply(
                    final_text=(
                        "已完成检查\n\n```tool_episode_summary\n"
                        '{"summary":"已完成检查该仓库。","facts":[],"volatile":false,"keep_next_turn":true,"refresh_hint":""}'
                        "\n```"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_runtime_merge_nested_facts",
            message="查一下 easy-agent",
            trace_id="trace_runtime_merge_nested_facts",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(
            [
                f"{item.key}={item.value}"
                for item in run.tool_outcome_summaries[0].facts
            ],
            [
                "full_name=CloudWide851/easy-agent",
                "default_branch=main",
                "url=https://github.com/CloudWide851/easy-agent",
            ],
        )

    def test_runtime_does_not_generate_tool_outcome_summary_for_failed_tool_call(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "broken_tool",
            lambda payload: (_ for _ in ()).throw(ValueError("tool blew up")),
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [LLMReply(tool_name="broken_tool", tool_payload={"value": "x"})]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["broken_tool"],
        )

        events = runtime.run(
            session_id="sess_runtime_summary_fail",
            message="run broken tool",
            trace_id="trace_runtime_summary_fail",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.tool_outcome_summaries, [])

    def test_runtime_initial_preflight_reflects_activated_skill_bodies(self) -> None:
        history = InMemoryRunHistory()
        llm_plain = ScriptedLLMClient([LLMReply(final_text="plain")])
        llm_skill = ScriptedLLMClient([LLMReply(final_text="skill")])

        runtime_plain = RuntimeLoop(llm_plain, ToolRegistry(), history)
        events_plain = runtime_plain.run(
            session_id="sess_skill_plain",
            message="继续处理",
            trace_id="trace_skill_plain",
        )
        plain_run = history.get(events_plain[-1].run_id)

        runtime_skill = RuntimeLoop(llm_skill, ToolRegistry(), history)
        events_skill = runtime_skill.run(
            session_id="sess_skill_loaded",
            message="继续处理",
            trace_id="trace_skill_loaded",
            activated_skill_bodies=["Skill body " * 50],
        )
        skill_run = history.get(events_skill[-1].run_id)

        self.assertGreater(
            skill_run.initial_preflight_input_tokens_estimate,
            plain_run.initial_preflight_input_tokens_estimate,
        )

    def test_runtime_reinjects_recent_tool_outcome_summary_on_followup_turn(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="done")])
        runtime = RuntimeLoop(llm, tools, history)

        runtime.run(
            session_id="sess_followup_summary",
            message="基于刚才的工具结果继续",
            trace_id="trace_followup_summary",
            session_messages=[
                SessionMessage.user("先查 repo"),
                SessionMessage.assistant("已查 repo"),
            ],
            recent_tool_outcome_summaries=[
                {
                    "source_kind": "mcp",
                    "summary_text": "上一轮通过 github MCP 查询了 repo=openai/codex，branch=main。",
                }
            ],
        )

        self.assertIn(
            "Recent tool outcome summary",
            llm.requests[0].tool_outcome_summary_text or "",
        )
        self.assertIn(
            "repo=openai/codex", llm.requests[0].tool_outcome_summary_text or ""
        )

    def test_runtime_supports_multi_step_tool_loop_before_final(self) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        tools.register(
            "mock_search", lambda payload: {"result_text": f"search:{payload['query']}"}
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "UTC"}),
                LLMReply(
                    tool_name="mock_search", tool_payload={"query": "utc follow-up"}
                ),
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

        events = runtime.run(
            session_id="sess_multi",
            message="tell me now",
            trace_id="trace_multi",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "done")
        self.assertEqual(len(llm.requests), 3)
        self.assertEqual(llm.requests[1].tool_history[0].tool_name, "time")
        self.assertEqual(llm.requests[2].tool_history[1].tool_name, "mock_search")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 3)

    def test_runtime_handles_explicit_github_repo_query_via_llm_selected_mcp_call(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "search_repositories",
                        "arguments": {"query": "repo:CloudWide851/easy-agent"},
                    },
                ),
                LLMReply(
                    final_text=(
                        "默认分支是 main，描述已确认。\n\n```tool_episode_summary\n"
                        '{"summary":"通过 GitHub MCP 查询了 CloudWide851/easy-agent 的默认分支和描述。","facts":[{"key":"full_name","value":"CloudWide851/easy-agent"},{"key":"default_branch","value":"main"}],"volatile":false,"keep_next_turn":true,"refresh_hint":""}\n'
                        "```"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": '{"items":[{"full_name":"CloudWide851/easy-agent","default_branch":"main","description":"demo"}]}',
                "ok": True,
                "is_error": False,
            },
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_mcp_direct",
            message="请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库的默认分支和描述。",
            trace_id="trace_mcp_direct",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "默认分支是 main，描述已确认。")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(
            llm.requests[0].message,
            "请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库的默认分支和描述。",
        )
        self.assertEqual(llm.requests[1].tool_history[0].tool_name, "mcp")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual(len(run.tool_calls), 1)

    def test_runtime_uses_llm_first_for_runtime_detail_query(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [LLMReply(tool_name="runtime", tool_payload={"action": "context_status"})]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "runtime",
            lambda payload: {"action": payload["action"], "summary": "ok", "ok": True},
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["runtime"],
        )

        events = runtime.run(
            session_id="sess_runtime_detail",
            message="当前上下文的具体使用详情是什么？",
            trace_id="trace_runtime_detail",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(len(llm.requests), 1)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls[0]["tool_name"], "runtime")

    def test_runtime_handles_explicit_github_repo_commit_query_via_llm_selected_mcp_call(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "list_commits",
                        "arguments": {
                            "owner": "CloudWide851",
                            "repo": "easy-agent",
                            "perPage": 1,
                        },
                    },
                ),
                LLMReply(
                    final_text=(
                        "这个仓库最近一次提交时间是 2026-04-01 10:24:49（北京时间）。\n\n```tool_episode_summary\n"
                        '{"summary":"通过 GitHub MCP list_commits 查询了 CloudWide851/easy-agent 最近一次提交时间。","facts":[{"key":"full_name","value":"CloudWide851/easy-agent"},{"key":"latest_commit_at","value":"2026-04-01T02:24:49Z"}],"volatile":false,"keep_next_turn":true,"refresh_hint":""}\n'
                        "```"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"}}}]',
                "ok": True,
                "is_error": False,
            },
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        with patch.dict("os.environ", {"TZ": "Asia/Shanghai"}):
            events = runtime.run(
                session_id="sess_mcp_commit_direct",
                message="请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库最近一次提交是什么时候？",
                trace_id="trace_mcp_commit_direct",
                agent=agent,
            )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(
            events[-1].payload["text"],
            "CloudWide851/easy-agent 最近一次提交是 **2026-04-01 10:24:49**（北京时间）。",
        )
        self.assertEqual(len(llm.requests), 1)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls[0]["tool_payload"]["tool_name"], "list_commits")

    def test_runtime_recovers_when_followup_returns_generic_tool_failure_after_successful_commit_tool(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "list_commits",
                        "arguments": {"owner": "llt22", "repo": "talkio", "perPage": 1},
                    },
                ),
                LLMReply(final_text="工具执行失败，请重试。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": (
                    '[{"sha":"f2055a6400cf1d78948729d83bd8fb1107aa9d2c",'
                    '"commit":{"message":"release: v2.7.2","author":{"date":"2026-04-05T13:48:45Z"}}}]'
                ),
                "ok": True,
                "is_error": False,
            },
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_mcp_commit_recover",
            message="GitHub - llt22/talkio 这个github仓库最近一次提交是什么时候",
            trace_id="trace_mcp_commit_recover",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("最近一次提交", events[-1].payload["text"])
        self.assertNotEqual(events[-1].payload["text"], "工具执行失败，请重试。")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls[0]["tool_payload"]["tool_name"], "list_commits")

    def test_runtime_uses_llm_first_for_trending_query(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github_trending",
                        "tool_name": "trending_repositories",
                        "arguments": {"since": "daily", "limit": 10},
                    },
                )
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": (
                    '{"source":"github_trending","order_basis":"github_trending_page_rank","since":"daily",'
                    '"fetched_at_display":"2026-04-08 16:42","items":['
                    '{"rank":1,"full_name":"google-ai-edge/gallery","language":"Kotlin","stars_period":897},'
                    '{"rank":2,"full_name":"google-ai-edge/LiteRT-LM","language":"C++","stars_period":528}'
                    "]}"
                ),
                "ok": True,
                "is_error": False,
            },
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_trending_direct",
            message="今日trnding top10都哪些项目",
            trace_id="trace_trending_direct",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(len(llm.requests), 1)
        self.assertIn("GitHub 今日热榜", events[-1].payload["text"])
        self.assertIn("1. google-ai-edge/gallery", events[-1].payload["text"])
        self.assertIn("2. google-ai-edge/LiteRT-LM", events[-1].payload["text"])
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(len(run.tool_calls), 1)
        self.assertEqual(
            run.tool_calls[0]["tool_payload"]["server_id"], "github_trending"
        )
        self.assertEqual(
            run.tool_calls[0]["tool_payload"]["tool_name"], "trending_repositories"
        )
        self.assertEqual(
            run.tool_calls[0]["tool_payload"]["arguments"]["since"], "daily"
        )
        self.assertEqual(run.tool_calls[0]["tool_payload"]["arguments"]["limit"], 10)

    def test_runtime_uses_llm_first_for_trending_typo_query(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github_trending",
                        "tool_name": "trending_repositories",
                        "arguments": {"since": "daily", "limit": 10},
                    },
                )
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": (
                    '{"source":"github_trending","order_basis":"github_trending_page_rank","since":"daily",'
                    '"fetched_at_display":"2026-04-08 16:42","items":['
                    '{"rank":1,"full_name":"forrestchang/andrej-karpathy-skills","language":null,"stars_period":686}'
                    "]}"
                ),
                "ok": True,
                "is_error": False,
            },
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_treding_direct",
            message="今日treding top10都哪些项目",
            trace_id="trace_treding_direct",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(len(llm.requests), 1)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(len(run.tool_calls), 1)
        self.assertEqual(
            run.tool_calls[0]["tool_payload"]["server_id"], "github_trending"
        )
        self.assertEqual(
            run.tool_calls[0]["tool_payload"]["tool_name"], "trending_repositories"
        )
        self.assertEqual(
            run.tool_calls[0]["tool_payload"]["arguments"]["since"], "daily"
        )
        self.assertEqual(run.tool_calls[0]["tool_payload"]["arguments"]["limit"], 10)

    def test_runtime_shortcuts_weekly_trending_query_to_weekly_since(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github_trending",
                        "tool_name": "trending_repositories",
                        "arguments": {"since": "weekly", "limit": 5},
                    },
                )
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": '{"source":"github_trending","since":"weekly","fetched_at_display":"2026-04-08 16:42","items":[]}',
                "ok": True,
                "is_error": False,
            },
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_trending_weekly",
            message="GitHub trending 周榜 top5",
            trace_id="trace_trending_weekly",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(
            run.tool_calls[0]["tool_payload"]["arguments"]["since"], "weekly"
        )
        self.assertEqual(run.tool_calls[0]["tool_payload"]["arguments"]["limit"], 5)

    def test_runtime_returns_error_when_llm_requests_tool_outside_agent_contract(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [LLMReply(tool_name="time", tool_payload={"timezone": "UTC"})]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=[],
        )

        events = runtime.run(
            session_id="sess_1",
            message="tell me now",
            trace_id="trace_denied",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "TOOL_NOT_ALLOWED")
        self.assertEqual(
            events[-1].payload["text"], "当前操作未被允许，请换个说法或缩小范围。"
        )
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "TOOL_NOT_ALLOWED")

    def test_runtime_failure_paths_finalize_total_timing(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = FailingLLMClient()
        runtime = RuntimeLoop(llm, tools, history)

        with patch(
            "marten_runtime.runtime.loop.time.perf_counter",
            side_effect=[10.0, 11.0, 11.3, 11.7],
        ):
            events = runtime.run(
                session_id="sess_fail", message="hello", trace_id="trace_fail"
            )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertGreaterEqual(run.timings.llm_first_ms, 299)
        self.assertEqual(run.timings.total_ms, 1699)

    def test_runtime_returns_provider_transport_error_for_explicit_github_commit_query_after_first_llm_provider_failure(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(FailingLLMClient(), tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"},"message":"chore(release): 发布0.3.3版本"}}]',
                "ok": True,
                "is_error": False,
            },
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_fail_commit_recover",
            message="GitHub - CloudWide851/easy-agent 这个github仓库最近一次提交是什么时候",
            trace_id="trace_fail_commit_recover",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "PROVIDER_TRANSPORT_ERROR")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls, [])

    def test_runtime_returns_provider_transport_error_for_explicit_github_404_commit_query_after_first_llm_provider_failure(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(FailingLLMClient(), tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": "failed to list commits: : GET https://api.github.com/repos/definitely-not-found-user/definitely-not-found-repo/commits?page=1&per_page=1: 404 Not Found []",
                "ok": False,
                "is_error": True,
            },
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_fail_commit_404_recover",
            message="GitHub - definitely-not-found-user/definitely-not-found-repo 这个github仓库最近一次提交是什么时候",
            trace_id="trace_fail_commit_404_recover",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "PROVIDER_TRANSPORT_ERROR")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls, [])

    def test_runtime_recovers_direct_commit_text_when_followup_provider_call_times_out(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = FirstSuccessThenFailingLLMClient(
            LLMReply(
                tool_name="mcp",
                tool_payload={
                    "action": "call",
                    "server_id": "github",
                    "tool_name": "list_commits",
                    "arguments": {
                        "owner": "CloudWide851",
                        "repo": "easy-agent",
                        "perPage": 1,
                    },
                },
            )
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"},"message":"chore(release): 发布0.3.3版本"}}]',
                "ok": True,
                "is_error": False,
            },
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_followup_provider_fail_recover",
            message="GitHub - CloudWide851/easy-agent 这个github仓库最近一次提交是什么时候",
            trace_id="trace_followup_provider_fail_recover",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn(
            "CloudWide851/easy-agent 最近一次提交是", events[-1].payload["text"]
        )
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.llm_request_count, 1)

    def test_runtime_recovers_direct_commit_text_when_followup_requests_disallowed_tool(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = FirstSuccessThenDisallowedToolLLMClient(
            LLMReply(
                tool_name="mcp",
                tool_payload={
                    "action": "call",
                    "server_id": "github",
                    "tool_name": "list_commits",
                    "arguments": {
                        "owner": "CloudWide851",
                        "repo": "easy-agent",
                        "perPage": 1,
                    },
                },
            )
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"},"message":"chore(release): 发布0.3.3版本"}}]',
                "ok": True,
                "is_error": False,
            },
        )
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_followup_disallowed_tool_recover",
            message="GitHub - CloudWide851/easy-agent 这个github仓库最近一次提交是什么时候",
            trace_id="trace_followup_disallowed_tool_recover",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn(
            "CloudWide851/easy-agent 最近一次提交是", events[-1].payload["text"]
        )
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.llm_request_count, 1)

    def test_runtime_distinguishes_tool_execution_failure_from_generic_runtime_failure(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        tools.register(
            "broken_tool",
            lambda payload: (_ for _ in ()).throw(ValueError("tool blew up")),
        )
        runtime = RuntimeLoop(BrokenToolLLMClient(), tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["broken_tool"],
        )

        events = runtime.run(
            session_id="sess_tool_fail",
            message="run broken tool",
            trace_id="trace_tool_fail",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "TOOL_EXECUTION_FAILED")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "TOOL_EXECUTION_FAILED")

    def test_runtime_returns_error_when_final_text_is_empty_after_tool_call(
        self,
    ) -> None:
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

        events = runtime.run(
            session_id="sess_empty",
            message="tell me now",
            trace_id="trace_empty",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "EMPTY_FINAL_RESPONSE")
        self.assertEqual(events[-1].payload["text"], "暂时没有生成可见回复，请重试。")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "EMPTY_FINAL_RESPONSE")

    def test_runtime_exposes_provider_specific_error_codes_for_provider_failures(
        self,
    ) -> None:
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

            events = runtime.run(
                session_id="sess_fail", message="hello", trace_id="trace_fail"
            )
            failures = store.list_recent_failures(agent_id="assistant", limit=10)

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(events[-1].payload["text"], "暂时没有生成可见回复，请重试。")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].error_code, "PROVIDER_TRANSPORT_ERROR")

    def test_runtime_keeps_runtime_loop_failed_for_unknown_internal_exceptions(
        self,
    ) -> None:
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

            events = runtime.run(
                session_id="sess_fail_internal",
                message="hello",
                trace_id="trace_fail_internal",
            )
            failures = store.list_recent_failures(agent_id="assistant", limit=10)

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "RUNTIME_LOOP_FAILED")
        self.assertEqual(events[-1].payload["text"], "暂时没有生成可见回复，请重试。")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "RUNTIME_LOOP_FAILED")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].error_code, "RUNTIME_LOOP_FAILED")

    def test_runtime_records_recovery_after_later_success_on_compatible_message(
        self,
    ) -> None:
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

            failing_runtime.run(
                session_id="sess_fail", message="hello", trace_id="trace_fail"
            )
            success_runtime.run(
                session_id="sess_success", message="hello", trace_id="trace_success"
            )
            recoveries = store.list_recent_recoveries(agent_id="assistant", limit=10)

        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0].recovery_kind, "same_fingerprint_success")

    def test_runtime_allows_main_agent_to_register_automation_via_family_tool(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteAutomationStore(Path(tmpdir) / "automations.sqlite3")
            adapter = DomainDataAdapter(
                self_improve_store=SQLiteSelfImproveStore(
                    Path(tmpdir) / "self_improve.sqlite3"
                ),
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
                            "skill_id": "github_trending_digest",
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

            self.assertEqual(
                [event.event_type for event in events], ["progress", "final"]
            )
            enabled = store.list_enabled()
            self.assertEqual(len(enabled), 1)
            self.assertEqual(enabled[0].automation_id, "daily_hot")
            self.assertEqual(enabled[0].schedule_expr, "09:30")
            self.assertEqual(enabled[0].delivery_target, "oc_test_chat")
            self.assertEqual(llm.requests[0].available_tools, ["automation"])
            self.assertEqual(len(llm.requests), 1)
            self.assertIn("已创建定时任务 Daily GitHub Hot Repos", events[-1].payload["text"])
            run = history.get(events[-1].run_id)
            self.assertEqual(run.llm_request_count, 1)

    def test_runtime_does_not_misroute_automation_registration_prompt_to_trending_fast_path(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteAutomationStore(Path(tmpdir) / "automations.sqlite3")
            adapter = DomainDataAdapter(
                self_improve_store=SQLiteSelfImproveStore(
                    Path(tmpdir) / "self_improve.sqlite3"
                ),
                automation_store=store,
            )
            tools = ToolRegistry()
            tools.register(
                "automation",
                lambda payload: run_automation_tool(payload, store, adapter),
            )
            tools.register(
                "mcp",
                lambda payload: {
                    "action": "call",
                    "server_id": payload.get("server_id"),
                    "tool_name": payload.get("tool_name"),
                    "arguments": payload.get("arguments", {}),
                    "ok": True,
                    "is_error": False,
                    "result_text": '{"items":[]}',
                },
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
                            "skill_id": "github_trending_digest",
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
                allowed_tools=["automation", "mcp"],
            )

            events = runtime.run(
                session_id="sess_register_task",
                message="请创建一个每日 GitHub 热门项目任务。",
                trace_id="trace_register_task",
                agent=agent,
            )

            self.assertEqual(
                [event.event_type for event in events], ["progress", "final"]
            )
            self.assertIn("已创建定时任务 Daily GitHub Hot Repos", events[-1].payload["text"])
            run = history.get(events[-1].run_id)
            self.assertEqual(run.llm_request_count, 1)
            self.assertEqual(run.tool_calls[0]["tool_name"], "automation")
            self.assertEqual(len(llm.requests), 1)

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

    def test_runtime_returns_provider_auth_error_when_provider_auth_fails_before_any_tool(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = AuthFailingLLMClient()
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=[],
        )

        events = runtime.run(
            session_id="sess_auth_plain",
            message="hello",
            trace_id="trace_auth_plain",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "PROVIDER_AUTH_ERROR")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.llm_request_count, 1)

    def test_runtime_returns_provider_auth_error_for_explicit_skill_load_when_provider_auth_fails_before_any_tool(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            skills_root = Path(tmpdir) / "skills"
            skill_dir = skills_root / "example_time"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                (
                    "---\n"
                    "skill_id: example_time\n"
                    "name: Example Time\n"
                    "description: Return current time guidance\n"
                    "enabled: true\n"
                    "agents: [assistant]\n"
                    "channels: [http]\n"
                    "---\n"
                    "Use the time tool when the user asks for the current time.\n"
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
            llm = AuthFailingLLMClient()
            runtime = RuntimeLoop(llm, tools, history)
            agent = AgentSpec(
                agent_id="assistant",
                role="general_assistant",
                app_id="example_assistant",
                allowed_tools=["skill"],
            )

            events = runtime.run(
                session_id="sess_auth_skill",
                message="请读取 example_time 这个 skill 并简单概括它的用途",
                trace_id="trace_auth_skill",
                agent=agent,
            )

            self.assertEqual(
                [event.event_type for event in events], ["progress", "error"]
            )
            self.assertEqual(events[-1].payload["code"], "PROVIDER_AUTH_ERROR")
            run = history.get(events[-1].run_id)
            self.assertEqual(run.status, "failed")
            self.assertEqual(run.llm_request_count, 1)

    def test_runtime_returns_provider_auth_error_for_explicit_github_commit_query_when_provider_auth_fails_before_any_tool(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"},"message":"chore(release): 发布0.3.3版本"}}]',
                "ok": True,
                "is_error": False,
            },
        )
        history = InMemoryRunHistory()
        llm = AuthFailingLLMClient()
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_auth_commit",
            message="GitHub - CloudWide851/easy-agent 这个github仓库最近一次提交是什么时候",
            trace_id="trace_auth_commit",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "PROVIDER_AUTH_ERROR")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.llm_request_count, 1)

    def test_runtime_returns_provider_auth_error_for_english_explicit_github_commit_query_when_provider_auth_fails_before_any_tool(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"},"message":"chore(release): 发布0.3.3版本"}}]',
                "ok": True,
                "is_error": False,
            },
        )
        history = InMemoryRunHistory()
        llm = AuthFailingLLMClient()
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_auth_commit_en",
            message="latest commit of CloudWide851/easy-agent",
            trace_id="trace_auth_commit_en",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "PROVIDER_AUTH_ERROR")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.llm_request_count, 1)

    def test_runtime_can_use_self_improve_candidate_tools_without_affecting_active_lessons(
        self,
    ) -> None:
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
                            "agent_id": "assistant",
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
