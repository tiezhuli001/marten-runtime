import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.llm_message_support import build_openai_messages
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.registry import ToolRegistry
from tests.support.domain_builders import build_self_improve_adapter
from tests.support.scripted_llm import (
    BrokenInternalLLMClient,
    BrokenToolLLMClient,
    FailingLLMClient,
    FirstSuccessThenDisallowedToolLLMClient,
    FirstSuccessThenFailingLLMClient,
)


class RuntimeLoopToolFollowupAndRecoveryTests(unittest.TestCase):

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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            "只有当前消息明确承接上一轮结果时才参考",
            llm.requests[0].tool_outcome_summary_text or "",
        )
        self.assertIn(
            "repo=openai/codex", llm.requests[0].tool_outcome_summary_text or ""
        )

    def test_runtime_marks_stale_compact_and_tool_summaries_as_background_only_for_new_turn(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([LLMReply(final_text="当前只回答这一轮。")])
        runtime = RuntimeLoop(llm, tools, history)

        runtime.run(
            session_id="sess_background_only",
            message="当前上下文窗口大小",
            trace_id="trace_background_only",
            session_messages=[
                SessionMessage.user("请严格按顺序先调用 time，再调用 runtime，再调用 mcp。"),
                SessionMessage.assistant("上一轮按 time/runtime/mcp 链路完成。"),
            ],
            compacted_context=CompactedContext(
                compact_id="cmp_background_only",
                session_id="sess_background_only",
                summary_text=(
                    "旧摘要：最近处理了会话列表、上下文窗口、GitHub 最近提交时间。\n"
                    "建议下一步优先可做三件事：1. 回答上下文窗口 2. 列会话列表 3. 跟进 GitHub 最近提交时间。"
                ),
                source_message_range=[0, 1],
                preserved_tail_user_turns=1,
            ),
            recent_tool_outcome_summaries=[
                {
                    "source_kind": "mcp",
                    "summary_text": "上一轮调用了 MCP，并获得了查询结果。",
                }
            ],
        )

        request = llm.requests[0]
        messages = build_openai_messages(request)
        system_text = "\n".join(
            str(item.get("content") or "")
            for item in messages
            if item.get("role") == "system"
        )
        self.assertIn("当前用户最新一条消息定义本轮任务边界", system_text)
        self.assertIn("当前这条用户消息优先级最高", system_text)
        self.assertIn("只有当前消息明确承接上一轮结果时才参考", system_text)

    def test_runtime_skips_post_turn_summary_for_mcp_server_inventory_turns(self) -> None:
        tools = ToolRegistry()
        tools.register(
            "mcp",
            lambda payload: {
                "ok": True,
                "action": payload.get("action", "list"),
                "servers": [{"server_id": "github", "tool_count": 38}],
                "result_text": '{"servers":[{"server_id":"github","tool_count":38}]}',
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="mcp", tool_payload={"action": "list"}),
                LLMReply(final_text="当前可用 MCP 服务共 1 个。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["mcp"],
        )

        events = runtime.run(
            session_id="sess_skip_mcp_inventory_summary",
            message="列出当前可用 MCP 服务",
            trace_id="trace_skip_mcp_inventory_summary",
            agent=agent,
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(run.tool_outcome_summaries, [])

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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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

    def test_runtime_routes_fixed_three_step_sequence_back_through_followup_llm(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        tools.register(
            "runtime",
            lambda payload: {
                "ok": True,
                "action": "context_status",
                "summary": "当前估算占用 1234/184000 tokens（1%）。",
                "estimated_usage": 1234,
                "effective_window": 184000,
                "current_run": {
                    "initial_input_tokens_estimate": 1234,
                    "peak_input_tokens_estimate": 1234,
                    "peak_stage": "initial_request",
                    "actual_cumulative_input_tokens": 0,
                    "actual_cumulative_output_tokens": 0,
                    "actual_cumulative_total_tokens": 0,
                    "actual_peak_input_tokens": None,
                    "actual_peak_output_tokens": None,
                    "actual_peak_total_tokens": None,
                    "actual_peak_stage": None,
                },
                "next_request_estimate": {
                    "input_tokens_estimate": 1234,
                    "effective_window_tokens": 184000,
                    "context_window_tokens": 200000,
                    "estimator_kind": "rough",
                    "degraded": True,
                },
                "context_window": 200000,
                "usage_percent": 1,
                "compaction_status": "none",
                "latest_checkpoint": "none",
                "estimate_source": "rough",
                "last_actual_usage": None,
                "last_completed_run": None,
                "model_profile": "minimax_coding",
            },
        )
        tools.register(
            "mcp",
            lambda payload: {
                "ok": True,
                "action": payload.get("action", "list"),
                "servers": [{"server_id": "github", "tool_count": 38}],
                "result_text": '{"servers":[{"server_id":"github","tool_count":38}]}',
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(tool_name="mcp", tool_payload={"action": "list"}),
                LLMReply(
                    final_text=(
                        "现在是北京时间 2026年4月20日 12:30。\n\n"
                        "当前上下文使用详情：当前估算占用 1200/184000 tokens（1%）。\n\n"
                        "当前可用 MCP 服务共 1 个。\n\n"
                        "本次请求发生了多次模型/工具往返。"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["time", "runtime", "mcp"],
        )

        events = runtime.run(
            session_id="sess_runtime_sequence_keeps_going",
            message=(
                "先看当前时间，再检查上下文占用，"
                "最后列出当前可用 MCP 服务并汇总。"
            ),
            trace_id="trace_runtime_sequence_keeps_going",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("当前上下文使用详情", events[-1].payload["text"])
        self.assertIn("当前可用 MCP 服务共 1 个", events[-1].payload["text"])
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 4)
        self.assertEqual(
            [item["tool_name"] for item in run.tool_calls],
            ["time", "runtime", "mcp"],
        )

    def test_runtime_direct_renders_time_when_llm_marks_single_tool_turn_terminal(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="time",
                    tool_payload={
                        "timezone": "Asia/Shanghai",
                        "finalize_response": True,
                    },
                )
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
            session_id="sess_time_finalize_response",
            message="告诉我当前北京时间。",
            trace_id="trace_time_finalize_response",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("现在是北京时间", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 1)
        self.assertIsNone(llm.requests[0].finalization_evidence_ledger)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls[0]["tool_name"], "time")
        self.assertTrue(run.tool_calls[0]["tool_payload"]["finalize_response"])

    def test_runtime_recovers_combined_three_step_sequence_when_final_text_degrades_to_last_tool_only(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        tools.register(
            "runtime",
            lambda payload: {
                "ok": True,
                "action": "context_status",
                "summary": "当前估算占用 1234/184000 tokens（1%）。",
                "estimated_usage": 1234,
                "effective_window": 184000,
                "current_run": {
                    "initial_input_tokens_estimate": 1234,
                    "peak_input_tokens_estimate": 1234,
                    "peak_stage": "initial_request",
                    "actual_cumulative_input_tokens": 0,
                    "actual_cumulative_output_tokens": 0,
                    "actual_cumulative_total_tokens": 0,
                    "actual_peak_input_tokens": None,
                    "actual_peak_output_tokens": None,
                    "actual_peak_total_tokens": None,
                    "actual_peak_stage": None,
                },
                "next_request_estimate": {
                    "input_tokens_estimate": 1234,
                    "effective_window_tokens": 184000,
                    "context_window_tokens": 200000,
                    "estimator_kind": "rough",
                    "degraded": True,
                },
                "context_window": 200000,
                "usage_percent": 1,
                "compaction_status": "none",
                "latest_checkpoint": "none",
                "estimate_source": "rough",
                "last_actual_usage": None,
                "last_completed_run": None,
                "model_profile": "minimax_coding",
            },
        )
        tools.register(
            "mcp",
            lambda payload: {
                "ok": True,
                "action": payload.get("action", "list"),
                "servers": [{"server_id": "github", "tool_count": 38, "state": "discovered"}],
                "result_text": '{"servers":[{"server_id":"github","tool_count":38,"state":"discovered"}]}',
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(tool_name="mcp", tool_payload={"action": "list"}),
                LLMReply(
                    final_text="当前可用 MCP 服务共 1 个。\n- 1. github（38 个工具，状态 discovered）"
                ),
                LLMReply(final_text="工具执行失败，请重试。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["time", "runtime", "mcp"],
        )

        events = runtime.run(
            session_id="sess_runtime_sequence_degraded_final_text",
            message=(
                "请严格按顺序先调用 time 获取当前时间，"
                "再调用 runtime 查看当前 run 的 context_status，"
                "再调用 mcp 列出 github server 的可用工具，"
                "最后用中文总结这次链路，并明确说明这次请求是否发生了多次模型/工具往返。"
            ),
            trace_id="trace_runtime_sequence_degraded_final_text",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("现在是北京时间", events[-1].payload["text"])
        self.assertIn("当前上下文使用详情", events[-1].payload["text"])
        self.assertIn("当前可用 MCP 服务共 1 个", events[-1].payload["text"])
        self.assertIn("属于多次模型/工具往返", events[-1].payload["text"])

    def test_runtime_recovers_explicit_chain_summary_without_leaking_historical_conclusions(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        tools.register(
            "runtime",
            lambda payload: {
                "ok": True,
                "action": "context_status",
                "summary": "当前估算占用 1234/184000 tokens（1%）。",
                "effective_window": 184000,
                "usage_percent": 1,
                "next_request_estimate": {
                    "input_tokens_estimate": 1234,
                    "estimator_kind": "tokenizer",
                },
                "compaction_status": "none",
            },
        )
        tools.register(
            "mcp",
            lambda payload: {
                "ok": True,
                "action": payload.get("action", "list"),
                "servers": [{"server_id": "github", "tool_count": 38, "state": "discovered"}],
                "result_text": '{"servers":[{"server_id":"github","tool_count":38,"state":"discovered"}]}',
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(tool_name="mcp", tool_payload={"action": "list"}),
                LLMReply(final_text="已按顺序完成，且这次请求明确发生了多次模型/工具往返。"),
                LLMReply(final_text="工具执行失败，请重试。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["time", "runtime", "mcp"],
        )

        events = runtime.run(
            session_id="sess_runtime_sequence_no_history_leak",
            message=(
                "请严格按顺序先调用 time 获取当前时间，"
                "再调用 runtime 查看当前 run 的 context_status，"
                "再调用 mcp 列出 github server 的可用工具，"
                "最后用中文总结这次链路，并明确说明这次请求是否发生了多次模型/工具往返。"
            ),
            trace_id="trace_runtime_sequence_no_history_leak",
            agent=agent,
            session_messages=[
                SessionMessage.user("上一轮帮我查历史 GitHub 结论。"),
                SessionMessage.assistant("上一轮确认默认分支是 main，并建议继续看 issue 列表。"),
            ],
            recent_tool_outcome_summaries=[
                {
                    "source_kind": "mcp",
                    "summary_text": "上一轮通过 github MCP 查询了 repo=openai/codex，default_branch=main。",
                }
            ],
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("现在是北京时间", events[-1].payload["text"])
        self.assertIn("当前上下文使用详情", events[-1].payload["text"])
        self.assertIn("当前可用 MCP 服务共 1 个", events[-1].payload["text"])
        self.assertIn("属于多次模型/工具往返", events[-1].payload["text"])
        self.assertNotIn("默认分支是 main", events[-1].payload["text"])
        self.assertNotIn("repo=openai/codex", events[-1].payload["text"])
        retry_request = llm.requests[-1]
        self.assertEqual(retry_request.request_kind, "finalization_retry")
        self.assertEqual(retry_request.conversation_messages, [])
        self.assertIsNone(retry_request.compact_summary_text)
        self.assertIsNone(retry_request.tool_outcome_summary_text)
        self.assertIsNotNone(llm.requests[1].finalization_evidence_ledger)
        self.assertEqual(llm.requests[1].finalization_evidence_ledger.tool_call_count, 1)
        self.assertEqual(llm.requests[2].finalization_evidence_ledger.tool_call_count, 2)
        self.assertEqual(llm.requests[3].finalization_evidence_ledger.tool_call_count, 3)
        self.assertIsNotNone(retry_request.finalization_evidence_ledger)
        self.assertEqual(retry_request.finalization_evidence_ledger.tool_call_count, 3)
        self.assertEqual(retry_request.finalization_evidence_ledger.model_request_count, 4)

    def test_runtime_keeps_strong_model_authored_final_text_without_finalization_retry(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(final_text="现在是北京时间 2026-04-20 12:30，这轮查询已经完成。"),
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
            session_id="sess_strong_final_text",
            message="先查一下现在几点，然后直接告诉我结果。",
            trace_id="trace_strong_final_text",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "现在是北京时间 2026-04-20 12:30，这轮查询已经完成。")
        self.assertEqual([request.request_kind for request in llm.requests], ["interactive", "interactive"])
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual(run.finalization.assessment, "accepted")
        self.assertEqual(run.finalization.request_kind, "interactive")
        self.assertEqual(run.finalization.required_evidence_count, 1)
        self.assertFalse(run.finalization.retry_triggered)
        self.assertEqual(run.finalization.missing_evidence_items, [])

    def test_runtime_uses_one_finalization_retry_before_accepting_retry_text(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(final_text="工具执行失败，请重试。"),
                LLMReply(final_text="现在是北京时间 2026-04-20 12:30，我已经基于现有结果完成回答。"),
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
            session_id="sess_finalization_retry_success",
            message="先查一下北京时间，然后告诉我结果。",
            trace_id="trace_finalization_retry_success",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(
            events[-1].payload["text"],
            "现在是北京时间 2026-04-20 12:30，我已经基于现有结果完成回答。",
        )
        self.assertEqual(
            [request.request_kind for request in llm.requests],
            ["interactive", "interactive", "finalization_retry"],
        )
        self.assertEqual(llm.requests[-1].available_tools, [])
        self.assertEqual(llm.requests[-1].requested_tool_name, None)
        self.assertEqual(llm.requests[-1].tool_result, None)
        self.assertIsNotNone(llm.requests[1].finalization_evidence_ledger)
        self.assertEqual(llm.requests[1].finalization_evidence_ledger.tool_call_count, 1)
        self.assertIsNotNone(llm.requests[-1].finalization_evidence_ledger)
        self.assertEqual(llm.requests[-1].finalization_evidence_ledger.tool_call_count, 1)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 3)
        self.assertEqual(run.finalization.assessment, "accepted")
        self.assertEqual(run.finalization.request_kind, "finalization_retry")
        self.assertEqual(run.finalization.required_evidence_count, 1)
        self.assertTrue(run.finalization.retry_triggered)
        self.assertEqual(run.finalization.missing_evidence_items, [])
        self.assertEqual(run.finalization.invalid_final_text, "工具执行失败，请重试。")

    def test_runtime_falls_back_to_recovery_fragments_when_retry_still_degrades(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        tools.register(
            "runtime",
            lambda payload: {
                "ok": True,
                "action": "context_status",
                "summary": "当前估算占用 1234/184000 tokens（1%）。",
                "estimated_usage": 1234,
                "effective_window": 184000,
                "current_run": {
                    "initial_input_tokens_estimate": 1234,
                    "peak_input_tokens_estimate": 1234,
                    "peak_stage": "initial_request",
                    "actual_cumulative_input_tokens": 0,
                    "actual_cumulative_output_tokens": 0,
                    "actual_cumulative_total_tokens": 0,
                    "actual_peak_input_tokens": None,
                    "actual_peak_output_tokens": None,
                    "actual_peak_total_tokens": None,
                    "actual_peak_stage": None,
                },
                "next_request_estimate": {
                    "input_tokens_estimate": 1234,
                    "effective_window_tokens": 184000,
                    "context_window_tokens": 200000,
                    "estimator_kind": "rough",
                    "degraded": True,
                },
                "context_window": 200000,
                "usage_percent": 1,
                "compaction_status": "none",
                "latest_checkpoint": "none",
                "estimate_source": "rough",
                "last_actual_usage": None,
                "last_completed_run": None,
                "model_profile": "minimax_coding",
            },
        )
        tools.register(
            "mcp",
            lambda payload: {
                "ok": True,
                "action": payload.get("action", "list"),
                "servers": [{"server_id": "github", "tool_count": 38, "state": "discovered"}],
                "result_text": '{"servers":[{"server_id":"github","tool_count":38,"state":"discovered"}]}',
            },
        )
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(tool_name="mcp", tool_payload={"action": "list"}),
                LLMReply(
                    final_text="当前可用 MCP 服务共 1 个。\n- 1. github（38 个工具，状态 discovered）"
                ),
                LLMReply(final_text="工具执行失败，请重试。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["time", "runtime", "mcp"],
        )

        events = runtime.run(
            session_id="sess_finalization_retry_fallback",
            message=(
                "请严格按顺序先调用 time 获取当前时间，"
                "再调用 runtime 查看当前 run 的 context_status，"
                "再调用 mcp 列出 github server 的可用工具。"
            ),
            trace_id="trace_finalization_retry_fallback",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("现在是北京时间", events[-1].payload["text"])
        self.assertIn("当前上下文使用详情", events[-1].payload["text"])
        self.assertIn("当前可用 MCP 服务共 1 个", events[-1].payload["text"])
        self.assertEqual(
            [request.request_kind for request in llm.requests],
            ["interactive", "interactive", "interactive", "interactive", "finalization_retry"],
        )
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 5)
        self.assertEqual(run.finalization.assessment, "retryable_degraded")
        self.assertEqual(run.finalization.request_kind, "finalization_retry")
        self.assertEqual(run.finalization.required_evidence_count, 3)
        self.assertTrue(run.finalization.retry_triggered)
        self.assertTrue(run.finalization.recovered_from_fragments)
        self.assertTrue(
            any("现在是北京时间" in item for item in run.finalization.missing_evidence_items)
        )
        self.assertTrue(
            any("当前上下文使用详情" in item for item in run.finalization.missing_evidence_items)
        )
        self.assertTrue(
            any("当前可用 MCP 服务共 1 个" in item for item in run.finalization.missing_evidence_items)
        )
        self.assertEqual(run.finalization.invalid_final_text, "工具执行失败，请重试。")

    def test_runtime_does_not_execute_additional_tool_calls_after_finalization_retry_starts(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(final_text="工具执行失败，请重试。"),
                LLMReply(tool_name="time", tool_payload={"timezone": "UTC"}),
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
            session_id="sess_finalization_retry_blocks_tools",
            message="先查一下北京时间，然后基于结果回答。",
            trace_id="trace_finalization_retry_blocks_tools",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("现在是北京时间", events[-1].payload["text"])
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 3)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["time"])

    def test_runtime_direct_renders_session_list_when_llm_finalizes(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="session",
                    tool_payload={"action": "list", "finalize_response": True},
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "list",
                "count": 1,
                "items": [
                    {
                        "session_id": "sess_dcce8f9c",
                        "session_title": "排查 Feishu 输出",
                        "message_count": 7,
                    }
                ],
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_session_list_direct",
            message="当前有哪些会话列表？",
            trace_id="trace_session_list_direct",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("当前有 1 个可见会话", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 1)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls[0]["tool_name"], "session")

    def test_runtime_routes_session_list_through_followup_llm_without_finalize_response(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="session", tool_payload={"action": "list"}),
                LLMReply(
                    final_text=(
                        "当前有 1 个可见会话。\n\n"
                        "| 序号 | 标题 | 状态 | 消息数 | 创建时间 | session_id |\n"
                        "| --- | --- | --- | --- | --- | --- |\n"
                        "| 1 | 排查 Feishu 输出 | unknown | 7 | - | sess_dcce8f9c |"
                    )
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "list",
                "count": 1,
                "items": [
                    {
                        "session_id": "sess_dcce8f9c",
                        "session_title": "排查 Feishu 输出",
                        "message_count": 7,
                    }
                ],
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_session_list_direct",
            message="当前有哪些会话列表？",
            trace_id="trace_session_list_direct",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("当前有 1 个可见会话", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(llm.requests[1].requested_tool_name, "session")
        self.assertEqual(llm.requests[1].requested_tool_payload, {"action": "list"})
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual(run.tool_calls[0]["tool_name"], "session")

    def test_runtime_recovers_after_wrong_session_list_tool_on_github_background_request(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="session", tool_payload={"action": "list"}),
                LLMReply(
                    tool_name="spawn_subagent",
                    tool_payload={
                        "task": "查询 tiezhuli001/codex-skills 最近一次提交时间",
                        "label": "github-last-commit",
                        "tool_profile": "standard",
                        "notify_on_finish": True,
                        "finalize_response": True,
                    },
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "list",
                "count": 1,
                "items": [
                    {
                        "session_id": "sess_dcce8f9c",
                        "session_title": "排查 Feishu 输出",
                        "message_count": 7,
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
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session", "spawn_subagent"],
        )

        events = runtime.run(
            session_id="sess_session_list_misroute_recover",
            message="开启子代理查询 github 上 tiezhuli001/codex-skills 最近一次提交是什么时候",
            trace_id="trace_session_list_misroute_recover",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "已受理，子 agent 正在后台执行，完成后会通知你结果。")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(llm.requests[1].requested_tool_name, "session")
        self.assertEqual(llm.requests[1].requested_tool_payload, {"action": "list"})
        self.assertEqual(len(llm.requests[1].tool_history), 1)
        self.assertEqual(llm.requests[1].tool_history[0].tool_name, "session")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["session", "spawn_subagent"])

    def test_runtime_direct_renders_session_new_for_single_intent_query(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="session", tool_payload={"action": "new", "finalize_response": True}),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "new",
                "session": {
                    "session_id": "sess_new_direct",
                    "message_count": 0,
                    "state": "created",
                    "created_at": "2026-04-20T06:00:00+00:00",
                },
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_session_new_direct",
            message="切换到新会话",
            trace_id="trace_session_new_direct",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("已切换到新会话", events[-1].payload["text"])
        self.assertNotIn("查看某个会话", events[-1].payload["text"])
        self.assertNotIn("新开一个会话", events[-1].payload["text"])
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls[0]["tool_name"], "session")

    def test_runtime_direct_renders_session_resume_for_single_intent_query(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="session",
                    tool_payload={
                        "action": "resume",
                        "session_id": "sess_dcce8f9c",
                        "finalize_response": True,
                    },
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "resume",
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
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_session_resume_direct",
            message="切换到会话 sess_dcce8f9c",
            trace_id="trace_session_resume_direct",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("已切换到会话 `sess_dcce8f9c`", events[-1].payload["text"])
        self.assertNotIn("查看某个会话", events[-1].payload["text"])
        self.assertNotIn("新开一个会话", events[-1].payload["text"])
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls[0]["tool_name"], "session")

    def test_runtime_rejects_unbacked_session_resume_claim_without_session_tool(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(final_text="已切换到会话 `sess_dcce8f9c`。"),
                LLMReply(final_text="已切换到会话 `sess_dcce8f9c`。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "resume",
                "transition": {
                    "mode": "switched",
                    "binding_changed": True,
                    "source_session_id": "sess_current",
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
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_session_resume_unbacked_claim",
            message="切换到会话 sess_dcce8f9c",
            trace_id="trace_session_resume_unbacked_claim",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "INVALID_FINAL_RESPONSE")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(llm.requests[1].request_kind, "contract_repair")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual(run.tool_calls, [])

    def test_runtime_repairs_unbacked_session_resume_claim_with_contract_repair(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(final_text="已切换到会话 `sess_dcce8f9c`。"),
                LLMReply(
                    tool_name="session",
                    tool_payload={
                        "action": "resume",
                        "session_id": "sess_dcce8f9c",
                        "finalize_response": True,
                    },
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "resume",
                "transition": {
                    "mode": "switched",
                    "binding_changed": True,
                    "source_session_id": "sess_current",
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
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_session_resume_contract_repair",
            message="切换到会话 sess_dcce8f9c",
            trace_id="trace_session_resume_contract_repair",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("已切换到会话 `sess_dcce8f9c`", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(llm.requests[1].request_kind, "contract_repair")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["session"])
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_selected_tool, "session")

    def test_runtime_repairs_unbacked_current_session_identity_claim_with_contract_repair(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(final_text="当前会话 id 是 sess_fake123。"),
                LLMReply(
                    tool_name="session",
                    tool_payload={
                        "action": "show",
                        "finalize_response": True,
                    },
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "show",
                "session": {
                    "session_id": "sess_current_real",
                    "session_title": "当前会话",
                    "session_preview": "当前绑定会话详情。",
                    "message_count": 12,
                    "state": "running",
                    "created_at": "2026-04-19T15:30:41+00:00",
                },
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_current_real",
            message="继续对话，告诉我当前会话 id，并只回复一句话。",
            trace_id="trace_current_session_id_contract_repair",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("sess_current_real", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(llm.requests[1].request_kind, "contract_repair")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_reason, "invalid_first_turn_finalization_contract")
        self.assertEqual(run.contract_repair_attempt_count, 1)
        self.assertEqual(run.contract_repair_outcome, "tool_call")
        self.assertEqual(run.contract_repair_selected_tool, "session")

    def test_runtime_rejects_session_resume_claim_with_wrong_session_id_after_real_tool(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="session", tool_payload={"action": "resume", "session_id": "sess_real"}),
                LLMReply(final_text="已切换到会话 `sess_wrong`。"),
                LLMReply(final_text="已切换到会话 `sess_wrong`。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "resume",
                "transition": {
                    "mode": "switched",
                    "binding_changed": True,
                    "source_session_id": "sess_current",
                    "target_session_id": payload["session_id"],
                    "compaction_attempted": False,
                    "compaction_succeeded": False,
                    "compaction_reason": None,
                },
                "session": {
                    "session_id": payload["session_id"],
                    "message_count": 72,
                    "state": "running",
                    "created_at": "2026-04-19T15:30:41+00:00",
                },
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_session_resume_wrong_claim",
            message="先切换到会话 sess_real，再总结当前状态。",
            trace_id="trace_session_resume_wrong_claim",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("已切换到会话 `sess_real`", events[-1].payload["text"])
        self.assertNotIn("sess_wrong", events[-1].payload["text"])
        self.assertEqual(
            [request.request_kind for request in llm.requests],
            ["interactive", "interactive", "finalization_retry"],
        )
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 3)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["session"])

    def test_runtime_does_not_repair_negated_session_reference_into_resume(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [LLMReply(final_text="这个会话目前有 72 条消息。")]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": payload.get("action") or "resume",
                "session": {"session_id": payload.get("session_id") or "sess_unknown"},
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_session_resume_negated",
            message="不要切换到 sess_dcce8f9c，只告诉我这个会话有多少消息",
            trace_id="trace_session_resume_negated",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "这个会话目前有 72 条消息。")
        self.assertEqual(len(llm.requests), 1)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls, [])

    def test_runtime_does_not_repair_past_tense_session_reference_into_resume(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [LLMReply(final_text="这个会话目前有 72 条消息。")]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": payload.get("action") or "resume",
                "session": {"session_id": payload.get("session_id") or "sess_unknown"},
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_session_resume_past_tense",
            message="我刚刚切换到 sess_dcce8f9c 了，现在告诉我这个会话有多少消息",
            trace_id="trace_session_resume_past_tense",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "这个会话目前有 72 条消息。")
        self.assertEqual(len(llm.requests), 1)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls, [])

    def test_runtime_rejects_unbacked_same_session_claim_without_session_tool(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(final_text="当前已在会话 `sess_dcce8f9c`。"),
                LLMReply(final_text="当前已在会话 `sess_dcce8f9c`。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "resume",
                "transition": {
                    "mode": "noop_same_session",
                    "binding_changed": False,
                    "source_session_id": "sess_dcce8f9c",
                    "target_session_id": "sess_dcce8f9c",
                    "compaction_attempted": False,
                    "compaction_succeeded": False,
                    "compaction_reason": None,
                },
                "session": {
                    "session_id": "sess_dcce8f9c",
                    "session_title": "排查 Feishu 输出",
                    "session_preview": "切换到问题会话继续排查",
                    "message_count": 72,
                    "state": "running",
                    "created_at": "2026-04-19T15:30:41+00:00",
                },
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_session_resume_same_unbacked_claim",
            message="继续当前会话",
            trace_id="trace_session_resume_same_unbacked_claim",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "INVALID_FINAL_RESPONSE")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(llm.requests[1].request_kind, "contract_repair")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual(run.tool_calls, [])

    def test_runtime_rejects_unbacked_new_session_claim_without_session_tool(self) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(final_text="已切换到新会话。"),
                LLMReply(final_text="已切换到新会话。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "new",
                "transition": {
                    "mode": "switched",
                    "binding_changed": True,
                    "source_session_id": "sess_current",
                    "target_session_id": "sess_new_direct",
                    "compaction_attempted": False,
                    "compaction_succeeded": False,
                    "compaction_reason": None,
                },
                "session": {
                    "session_id": "sess_new_direct",
                    "message_count": 0,
                    "state": "created",
                    "created_at": "2026-04-20T06:00:00+00:00",
                },
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session"],
        )

        events = runtime.run(
            session_id="sess_session_new_unbacked_claim",
            message="切换到新会话",
            trace_id="trace_session_new_unbacked_claim",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "INVALID_FINAL_RESPONSE")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(llm.requests[1].request_kind, "contract_repair")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual(run.tool_calls, [])

    def test_runtime_keeps_followup_after_spawn_subagent_inside_multi_step_request(
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
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="spawn_subagent",
                    tool_payload={
                        "task": "查询最近一次提交时间",
                        "label": "github-last-commit",
                        "tool_profile": "standard",
                        "notify_on_finish": True,
                    },
                ),
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(final_text="已受理子 agent 查询 GitHub；现在是北京时间 2026-04-20 12:30:00。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["spawn_subagent", "time"],
        )

        events = runtime.run(
            session_id="sess_spawn_multi_step",
            message="开子代理查 GitHub，再告诉我当前时间。",
            trace_id="trace_spawn_multi_step",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("现在是北京时间", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 3)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 3)
        self.assertEqual(
            [item["tool_name"] for item in run.tool_calls],
            ["spawn_subagent", "time"],
        )

    def test_runtime_repairs_unbacked_spawn_subagent_acceptance_claim_with_contract_repair(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(final_text="已受理，子 agent 正在后台执行，完成后会通知你结果。"),
                LLMReply(
                    tool_name="spawn_subagent",
                    tool_payload={
                        "task": "查询最近一次提交",
                        "label": "commit-check",
                        "tool_profile": "standard",
                        "notify_on_finish": True,
                        "finalize_response": True,
                    },
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
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
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["spawn_subagent"],
        )

        events = runtime.run(
            session_id="sess_spawn_unbacked_claim",
            message="开启子代理查询最近一次提交",
            trace_id="trace_spawn_unbacked_claim",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "已受理，子 agent 正在后台执行，完成后会通知你结果。")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(llm.requests[1].request_kind, "contract_repair")
        self.assertIsNone(llm.requests[1].finalization_evidence_ledger)
        self.assertEqual(
            llm.requests[1].invalid_final_text,
            "已受理，子 agent 正在后台执行，完成后会通知你结果。",
        )
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["spawn_subagent"])
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_outcome, "tool_call")
        self.assertEqual(run.contract_repair_selected_tool, "spawn_subagent")

    def test_runtime_rejects_unbacked_spawn_subagent_acceptance_claim_after_one_contract_repair(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(final_text="已受理，子 agent 正在后台执行，完成后会通知你结果。"),
                LLMReply(final_text="已受理，子 agent 正在后台执行，完成后会通知你结果。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
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
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["spawn_subagent"],
        )

        events = runtime.run(
            session_id="sess_spawn_unbacked_claim_failed_repair",
            message="开启子代理查询最近一次提交",
            trace_id="trace_spawn_unbacked_claim_failed_repair",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "INVALID_FINAL_RESPONSE")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(llm.requests[1].request_kind, "contract_repair")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual(run.tool_calls, [])
        self.assertTrue(run.contract_repair_triggered)
        self.assertEqual(run.contract_repair_attempt_count, 1)
        self.assertEqual(run.contract_repair_outcome, "invalid_final_response")
        self.assertIsNone(run.contract_repair_selected_tool)

    def test_runtime_rejects_spawn_subagent_running_wording_for_queued_result(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="spawn_subagent",
                    tool_payload={
                        "task": "查询最近一次提交时间",
                        "label": "github-last-commit",
                        "tool_profile": "standard",
                        "notify_on_finish": True,
                    },
                ),
                LLMReply(final_text="已受理，子 agent 正在后台执行，完成后会通知你结果。"),
                LLMReply(final_text="已受理，子 agent 正在后台执行，完成后会通知你结果。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "spawn_subagent",
            lambda payload: {
                "ok": True,
                "status": "accepted",
                "task_id": "task_spawn_ack",
                "child_session_id": "sess_child_ack",
                "effective_tool_profile": "standard",
                "queue_state": "queued",
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["spawn_subagent"],
        )

        events = runtime.run(
            session_id="sess_spawn_wrong_queue_wording",
            message="先开启子代理查询最近一次提交，再总结受理状态。",
            trace_id="trace_spawn_wrong_queue_wording",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("已进入队列", events[-1].payload["text"])
        self.assertNotIn("正在后台执行", events[-1].payload["text"])
        self.assertEqual(
            [request.request_kind for request in llm.requests],
            ["interactive", "interactive", "finalization_retry"],
        )
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 3)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["spawn_subagent"])

    def test_runtime_finishes_from_first_accepted_spawn_subagent_when_followup_repeats_same_tool(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="spawn_subagent",
                    tool_payload={
                        "task": "查询最近一次提交时间",
                        "label": "github-last-commit",
                        "tool_profile": "standard",
                        "notify_on_finish": True,
                    },
                ),
                LLMReply(
                    tool_name="spawn_subagent",
                    tool_payload={
                        "task": "查询最近一次提交时间",
                        "label": "github-last-commit",
                        "tool_profile": "standard",
                        "notify_on_finish": True,
                    },
                ),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
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
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["spawn_subagent"],
        )

        events = runtime.run(
            session_id="sess_spawn_duplicate_followup",
            message="开启子代理查询最近一次提交",
            trace_id="trace_spawn_duplicate_followup",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "已受理，子 agent 正在后台执行，完成后会通知你结果。")
        self.assertEqual(len(llm.requests), 2)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 2)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["spawn_subagent"])

    def test_runtime_keeps_followup_after_session_resume_inside_multi_step_request(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="session", tool_payload={"action": "resume", "session_id": "sess_dcce8f9c"}),
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(final_text="已切换到会话 `sess_dcce8f9c`；现在是北京时间 2026-04-20 12:30:00。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "resume",
                "transition": {
                    "mode": "switched",
                    "binding_changed": True,
                    "source_session_id": "sess_current",
                    "target_session_id": payload["session_id"],
                    "compaction_attempted": False,
                    "compaction_succeeded": False,
                    "compaction_reason": None,
                },
                "session": {
                    "session_id": payload["session_id"],
                    "message_count": 72,
                    "state": "running",
                    "created_at": "2026-04-19T15:30:41+00:00",
                },
            },
        )
        tools.register("time", run_time_tool)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session", "time"],
        )

        events = runtime.run(
            session_id="sess_session_resume_multi_step",
            message="先切换到 sess_dcce8f9c，再告诉我当前时间。",
            trace_id="trace_session_resume_multi_step",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("现在是北京时间", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 3)
        run = history.get(events[-1].run_id)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["session", "time"])

    def test_runtime_keeps_followup_after_session_resume_for_after_clause_request(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="session", tool_payload={"action": "resume", "session_id": "sess_dcce8f9c"}),
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(final_text="已切换到会话 `sess_dcce8f9c`；现在是北京时间 2026-04-20 12:30:00。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "session",
            lambda payload: {
                "action": "resume",
                "transition": {
                    "mode": "switched",
                    "binding_changed": True,
                    "source_session_id": "sess_current",
                    "target_session_id": payload["session_id"],
                    "compaction_attempted": False,
                    "compaction_succeeded": False,
                    "compaction_reason": None,
                },
                "session": {
                    "session_id": payload["session_id"],
                    "message_count": 72,
                    "state": "running",
                    "created_at": "2026-04-19T15:30:41+00:00",
                },
            },
        )
        tools.register("time", run_time_tool)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["session", "time"],
        )

        events = runtime.run(
            session_id="sess_session_resume_after_clause",
            message="切换到 sess_dcce8f9c 后告诉我当前时间。",
            trace_id="trace_session_resume_after_clause",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("现在是北京时间", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 3)
        run = history.get(events[-1].run_id)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["session", "time"])

    def test_runtime_keeps_followup_after_mcp_call_inside_multi_step_request(
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
                        "arguments": {"owner": "CloudWide851", "repo": "easy-agent", "perPage": 1},
                    },
                ),
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(final_text="CloudWide851/easy-agent 最近一次提交已获取；当前上下文使用详情：当前估算占用 100/184000 tokens（0%）。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "ok": True,
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": payload["arguments"],
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"}}}]',
                "is_error": False,
            },
        )
        tools.register(
            "runtime",
            lambda payload: {
                "ok": True,
                "action": "context_status",
                "summary": "当前估算占用 100/184000 tokens（0%）。",
                "effective_window": 184000,
                "usage_percent": 0,
                "next_request_estimate": {
                    "input_tokens_estimate": 100,
                    "estimator_kind": "tokenizer",
                },
                "compaction_status": "none",
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["mcp", "runtime"],
        )

        events = runtime.run(
            session_id="sess_mcp_multi_step",
            message="先查 GitHub 最近提交，再总结当前上下文。",
            trace_id="trace_mcp_multi_step",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("当前上下文使用详情", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 3)
        run = history.get(events[-1].run_id)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["mcp", "runtime"])

    def test_runtime_keeps_followup_after_mcp_call_for_after_clause_request(
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
                        "arguments": {"owner": "CloudWide851", "repo": "easy-agent", "perPage": 1},
                    },
                ),
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(final_text="CloudWide851/easy-agent 最近一次提交已获取；当前上下文使用详情：当前估算占用 100/184000 tokens（0%）。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        tools.register(
            "mcp",
            lambda payload: {
                "ok": True,
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": payload["arguments"],
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"}}}]',
                "is_error": False,
            },
        )
        tools.register(
            "runtime",
            lambda payload: {
                "ok": True,
                "action": "context_status",
                "summary": "当前估算占用 100/184000 tokens（0%）。",
                "effective_window": 184000,
                "usage_percent": 0,
                "next_request_estimate": {
                    "input_tokens_estimate": 100,
                    "estimator_kind": "tokenizer",
                },
                "compaction_status": "none",
            },
        )
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["mcp", "runtime"],
        )

        events = runtime.run(
            session_id="sess_mcp_after_clause",
            message="查 GitHub 最近提交后总结当前上下文。",
            trace_id="trace_mcp_after_clause",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("当前上下文使用详情", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 3)
        run = history.get(events[-1].run_id)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["mcp", "runtime"])

    def test_runtime_keeps_followup_after_spawn_subagent_for_and_clause_request(
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
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="spawn_subagent",
                    tool_payload={
                        "task": "查询最近一次提交时间",
                        "label": "github-last-commit",
                        "tool_profile": "standard",
                        "notify_on_finish": True,
                    },
                ),
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(final_text="已受理子 agent 查询 GitHub；现在是北京时间 2026-04-20 12:30:00。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["spawn_subagent", "time"],
        )

        events = runtime.run(
            session_id="sess_spawn_and_clause",
            message="开子代理并告诉我当前时间。",
            trace_id="trace_spawn_and_clause",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertIn("现在是北京时间", events[-1].payload["text"])
        self.assertEqual(len(llm.requests), 3)
        run = history.get(events[-1].run_id)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["spawn_subagent", "time"])

    def test_runtime_keeps_first_turn_live_time_query_on_model_selected_path(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(final_text="现在是北京时间 21:37。"),
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
            session_id="sess_time_contract_repair",
            message="请告诉我现在几点了？",
            trace_id="trace_time_contract_repair",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "现在是北京时间 21:37。")
        self.assertEqual(len(llm.requests), 1)
        self.assertIsNone(llm.requests[0].requested_tool_name)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls, [])

    def test_runtime_keeps_first_turn_live_runtime_query_on_model_selected_path(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(final_text="当前上下文大约 3000 tokens。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["runtime"],
        )

        events = runtime.run(
            session_id="sess_runtime_contract_repair",
            message="当前会话的上下文窗口使用情况",
            trace_id="trace_runtime_contract_repair",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "当前上下文大约 3000 tokens。")
        self.assertEqual(len(llm.requests), 1)
        self.assertIsNone(llm.requests[0].requested_tool_name)
        run = history.get(events[-1].run_id)
        self.assertEqual(run.llm_request_count, 1)
        self.assertEqual(run.tool_calls, [])

    def test_runtime_direct_renders_commit_text_without_followup_llm_even_if_more_replies_exist(
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
                        "finalize_response": True,
                    },
                ),
                LLMReply(final_text="工具执行失败，请重试。"),
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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

    def test_runtime_direct_renders_commit_text_without_followup_even_if_llm_would_time_out(
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
                    "finalize_response": True,
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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

    def test_runtime_direct_renders_commit_text_without_followup_even_if_llm_would_request_disallowed_tool(
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
                    "finalize_response": True,
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
        self.assertEqual(len(run.tool_calls), 1)
        self.assertEqual(run.tool_calls[0]["tool_name"], "broken_tool")
        self.assertEqual(run.tool_calls[0]["tool_payload"], {"value": "x"})
        self.assertFalse(run.tool_calls[0]["tool_result"]["ok"])
        self.assertTrue(run.tool_calls[0]["tool_result"]["is_error"])
        self.assertEqual(
            run.tool_calls[0]["tool_result"]["error_code"],
            "TOOL_EXECUTION_FAILED",
        )
        self.assertIn("tool blew up", run.tool_calls[0]["tool_result"]["error_text"])

    def test_runtime_recovers_from_shared_evidence_when_final_text_stays_empty_after_retry(
        self,
    ) -> None:
        tools = ToolRegistry()
        tools.register("mock_search", lambda payload: {"result_text": f"search:{payload['query']}"})
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="mock_search", tool_payload={"query": "now"}),
                LLMReply(final_text=""),
                LLMReply(final_text=""),
            ]
        )
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["mock_search"],
        )

        events = runtime.run(
            session_id="sess_empty",
            message="tell me now",
            trace_id="trace_empty",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "search:now")
        self.assertEqual(
            [request.request_kind for request in llm.requests],
            ["interactive", "interactive", "finalization_retry"],
        )
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "succeeded")
        self.assertIsNone(run.error_code)

    def test_runtime_exposes_provider_specific_error_codes_for_provider_failures(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            tools = ToolRegistry()
            history = InMemoryRunHistory()
            _, store = build_self_improve_adapter(Path(tmpdir))
            runtime = RuntimeLoop(
                FailingLLMClient(),
                tools,
                history,
                self_improve_recorder=SelfImproveRecorder(store),
            )

            events = runtime.run(
                session_id="sess_fail", message="hello", trace_id="trace_fail"
            )
            failures = store.list_recent_failures(agent_id="main", limit=10)

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(events[-1].payload["text"], "暂时没有生成可见回复，请重试。")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].error_code, "PROVIDER_TRANSPORT_ERROR")

    def test_runtime_invokes_post_commit_callback_after_error_turn_when_failure_trigger_is_created(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            tools = ToolRegistry()
            history = InMemoryRunHistory()
            _, store = build_self_improve_adapter(Path(tmpdir))
            recorder = SelfImproveRecorder(store)
            recorder.record_failure(
                agent_id="main",
                run_id="run_seed_1",
                trace_id="trace_seed_1",
                session_id="sess_seed",
                error_code="PROVIDER_TRANSPORT_ERROR",
                error_stage="llm",
                summary="provider timed out",
                message="hello",
            )
            callback_calls: list[str] = []
            runtime = RuntimeLoop(
                FailingLLMClient(),
                tools,
                history,
                self_improve_recorder=recorder,
                self_improve_post_commit_callback=lambda *, agent_id: callback_calls.append(agent_id),
            )

            events = runtime.run(
                session_id="sess_fail", message="hello", trace_id="trace_fail"
            )
            triggers = store.list_review_triggers(agent_id="main", limit=10, status="pending")

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(callback_calls, ["main"])
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].trigger_kind, "lesson_failure_burst")

    def test_runtime_keeps_runtime_loop_failed_for_unknown_internal_exceptions(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            tools = ToolRegistry()
            history = InMemoryRunHistory()
            _, store = build_self_improve_adapter(Path(tmpdir))
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
            failures = store.list_recent_failures(agent_id="main", limit=10)

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "RUNTIME_LOOP_FAILED")
        self.assertEqual(events[-1].payload["text"], "暂时没有生成可见回复，请重试。")
        run = history.get(events[0].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "RUNTIME_LOOP_FAILED")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].error_code, "RUNTIME_LOOP_FAILED")

    def test_runtime_swallow_post_commit_callback_failure_after_success(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(
            ScriptedLLMClient([LLMReply(final_text="done")]),
            tools,
            history,
            self_improve_post_commit_callback=lambda *, agent_id: (_ for _ in ()).throw(RuntimeError(f"boom:{agent_id}")),
        )

        events = runtime.run(
            session_id="sess_success_post_commit",
            message="hello",
            trace_id="trace_success_post_commit",
        )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        run = history.get(events[-1].run_id)
        self.assertEqual(run.status, "succeeded")

    def test_runtime_returns_controlled_error_when_tool_loop_limit_is_exceeded(
        self,
    ) -> None:
        class EndlessToolLLMClient:
            provider_name = "scripted"
            model_name = "endless-tool"

            def complete(self, request):  # noqa: ANN001
                return LLMReply(tool_name="time", tool_payload={"timezone": "UTC"})

        tools = ToolRegistry()
        tools.register("time", run_time_tool)
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(EndlessToolLLMClient(), tools, history)
        runtime.max_tool_rounds = 1
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
            allowed_tools=["time"],
        )

        events = runtime.run(
            session_id="sess_tool_loop_limit",
            message="keep calling time",
            trace_id="trace_tool_loop_limit",
            agent=agent,
        )

        self.assertEqual([event.event_type for event in events], ["progress", "error"])
        self.assertEqual(events[-1].payload["code"], "TOOL_LOOP_LIMIT_EXCEEDED")
        self.assertEqual(events[-1].payload["text"], "tool_loop_limit_exceeded")
        run = history.get(events[-1].run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "TOOL_LOOP_LIMIT_EXCEEDED")

    def test_runtime_records_recovery_after_later_success_on_compatible_message(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            tools = ToolRegistry()
            history = InMemoryRunHistory()
            _, store = build_self_improve_adapter(Path(tmpdir))
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
            recoveries = store.list_recent_recoveries(agent_id="main", limit=10)

        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0].recovery_kind, "same_fingerprint_success")
