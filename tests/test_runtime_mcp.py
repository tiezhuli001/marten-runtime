import os
import asyncio
import socket
import subprocess
import sys
import time
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import anyio

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.mcp.client import MCPClient
from marten_runtime.mcp.discovery import discover_mcp_tools
from marten_runtime.mcp.models import MCPServerSpec, MCPToolSpec
from marten_runtime.mcp.loader import load_mcp_servers
from marten_runtime.mcp.normalize import normalize_mcp_request
from marten_runtime.mcp.request_models import NormalizedMCPRequest
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.tools.builtins.mcp_tool import (
    build_mcp_capability_catalog,
    run_mcp_tool,
)
from marten_runtime.tools.registry import ToolRegistry


class RuntimeMCPTests(unittest.TestCase):
    def test_normalized_mcp_request_requires_action(self) -> None:
        with self.assertRaisesRegex(ValueError, "action"):
            NormalizedMCPRequest(
                action="",
                server_id=None,
                tool_name=None,
                arguments={},
            )

    def test_normalized_mcp_request_keeps_canonical_fields(self) -> None:
        request = NormalizedMCPRequest(
            action="call",
            server_id="mock-search",
            tool_name="mock_search",
            arguments={"query": "release notes"},
        )

        self.assertEqual(
            request.model_dump(),
            {
                "action": "call",
                "server_id": "mock-search",
                "tool_name": "mock_search",
                "arguments": {"query": "release notes"},
            },
        )

    def test_normalize_mcp_request_maps_alias_fields_to_canonical_shape(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                MCPServerSpec(
                    server_id="mock-search",
                    transport="mock",
                    backend_id="remote-mock",
                    tools=[MCPToolSpec(name="mock_search", description="Mock search tool.")],
                )
            ),
            {
                "action": "call",
                "server_id": "mock-search",
                "tool": "mock_search",
                "params": {"query": "release notes"},
            },
        )

        self.assertEqual(request.tool_name, "mock_search")
        self.assertEqual(request.arguments, {"query": "release notes"})

    def test_normalize_mcp_request_accepts_server_and_parameters_aliases(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                MCPServerSpec(
                    server_id="github",
                    transport="stdio",
                    backend_id="remote-github",
                    tools=[MCPToolSpec(name="list_commits", description="List repo commits.")],
                )
            ),
            {
                "action": "call",
                "server": "github",
                "tool": "list_commits",
                "parameters": '{"owner":"jiji262","repo":"ai-agent-021","per_page":1}',
            },
        )

        self.assertEqual(request.server_id, "github")
        self.assertEqual(request.tool_name, "list_commits")
        self.assertEqual(
            request.arguments,
            {"owner": "jiji262", "repo": "ai-agent-021", "per_page": 1},
        )

    def test_normalize_mcp_request_accepts_input_alias_and_repo_slug_for_list_commits(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                MCPServerSpec(
                    server_id="github",
                    transport="stdio",
                    backend_id="remote-github",
                    tools=[MCPToolSpec(name="list_commits", description="List repo commits.")],
                )
            ),
            {
                "action": "call",
                "server": "github",
                "tool": "list_commits",
                "input": '{"repo":"jiji262/ai-agent-021","perPage":1}',
            },
        )

        self.assertEqual(request.server_id, "github")
        self.assertEqual(request.tool_name, "list_commits")
        self.assertEqual(
            request.arguments,
            {"owner": "jiji262", "repo": "ai-agent-021", "per_page": 1},
        )

    def test_normalize_mcp_request_does_not_repair_unknown_github_alias_tool_name(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                MCPServerSpec(
                    server_id="github",
                    transport="stdio",
                    backend_id="remote-github",
                    tools=[MCPToolSpec(name="search_repositories", description="Search repositories.")],
                )
            ),
            {
                "action": "call",
                "server_id": "github",
                "tool_name": "github_get_repository",
                "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
            },
        )

        self.assertEqual(request.tool_name, "github_get_repository")

    def test_normalize_mcp_request_uses_empty_dict_for_missing_arguments(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                MCPServerSpec(
                    server_id="mock-search",
                    transport="mock",
                    backend_id="remote-mock",
                    tools=[MCPToolSpec(name="mock_search", description="Mock search tool.")],
                )
            ),
            {
                "action": "call",
                "server_id": "mock-search",
                "tool_name": "mock_search",
            },
        )

        self.assertEqual(request.arguments, {})

    def test_client_can_call_tool_inside_asyncio_thread(self) -> None:
        class AsyncSafeClient(MCPClient):
            @asynccontextmanager
            async def _open_session(self, server):  # type: ignore[override]
                del server

                class FakeTextContent:
                    def model_dump(self, mode: str = "json", by_alias: bool = True):
                        del mode, by_alias
                        return {"type": "text", "text": "echo:async"}

                class FakeSession:
                    async def call_tool(self, tool_name, arguments, read_timeout_seconds):
                        del tool_name, arguments, read_timeout_seconds
                        return SimpleNamespace(
                            content=[FakeTextContent()],
                            structuredContent=None,
                            isError=False,
                        )

                yield FakeSession()

        server = MCPServerSpec(
            server_id="stdio-echo",
            transport="stdio",
            backend_id="stdio-test",
            command=sys.executable,
            args=["-c", "print('unused')"],
        )
        client = AsyncSafeClient([server])

        async def run_call() -> dict:
            return client.call_tool(server.server_id, "echo", {"query": "release notes"})

        result = asyncio.run(run_call())

        self.assertTrue(result["ok"])
        self.assertEqual(result["result_text"], "echo:async")

    def test_client_ignores_stdio_broken_resource_on_list_tools_teardown(self) -> None:
        class BrokenOnExitClient(MCPClient):
            @asynccontextmanager
            async def _open_session(self, server):  # type: ignore[override]
                del server

                class FakeSession:
                    async def list_tools(self):
                        return SimpleNamespace(
                            tools=[SimpleNamespace(name="echo", description="Echo over stdio.")]
                        )

                yield FakeSession()
                raise BaseExceptionGroup("shutdown", [anyio.BrokenResourceError()])

        server = MCPServerSpec(
            server_id="stdio-echo",
            transport="stdio",
            backend_id="stdio-test",
            command=sys.executable,
            args=["-c", "print('unused')"],
        )
        client = BrokenOnExitClient([server])

        tools = client.list_tools(server.server_id)

        self.assertEqual([tool.name for tool in tools], ["echo"])

    def test_client_ignores_stdio_broken_resource_on_call_tool_teardown(self) -> None:
        class BrokenOnExitClient(MCPClient):
            @asynccontextmanager
            async def _open_session(self, server):  # type: ignore[override]
                del server

                class FakeTextContent:
                    def model_dump(self, mode: str = "json", by_alias: bool = True):
                        del mode, by_alias
                        return {"type": "text", "text": "echo:ok"}

                class FakeSession:
                    async def call_tool(self, tool_name, arguments, read_timeout_seconds):
                        del tool_name, arguments, read_timeout_seconds
                        return SimpleNamespace(
                            content=[FakeTextContent()],
                            structuredContent=None,
                            isError=False,
                        )

                yield FakeSession()
                raise BaseExceptionGroup("shutdown", [anyio.BrokenResourceError()])

        server = MCPServerSpec(
            server_id="stdio-echo",
            transport="stdio",
            backend_id="stdio-test",
            command=sys.executable,
            args=["-c", "print('unused')"],
        )
        client = BrokenOnExitClient([server])

        result = client.call_tool(server.server_id, "echo", {"query": "release notes"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["result_text"], "echo:ok")

    def test_discovery_can_run_inside_asyncio_thread(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "mcp_stdio_server.py"
        server = MCPServerSpec(
            server_id="stdio-echo",
            transport="stdio",
            backend_id="stdio-test",
            command=sys.executable,
            args=[str(fixture)],
            timeout_ms=5_000,
        )
        client = MCPClient([server])

        async def run_discovery() -> dict[str, dict[str, object]]:
            return discover_mcp_tools([server], client)

        discovery = asyncio.run(run_discovery())

        self.assertEqual(discovery["stdio-echo"]["state"], "discovered")
        self.assertEqual([tool.name for tool in server.tools], ["echo"])

    def test_runtime_can_call_real_stdio_mcp_tool_without_static_tool_list(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "mcp_stdio_server.py"
        server = MCPServerSpec(
            server_id="stdio-echo",
            transport="stdio",
            backend_id="stdio-test",
            command=sys.executable,
            args=[str(fixture)],
            timeout_ms=5_000,
        )
        client = MCPClient([server])
        discovery = discover_mcp_tools([server], client)
        tools = ToolRegistry()
        tools.register(
            "mcp",
            lambda payload: run_mcp_tool(payload, [server], client, discovery),
        )
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "stdio-echo",
                        "tool_name": "echo",
                        "arguments": {"query": "release notes"},
                    },
                ),
                LLMReply(final_text="echo=ok"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, InMemoryRunHistory())
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        events = runtime.run(session_id="sess_mcp", message="find release notes", trace_id="trace_mcp", agent=agent)

        self.assertEqual(discovery["stdio-echo"]["state"], "discovered")
        self.assertEqual([tool.name for tool in server.tools], ["echo"])
        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "echo=ok")
        self.assertEqual(llm.requests[0].available_tools, ["mcp"])

    def test_runtime_mcp_transient_transport_retry_succeeds_without_extra_llm_round(self) -> None:
        server = MCPServerSpec(
            server_id="github",
            transport="mock",
            backend_id="github",
            tools=[MCPToolSpec(name="list_commits", description="List GitHub commits.")],
        )

        class FlakyClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, dict]] = []

            def call_tool(self, server_id: str, tool_name: str, payload: dict) -> dict:
                self.calls.append((server_id, tool_name, payload))
                if len(self.calls) < 3:
                    return {
                        "server_id": server_id,
                        "tool_name": tool_name,
                        "payload": payload,
                        "result_text": 'failed to list commits: Get "https://api.github.com/repos/llt22/talkio/commits?page=1&per_page=1": EOF',
                        "ok": False,
                        "is_error": True,
                    }
                return {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "result_text": '[{"sha":"abc","commit":{"message":"release: v2.7.2"}}]',
                    "ok": True,
                    "is_error": False,
                }

        client = FlakyClient()
        discovery = {"github": {"state": "configured", "tool_count": 1, "error": None}}
        tools = ToolRegistry()
        tools.register(
            "mcp",
            lambda payload: run_mcp_tool(payload, [server], client, discovery),
        )
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
                LLMReply(final_text="最近一次提交是 release: v2.7.2。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, InMemoryRunHistory())
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        with patch("marten_runtime.tools.builtins.mcp_tool.time.sleep") as sleep_mock:
            events = runtime.run(
                session_id="sess_mcp_retry_success",
                message="查看 talkio 最近提交",
                trace_id="trace_mcp_retry_success",
                agent=agent,
            )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "最近一次提交是 release: v2.7.2。")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(
            [call.args[0] for call in sleep_mock.call_args_list],
            [3.0, 5.0],
        )
        self.assertTrue(llm.requests[1].tool_history[0].tool_result["ok"])

    def test_runtime_mcp_transient_transport_retry_still_returns_failure_to_followup_llm(self) -> None:
        server = MCPServerSpec(
            server_id="github",
            transport="mock",
            backend_id="github",
            tools=[MCPToolSpec(name="list_commits", description="List GitHub commits.")],
        )

        class AlwaysTransientFailureClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, dict]] = []

            def call_tool(self, server_id: str, tool_name: str, payload: dict) -> dict:
                self.calls.append((server_id, tool_name, payload))
                return {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "result_text": 'failed to list commits: Get "https://api.github.com/repos/llt22/talkio/commits?page=1&per_page=1": EOF',
                    "ok": False,
                    "is_error": True,
                }

        client = AlwaysTransientFailureClient()
        discovery = {"github": {"state": "configured", "tool_count": 1, "error": None}}
        tools = ToolRegistry()
        tools.register(
            "mcp",
            lambda payload: run_mcp_tool(payload, [server], client, discovery),
        )
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
                LLMReply(final_text="这次 GitHub MCP 调用失败了，请稍后重试。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, InMemoryRunHistory())
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["mcp"],
        )

        with patch("marten_runtime.tools.builtins.mcp_tool.time.sleep") as sleep_mock:
            events = runtime.run(
                session_id="sess_mcp_retry_fail",
                message="查看 talkio 最近提交",
                trace_id="trace_mcp_retry_fail",
                agent=agent,
            )

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "这次 GitHub MCP 调用失败了，请稍后重试。")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(
            [call.args[0] for call in sleep_mock.call_args_list],
            [3.0, 5.0],
        )
        self.assertTrue(llm.requests[1].tool_history[0].tool_result["is_error"])

    def test_run_mcp_tool_heals_stale_discovery_after_successful_call(self) -> None:
        server = MCPServerSpec(
            server_id="github",
            transport="stdio",
            backend_id="github",
            tools=[],
        )

        class RecoveringClient:
            def __init__(self) -> None:
                self.list_tools_calls = 0
                self.call_tool_calls = 0

            def list_tools(self, server_id: str) -> list[MCPToolSpec]:
                self.list_tools_calls += 1
                return [MCPToolSpec(name="list_commits", description="List GitHub commits.")]

            def call_tool(self, server_id: str, tool_name: str, payload: dict) -> dict:
                self.call_tool_calls += 1
                return {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "result_text": '[{"sha":"abc","commit":{"message":"release: v2.7.2"}}]',
                    "ok": True,
                    "is_error": False,
                }

        client = RecoveringClient()
        discovery = {"github": {"state": "unavailable", "tool_count": 0, "error": "startup EOF"}}

        result = run_mcp_tool(
            {
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "llt22", "repo": "talkio", "perPage": 1},
            },
            [server],
            client,  # type: ignore[arg-type]
            discovery,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(client.call_tool_calls, 1)
        self.assertEqual(client.list_tools_calls, 1)
        self.assertEqual(discovery["github"]["state"], "discovered")
        self.assertEqual(discovery["github"]["tool_count"], 1)
        self.assertEqual(discovery["github"]["error"], None)
        self.assertEqual([tool.name for tool in server.tools], ["list_commits"])

    def test_mcp_family_tool_can_infer_single_tool_server_from_query_payload(self) -> None:
        server = MCPServerSpec(
            server_id="mock-search",
            transport="mock",
            backend_id="remote-mock",
            tools=[MCPToolSpec(name="mock_search", description="Mock search tool.")],
        )
        client = MCPClient([server])

        result = run_mcp_tool(
            {"query": "release notes"},
            [server],
            client,
            {"mock-search": {"state": "configured", "tool_count": 1, "error": None}},
        )

        self.assertEqual(result["action"], "call")
        self.assertEqual(result["server_id"], "mock-search")
        self.assertEqual(result["tool_name"], "mock_search")
        self.assertEqual(result["arguments"]["query"], "release notes")

    def test_mcp_family_tool_accepts_json_string_arguments(self) -> None:
        server = MCPServerSpec(
            server_id="mock-search",
            transport="mock",
            backend_id="remote-mock",
            tools=[MCPToolSpec(name="mock_search", description="Mock search tool.")],
        )
        client = MCPClient([server])

        result = run_mcp_tool(
            {
                "action": "call",
                "server_id": "mock-search",
                "tool_name": "mock_search",
                "arguments": '{"query":"release notes"}',
            },
            [server],
            client,
            {"mock-search": {"state": "configured", "tool_count": 1, "error": None}},
        )

        self.assertEqual(result["arguments"]["query"], "release notes")

    def test_mcp_family_tool_retries_twice_on_transient_transport_error_result(self) -> None:
        server = MCPServerSpec(
            server_id="github",
            transport="mock",
            backend_id="github",
            tools=[MCPToolSpec(name="list_commits", description="List GitHub commits.")],
        )

        class FlakyClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, dict]] = []

            def call_tool(self, server_id: str, tool_name: str, payload: dict) -> dict:
                self.calls.append((server_id, tool_name, payload))
                if len(self.calls) < 3:
                    return {
                        "server_id": server_id,
                        "tool_name": tool_name,
                        "payload": payload,
                        "result_text": 'failed to list commits: Get "https://api.github.com/repos/llt22/talkio/commits?page=1&per_page=1": EOF',
                        "ok": False,
                        "is_error": True,
                    }
                return {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "result_text": '[{"sha":"abc"}]',
                    "ok": True,
                    "is_error": False,
                }

        client = FlakyClient()

        with patch("marten_runtime.tools.builtins.mcp_tool.time.sleep") as sleep_mock:
            result = run_mcp_tool(
                {
                    "action": "call",
                    "server_id": "github",
                    "tool_name": "list_commits",
                    "arguments": {"owner": "llt22", "repo": "talkio", "perPage": 1},
                },
                [server],
                client,  # type: ignore[arg-type]
                {"github": {"state": "configured", "tool_count": 1, "error": None}},
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["is_error"])
        self.assertEqual(result["result_text"], '[{"sha":"abc"}]')
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(
            [call.args[0] for call in sleep_mock.call_args_list],
            [3.0, 5.0],
        )

    def test_mcp_family_tool_returns_failure_after_two_transient_retries(self) -> None:
        server = MCPServerSpec(
            server_id="github",
            transport="mock",
            backend_id="github",
            tools=[MCPToolSpec(name="list_commits", description="List GitHub commits.")],
        )

        class AlwaysTransientFailureClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, dict]] = []

            def call_tool(self, server_id: str, tool_name: str, payload: dict) -> dict:
                self.calls.append((server_id, tool_name, payload))
                return {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "result_text": 'failed to list commits: Get "https://api.github.com/repos/llt22/talkio/commits?page=1&per_page=1": EOF',
                    "ok": False,
                    "is_error": True,
                }

        client = AlwaysTransientFailureClient()

        with patch("marten_runtime.tools.builtins.mcp_tool.time.sleep") as sleep_mock:
            result = run_mcp_tool(
                {
                    "action": "call",
                    "server_id": "github",
                    "tool_name": "list_commits",
                    "arguments": {"owner": "llt22", "repo": "talkio", "perPage": 1},
                },
                [server],
                client,  # type: ignore[arg-type]
                {"github": {"state": "configured", "tool_count": 1, "error": None}},
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["is_error"])
        self.assertIn("EOF", result["result_text"])
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(
            [call.args[0] for call in sleep_mock.call_args_list],
            [3.0, 5.0],
        )

    def test_mcp_family_tool_does_not_retry_non_transport_error_result(self) -> None:
        server = MCPServerSpec(
            server_id="github",
            transport="mock",
            backend_id="github",
            tools=[MCPToolSpec(name="list_commits", description="List GitHub commits.")],
        )

        class SemanticFailureClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, dict]] = []

            def call_tool(self, server_id: str, tool_name: str, payload: dict) -> dict:
                self.calls.append((server_id, tool_name, payload))
                return {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "result_text": "repository not found",
                    "ok": False,
                    "is_error": True,
                }

        client = SemanticFailureClient()

        result = run_mcp_tool(
            {
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "llt22", "repo": "talkio", "perPage": 1},
            },
            [server],
            client,  # type: ignore[arg-type]
            {"github": {"state": "configured", "tool_count": 1, "error": None}},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["result_text"], "repository not found")
        self.assertEqual(len(client.calls), 1)

    def test_mcp_family_tool_retries_twice_on_transient_transport_exception(self) -> None:
        server = MCPServerSpec(
            server_id="github",
            transport="mock",
            backend_id="github",
            tools=[MCPToolSpec(name="list_commits", description="List GitHub commits.")],
        )

        class FlakyExceptionClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, dict]] = []

            def call_tool(self, server_id: str, tool_name: str, payload: dict) -> dict:
                self.calls.append((server_id, tool_name, payload))
                if len(self.calls) < 3:
                    raise RuntimeError('Get "https://api.github.com/repos/llt22/talkio/commits?page=1&per_page=1": EOF')
                return {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "result_text": '[{"sha":"abc"}]',
                    "ok": True,
                    "is_error": False,
                }

        client = FlakyExceptionClient()

        with patch("marten_runtime.tools.builtins.mcp_tool.time.sleep") as sleep_mock:
            result = run_mcp_tool(
                {
                    "action": "call",
                    "server_id": "github",
                    "tool_name": "list_commits",
                    "arguments": {"owner": "llt22", "repo": "talkio", "perPage": 1},
                },
                [server],
                client,  # type: ignore[arg-type]
                {"github": {"state": "configured", "tool_count": 1, "error": None}},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result_text"], '[{"sha":"abc"}]')
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(
            [call.args[0] for call in sleep_mock.call_args_list],
            [3.0, 5.0],
        )

    def test_normalize_mcp_request_accepts_json_string_arguments(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                MCPServerSpec(
                    server_id="mock-search",
                    transport="mock",
                    backend_id="remote-mock",
                    tools=[MCPToolSpec(name="mock_search", description="Mock search tool.")],
                )
            ),
            {
                "action": "call",
                "server_id": "mock-search",
                "tool_name": "mock_search",
                "arguments": '{"query":"release notes"}',
            },
        )

        self.assertEqual(request.arguments, {"query": "release notes"})

    def test_normalize_mcp_request_maps_search_repositories_q_alias_to_query(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                MCPServerSpec(
                    server_id="github",
                    transport="stdio",
                    backend_id="github",
                    tools=[MCPToolSpec(name="search_repositories", description="Search GitHub repositories.")],
                )
            ),
            {
                "action": "call",
                "server_id": "github",
                "tool_name": "search_repositories",
                "arguments": {"q": "agent framework", "sort": "stars", "per_page": 10},
            },
        )

        self.assertEqual(
            request.arguments,
            {"query": "agent framework", "sort": "stars", "per_page": 10},
        )

    def test_normalize_mcp_request_treats_commit_action_name_as_call_tool(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                MCPServerSpec(
                    server_id="github",
                    transport="stdio",
                    backend_id="github",
                    tools=[MCPToolSpec(name="list_commits", description="List GitHub commits.")],
                )
            ),
            {
                "action": "list_commits",
                "server_name": "github",
                "owner": "jiji262",
                "repo": "ai-agent-021",
                "per_page": "1",
            },
        )

        self.assertEqual(request.action, "call")
        self.assertEqual(request.server_id, "github")
        self.assertEqual(request.tool_name, "list_commits")
        self.assertEqual(
            request.arguments,
            {"owner": "jiji262", "repo": "ai-agent-021", "per_page": "1"},
        )

    def test_build_mcp_capability_catalog_exposes_exact_server_and_tool_surface(self) -> None:
        catalog = build_mcp_capability_catalog(
            [
                MCPServerSpec(
                    server_id="github",
                    transport="stdio",
                    backend_id="github",
                    source_layers=["mcps.json"],
                    tools=[
                        MCPToolSpec(name="search_repositories", description="Search repositories."),
                        MCPToolSpec(name="list_commits", description="List commits."),
                    ],
                )
            ],
            {"github": {"state": "discovered", "tool_count": 2, "error": None}},
        )

        self.assertIn('Use {"action":"call","server_id":"<exact server_id>","tool_name":"<exact tool name>","arguments":{...}}', catalog or "")
        self.assertIn("do not rename or invent aliases", (catalog or "").lower())
        self.assertIn("search_repositories", catalog or "")
        self.assertIn("list_commits", catalog or "")

    def test_normalize_mcp_request_infers_server_from_unique_tool_name(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                MCPServerSpec(
                    server_id="mock-search",
                    transport="mock",
                    backend_id="remote-mock",
                    tools=[MCPToolSpec(name="mock_search", description="Mock search tool.")],
                ),
                MCPServerSpec(
                    server_id="other-search",
                    transport="mock",
                    backend_id="remote-mock",
                    tools=[MCPToolSpec(name="other_search", description="Other search tool.")],
                ),
            ),
            {
                "action": "call",
                "tool_name": "mock_search",
                "arguments": {"query": "release notes"},
            },
        )

        self.assertEqual(request.server_id, "mock-search")

    def test_normalize_mcp_request_infers_single_tool_name_on_server(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                MCPServerSpec(
                    server_id="mock-search",
                    transport="mock",
                    backend_id="remote-mock",
                    tools=[MCPToolSpec(name="mock_search", description="Mock search tool.")],
                )
            ),
            {
                "action": "call",
                "server_id": "mock-search",
                "arguments": {"query": "release notes"},
            },
        )

        self.assertEqual(request.tool_name, "mock_search")

    def test_normalize_mcp_request_rejects_ambiguous_server_inference(self) -> None:
        with self.assertRaisesRegex(ValueError, "server_id is required"):
            normalize_mcp_request(
                self._server_map(
                    MCPServerSpec(
                        server_id="mock-search",
                        transport="mock",
                        backend_id="remote-mock",
                        tools=[MCPToolSpec(name="search_a", description="Search A.")],
                    ),
                    MCPServerSpec(
                        server_id="other-search",
                        transport="mock",
                        backend_id="remote-mock",
                        tools=[MCPToolSpec(name="search_b", description="Search B.")],
                    ),
                ),
                {"query": "release notes"},
            )

    def test_normalize_mcp_request_rejects_ambiguous_tool_name_matches(self) -> None:
        with self.assertRaisesRegex(ValueError, "ambiguous tool_name: mock_search"):
            normalize_mcp_request(
                self._server_map(
                    MCPServerSpec(
                        server_id="mock-search-a",
                        transport="mock",
                        backend_id="remote-mock",
                        tools=[MCPToolSpec(name="mock_search", description="Search A.")],
                    ),
                    MCPServerSpec(
                        server_id="mock-search-b",
                        transport="mock",
                        backend_id="remote-mock",
                        tools=[MCPToolSpec(name="mock_search", description="Search B.")],
                    ),
                ),
                {
                    "action": "call",
                    "tool_name": "mock_search",
                    "arguments": {"query": "release notes"},
                },
            )

    def test_mcp_family_tool_accepts_underscore_alias_for_hyphenated_server_id(self) -> None:
        server = MCPServerSpec(
            server_id="github-trending",
            transport="mock",
            backend_id="github-trending",
            tools=[MCPToolSpec(name="trending_repositories", description="Fetch trending repositories.")],
        )

        class RecordingClient(MCPClient):
            def __init__(self, servers: list[MCPServerSpec]):
                super().__init__(servers)
                self.calls: list[tuple[str, str, dict]] = []

            def call_tool(self, server_id: str, tool_name: str, arguments: dict) -> dict:  # type: ignore[override]
                self.calls.append((server_id, tool_name, arguments))
                return {
                    "ok": True,
                    "is_error": False,
                    "result_text": '{"items":[]}',
                }

        client = RecordingClient([server])

        result = run_mcp_tool(
            {
                "action": "call",
                "server_id": "github_trending",
                "tool_name": "trending_repositories",
                "arguments": {"since": "daily", "limit": 10},
            },
            [server],
            client,
            {"github-trending": {"state": "discovered"}},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["server_id"], "github-trending")
        self.assertEqual(
            client.calls,
            [("github-trending", "trending_repositories", {"since": "daily", "limit": 10})],
        )

    def _server_map(self, *servers: MCPServerSpec) -> dict[str, MCPServerSpec]:
        return {server.server_id: server for server in servers}

    def test_runtime_can_call_real_stdio_mcp_tool(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "mcp_stdio_server.py"
        server = MCPServerSpec(
            server_id="stdio-echo",
            transport="stdio",
            backend_id="stdio-test",
            command=sys.executable,
            args=[str(fixture)],
            timeout_ms=5_000,
            tools=[MCPToolSpec(name="echo", description="Echo over stdio.")],
        )
        client = MCPClient([server])
        tools = ToolRegistry()
        tools.register(
            "echo",
            lambda payload: client.call_tool(server.server_id, "echo", payload),
            source_kind="mcp",
            server_id=server.server_id,
            backend_id=server.backend_id,
        )
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="echo", tool_payload={"query": "release notes"}),
                LLMReply(final_text="echo=ok"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, InMemoryRunHistory())
        agent = AgentSpec(
            agent_id="assistant",
            role="general_assistant",
            app_id="example_assistant",
            allowed_tools=["echo"],
        )

        events = runtime.run(session_id="sess_mcp", message="find release notes", trace_id="trace_mcp", agent=agent)

        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "echo=ok")
        self.assertEqual(events[0].trace_id, "trace_mcp")
        self.assertIn("echo", llm.requests[0].tool_snapshot.mcp_tools)

    def test_mcp_client_can_call_streamable_http_server(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "mcp_streamable_http_server.py"
        port = self._find_free_port()
        process = subprocess.Popen(
            [sys.executable, str(fixture)],
            env={**os.environ, "MCP_TEST_PORT": str(port)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_port(port)
            server = MCPServerSpec(
                server_id="http-echo",
                transport="http",
                backend_id="http-test",
                url=f"http://127.0.0.1:{port}/mcp",
                timeout_ms=5_000,
                tools=[MCPToolSpec(name="echo", description="Echo over HTTP.")],
            )
            client = MCPClient([server])

            tools = client.list_tools(server.server_id)
            result = client.call_tool(server.server_id, "echo", {"query": "release notes"})

            self.assertIn("echo", [item.name for item in tools])
            self.assertTrue(result["ok"])
            self.assertEqual(result["result_text"], "http:release notes")
        finally:
            process.terminate()
            process.wait(timeout=5)

    def _find_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _wait_for_port(self, port: int, timeout_s: float = 5.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    return
            time.sleep(0.05)
        raise TimeoutError(f"port {port} did not open in time")


if __name__ == "__main__":
    unittest.main()
