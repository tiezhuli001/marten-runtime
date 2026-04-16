import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
