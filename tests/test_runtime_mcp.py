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
from marten_runtime.tools.builtins.mcp_tool import run_mcp_tool
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
