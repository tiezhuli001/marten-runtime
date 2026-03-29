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
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.tools.registry import ToolRegistry


class RuntimeMCPTests(unittest.TestCase):
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
        for tool in server.tools:
            tools.register(
                tool.name,
                lambda payload, server_id=server.server_id, tool_name=tool.name: client.call_tool(
                    server_id,
                    tool_name,
                    payload,
                ),
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
            allowed_tools=["mcp:*"],
        )

        events = runtime.run(session_id="sess_mcp", message="find release notes", trace_id="trace_mcp", agent=agent)

        self.assertEqual(discovery["stdio-echo"]["state"], "discovered")
        self.assertEqual([tool.name for tool in server.tools], ["echo"])
        self.assertEqual([event.event_type for event in events], ["progress", "final"])
        self.assertEqual(events[-1].payload["text"], "echo=ok")
        self.assertIn("echo", llm.requests[0].tool_snapshot.mcp_tools)

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
