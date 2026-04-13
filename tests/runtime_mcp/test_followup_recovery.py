import asyncio
import os
import subprocess
import sys
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import anyio

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.mcp.client import MCPClient
from marten_runtime.mcp.discovery import discover_mcp_tools
from marten_runtime.mcp.loader import load_mcp_servers
from marten_runtime.mcp.models import MCPServerSpec, MCPToolSpec
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.tools.builtins.mcp_tool import run_mcp_tool
from marten_runtime.tools.registry import ToolRegistry
from tests.support.mcp_fixtures import build_server_map, find_free_port, wait_for_port


class RuntimeMCPFollowupRecoveryTests(unittest.TestCase):

    def _find_free_port(self) -> int:
        return find_free_port()

    def _wait_for_port(self, port: int, timeout_s: float = 5.0) -> None:
        wait_for_port(port, timeout_s)

    def _build_stdio_echo_server(self, *, fixture: Path | None = None) -> MCPServerSpec:
        kwargs = {
            "server_id": "stdio-echo",
            "transport": "stdio",
            "backend_id": "stdio-test",
            "command": sys.executable,
            "args": [str(fixture)] if fixture else ["-c", "print('unused')"],
        }
        if fixture is not None:
            kwargs["timeout_ms"] = 5_000
        return MCPServerSpec(
            **kwargs,
        )

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

        server = self._build_stdio_echo_server()
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

        server = self._build_stdio_echo_server()
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

        server = self._build_stdio_echo_server()
        client = BrokenOnExitClient([server])

        result = client.call_tool(server.server_id, "echo", {"query": "release notes"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["result_text"], "echo:ok")

    def test_discovery_can_run_inside_asyncio_thread(self) -> None:
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_stdio_server.py"
        server = self._build_stdio_echo_server(fixture=fixture)
        client = MCPClient([server])

        async def run_discovery() -> dict[str, dict[str, object]]:
            return discover_mcp_tools([server], client)

        discovery = asyncio.run(run_discovery())

        self.assertEqual(discovery["stdio-echo"]["state"], "discovered")
        self.assertEqual([tool.name for tool in server.tools], ["echo"])

    def test_runtime_can_call_real_stdio_mcp_tool_without_static_tool_list(self) -> None:
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_stdio_server.py"
        server = self._build_stdio_echo_server(fixture=fixture)
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

    def test_runtime_can_call_real_stdio_mcp_tool(self) -> None:
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_stdio_server.py"
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
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_streamable_http_server.py"
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
