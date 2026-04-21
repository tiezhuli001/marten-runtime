import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.config.models_loader import ModelProfile
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient, estimate_request_tokens
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.compaction_trigger import build_compaction_settings
from marten_runtime.session.models import SessionMessage
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.tools.builtins.runtime_tool import run_runtime_tool
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.registry import ToolRegistry, ToolSnapshot
from tests.support.scripted_llm import PromptTooLongThenSuccessLLMClient


class RuntimeLoopContextStatusAndUsageTests(unittest.TestCase):

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
                agent_id="main",
                app_id="main_agent",
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
                    provider_ref="openai",
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
                    provider_ref="openai",
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
                    provider_ref="openai",
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

    def test_runtime_records_pre_compaction_learning_flush_trigger_on_proactive_compaction(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            tools = ToolRegistry()
            history = InMemoryRunHistory()
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            recorder = SelfImproveRecorder(store)
            llm = ScriptedLLMClient(
                [LLMReply(final_text="done after proactive compact")]
            )
            compact_llm = ScriptedLLMClient(
                [LLMReply(final_text="当前进展：长线程已压缩。")]
            )
            runtime = RuntimeLoop(
                llm,
                tools,
                history,
                self_improve_recorder=recorder,
            )

            events = runtime.run(
                session_id="sess_pre_compact_trigger",
                message="下一步：继续处理剩余问题",
                trace_id="trace_pre_compact_trigger",
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
                        provider_ref="openai",
                        model="gpt-4.1",
                        context_window_tokens=400,
                        reserve_output_tokens=50,
                        compact_trigger_ratio=0.5,
                    )
                ),
            )

            run_id = events[-1].run_id
            triggers = store.list_review_triggers(
                agent_id="main",
                limit=10,
                status="pending",
            )

        self.assertEqual(len(triggers), 1)
        trigger = triggers[0]
        self.assertEqual(trigger.trigger_kind, "pre_compaction_learning_flush")
        self.assertEqual(trigger.source_run_id, run_id)
        self.assertGreater(
            int(trigger.payload_json["estimated_tokens_before"]),
            int(trigger.payload_json["estimated_tokens_after"]),
        )

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
                LLMReply(
                    final_text=(
                        "当前上下文使用详情：当前估算占用 1200/184000 tokens（1%）。"
                        " 下一次请求预计输入 1200 tokens。"
                    )
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
        self.assertIn("当前会话下一次请求预计带入", events[-1].payload["text"])
        self.assertIn("切换会话后会按目标会话重新计算", events[-1].payload["text"])
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
        self.assertLessEqual(
            tool_result["current_run"]["peak_input_tokens_estimate"],
            run.peak_preflight_input_tokens_estimate,
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
            [
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(final_text="当前上下文使用详情：现在占用很低。"),
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["runtime"],
        )

        events = runtime.run(
            session_id="sess_runtime_direct",
            message="现在上下文用了多少，简短一点。",
            trace_id="trace_runtime_direct",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("当前会话下一次请求预计带入", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 1)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls[0]["tool_name"], "runtime")
        self.assertEqual(
            run.tool_calls[0]["tool_payload"], {"action": "context_status"}
        )

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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
        self.assertEqual(run.actual_cumulative_input_tokens, 16270)
        self.assertEqual(run.actual_cumulative_output_tokens, 316)
        self.assertEqual(run.actual_cumulative_total_tokens, 16586)

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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
