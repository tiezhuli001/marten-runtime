import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.tools.builtins.skill_tool import run_skill_tool
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.registry import ToolRegistry
from marten_runtime.skills.service import SkillService
from tests.support.scripted_llm import AuthFailingLLMClient, FailingLLMClient


class RuntimeLoopForcedRouteTests(unittest.TestCase):

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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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

    def test_runtime_returns_provider_auth_error_when_provider_auth_fails_before_any_tool(
        self,
    ) -> None:
        tools = ToolRegistry()
        history = InMemoryRunHistory()
        llm = AuthFailingLLMClient()
        runtime = RuntimeLoop(llm, tools, history)
        agent = AgentSpec(
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
                    "agents: [main]\n"
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
                agent_id="main",
                role="general_assistant",
                app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
            agent_id="main",
            role="general_assistant",
            app_id="main_agent",
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
