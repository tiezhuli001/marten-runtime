import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.automation.models import AutomationJob
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.tools.builtins.automation_tool import run_automation_tool
from marten_runtime.tools.registry import ToolRegistry
from tests.support.domain_builders import build_automation_adapter


class RuntimeLoopAutomationRouteTests(unittest.TestCase):

    def test_runtime_uses_llm_first_for_natural_language_automation_list_query(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = build_automation_adapter(Path(tmpdir))
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
            adapter, store = build_automation_adapter(Path(tmpdir))
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

    def test_runtime_allows_main_agent_to_register_automation_via_family_tool(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = build_automation_adapter(Path(tmpdir))
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
            adapter, store = build_automation_adapter(Path(tmpdir))
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
