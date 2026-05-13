import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from marten_runtime.mcp.loader import load_mcp_servers
from marten_runtime.mcp.normalize import normalize_mcp_request
from marten_runtime.mcp.models import MCPServerSpec
from marten_runtime.mcp.models import MCPToolSpec


class MCPTests(unittest.TestCase):
    def test_normalize_call_merges_top_level_query_into_arguments(self) -> None:
        server = MCPServerSpec(
            server_id="github",
            tools=[MCPToolSpec(name="search_code", description="search code")],
        )

        normalized = normalize_mcp_request(
            {"github": server},
            {
                "action": "call",
                "server_id": "github",
                "tool_name": "search_code",
                "query": "feishu path:src repo:tiezhuli001/marten-runtime",
                "arguments": {"path": "src/"},
            },
        )

        self.assertEqual(
            normalized.arguments,
            {
                "query": "feishu path:src repo:tiezhuli001/marten-runtime",
                "path": "src/",
            },
        )

    def test_normalize_call_maps_search_q_alias_and_cleans_github_repo_arguments(self) -> None:
        server = MCPServerSpec(
            server_id="github",
            tools=[
                MCPToolSpec(name="search_code", description="search code"),
                MCPToolSpec(name="list_commits", description="list commits"),
                MCPToolSpec(name="get_file_contents", description="get file contents"),
            ],
        )

        search = normalize_mcp_request(
            {"github": server},
            {
                "action": "call",
                "server_id": "github",
                "tool_name": "search_code",
                "arguments": {"q": "feishu card renderer", "language": None},
            },
        )
        commits = normalize_mcp_request(
            {"github": server},
            {
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {
                    "repo": "tiezhuli001/marten-runtime",
                    "author": None,
                    "per_page": 5,
                    "sha": "main",
                },
            },
        )
        file_contents = normalize_mcp_request(
            {"github": server},
            {
                "action": "call",
                "server_id": "github",
                "tool_name": "get_file_contents",
                "arguments": {
                    "repo": "tiezhuli001/marten-runtime",
                    "path": "README.md",
                    "branch": "main",
                },
            },
        )

        self.assertEqual(search.arguments, {"query": "feishu card renderer"})
        self.assertEqual(
            commits.arguments,
            {
                "owner": "tiezhuli001",
                "repo": "marten-runtime",
                "per_page": 5,
                "sha": "main",
            },
        )
        self.assertEqual(
            file_contents.arguments,
            {
                "owner": "tiezhuli001",
                "repo": "marten-runtime",
                "path": "README.md",
                "ref": "main",
            },
        )

    def test_normalize_noncanonical_action_with_explicit_tool_name_to_call(self) -> None:
        server = MCPServerSpec(
            server_id="github",
            tools=[MCPToolSpec(name="search_code", description="search code")],
        )

        normalized = normalize_mcp_request(
            {"github": server},
            {
                "action": "search_code",
                "server_id": "github",
                "tool_name": "search_code",
                "arguments": {
                    "query": "飞书 卡片 失败 摘要 alert",
                    "repo": "tiezhuli001/marten-runtime",
                },
            },
        )

        self.assertEqual(normalized.action, "call")
        self.assertEqual(normalized.server_id, "github")
        self.assertEqual(normalized.tool_name, "search_code")
        self.assertEqual(
            normalized.arguments,
            {
                "query": "飞书 卡片 失败 摘要 alert",
                "repo": "tiezhuli001/marten-runtime",
            },
        )

    def test_loader_allows_missing_optional_mcps_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            servers = load_mcp_servers(str(base / "mcps.json"))

            self.assertEqual(servers, [])

    def test_loader_keeps_mcps_json_only_server_with_minimal_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            compat = base / "mcps.json"
            compat.write_text(
                json.dumps(
                    {
                        "servers": {
                            "github": {
                                "transport": "stdio",
                                "command": "docker",
                                "args": ["run"],
                                "env": {
                                    "GITHUB_PERSONAL_ACCESS_TOKEN": "$GITHUB_PERSONAL_ACCESS_TOKEN",
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            servers = load_mcp_servers(str(compat))

            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].server_id, "github")
            self.assertEqual(servers[0].transport, "stdio")
            self.assertEqual(servers[0].timeout_ms, 10000)
            self.assertEqual(servers[0].tools, [])
            self.assertEqual(servers[0].source_layers, ["mcps.json"])

    def test_loader_supports_tools_declared_in_mcps_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            compat = base / "mcps.json"
            compat.write_text(
                json.dumps(
                    {
                        "servers": {
                            "github-trending": {
                                "transport": "stdio",
                                "command": "python",
                                "args": ["-m", "demo"],
                                "tools": [
                                    {
                                        "name": "trending_repositories",
                                        "description": "Fetch GitHub trending repositories.",
                                    }
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            servers = load_mcp_servers(str(compat))

            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].tools[0].name, "trending_repositories")
            self.assertEqual(
                servers[0].tools[0].description,
                "Fetch GitHub trending repositories.",
            )

    def test_mcps_json_literal_env_value_is_authoritative(self) -> None:
        server = MCPServerSpec(
            server_id="github",
            transport="stdio",
            command="docker",
            args=["run"],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": "literal-token"},
        )

        from marten_runtime.mcp.client import MCPClient

        client = MCPClient([server], env={"GITHUB_PERSONAL_ACCESS_TOKEN": "process-token"})

        self.assertEqual(
            client._resolve_server_env(server)["GITHUB_PERSONAL_ACCESS_TOKEN"],
            "literal-token",
        )

    def test_persistent_stdio_session_is_recreated_after_startup_failure(self) -> None:
        from marten_runtime.mcp.client import MCPClient

        server = MCPServerSpec(
            server_id="github",
            transport="stdio",
            command="docker",
            args=["run"],
            tools=[MCPToolSpec(name="search_code", description="search")],
        )
        client = MCPClient([server], env={})
        attempts = {"count": 0}

        class BrokenSession:
            def __init__(self, *_args, **_kwargs):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    self._startup_error = RuntimeError("boom")
                else:
                    self._startup_error = None

            def run_list_tools(self, **_kwargs):
                if self._startup_error is not None:
                    raise self._startup_error
                return [MCPToolSpec(name="search_code", description="search")]

            def close(self):
                pass

        with patch("marten_runtime.mcp.client._PersistentStdioSession", BrokenSession):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                client.list_tools("github")
            tools = client.list_tools("github")

        self.assertEqual(attempts["count"], 2)
        self.assertEqual([tool.name for tool in tools], ["search_code"])



    def test_persistent_stdio_session_recreates_closed_cached_session(self) -> None:
        from marten_runtime.mcp.client import MCPClient

        server = MCPServerSpec(
            server_id="github",
            transport="stdio",
            command="docker",
            args=["run"],
            tools=[MCPToolSpec(name="search_code", description="search")],
        )
        client = MCPClient([server], env={})
        attempts = {"count": 0}

        class CachedSession:
            def __init__(self, *_args, **_kwargs):
                attempts["count"] += 1
                self.closed = attempts["count"] == 1

            def is_closed(self):
                return self.closed

            def run_list_tools(self, **_kwargs):
                if self.closed:
                    raise AssertionError("closed cached session must not be reused")
                return [MCPToolSpec(name="search_code", description="search")]

            def close(self):
                self.closed = True

        with patch("marten_runtime.mcp.client._PersistentStdioSession", CachedSession):
            client._persistent_stdio_sessions["github"] = CachedSession()
            tools = client.list_tools("github")

        self.assertEqual(attempts["count"], 2)
        self.assertEqual([tool.name for tool in tools], ["search_code"])

    def test_persistent_stdio_close_does_not_close_running_loop_after_join_timeout(self) -> None:
        from marten_runtime.mcp.client import _PersistentStdioSession

        server = MCPServerSpec(
            server_id="github",
            transport="stdio",
            command="docker",
            args=["run"],
        )

        class DummyClient:
            pass

        session = object.__new__(_PersistentStdioSession)
        closed = {"set": False}
        stop_called = {"value": False}

        class ClosedFlag:
            def is_set(self):
                return closed["set"]

            def set(self):
                closed["set"] = True

        class ReadyFlag:
            def is_set(self):
                return True

        class RunningLoop:
            def is_running(self):
                return True

            def is_closed(self):
                return False

            def call_soon_threadsafe(self, callback):  # noqa: ANN001
                callback()

            def close(self):
                raise AssertionError("running loop must not be closed")

        class AliveThread:
            def join(self, timeout=None):  # noqa: ANN001
                del timeout

            def is_alive(self):
                return True

        class StopEvent:
            def set(self):
                stop_called["value"] = True

        session._client = DummyClient()
        session._server = server
        session._loop = RunningLoop()
        session._ready = ReadyFlag()
        session._closed = ClosedFlag()
        session._startup_error = None
        session._session = object()
        session._stop_async = StopEvent()
        session._op_lock = None
        session._thread = AliveThread()

        session.close()

        self.assertTrue(closed["set"])
        self.assertTrue(stop_called["value"])

    def test_persistent_stdio_startup_failure_closes_partial_stack(self) -> None:
        import asyncio
        from contextlib import asynccontextmanager

        from marten_runtime.mcp.client import _PersistentStdioSession

        server = MCPServerSpec(
            server_id="github",
            transport="stdio",
            command="docker",
            args=["run"],
        )
        closed = {"value": False}

        @asynccontextmanager
        async def broken_manager(_params):
            try:
                yield object(), object()
            finally:
                closed["value"] = True

        class BrokenClient:
            def _resolve_server_env(self, _server):
                return {}

            def _stdio_client_manager(self, params):
                return broken_manager(params)

            def _effective_timeout_seconds(self, _server, _override, _deadline):
                return 0.1

        session = _PersistentStdioSession(BrokenClient(), server)  # type: ignore[arg-type]
        try:
            with self.assertRaises(Exception):
                session.run_list_tools(timeout_seconds_override=1)
        finally:
            session.close()

        self.assertTrue(closed["value"])


if __name__ == "__main__":
    unittest.main()
