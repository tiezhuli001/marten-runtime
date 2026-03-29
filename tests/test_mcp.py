import json
import tempfile
import unittest
from pathlib import Path

from marten_runtime.mcp.availability import MCPAvailability
from marten_runtime.mcp.loader import load_mcp_servers
from marten_runtime.mcp.models import MCPServerSpec
from marten_runtime.mcp.registry import MCPRegistry
from marten_runtime.mcp.schema_cache import MCPSchemaCacheEntry
from marten_runtime.mcp.session import MCPClientSession


class MCPTests(unittest.TestCase):
    def test_loader_allows_missing_optional_mcps_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = base / "mcp.toml"
            config.write_text(
                """
                compat_import = "mcps.json"

                [[servers]]
                server_id = "mock-search"
                transport = "mock"
                backend_id = "remote-mock"
                enabled = true

                [[servers.tools]]
                name = "mock_search"
                description = "demo"
                """,
                encoding="utf-8",
            )

            servers = load_mcp_servers(str(config), str(base / "mcps.json"))

            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].server_id, "mock-search")
            self.assertEqual(servers[0].source_layers, ["config/mcp.toml"])

    def test_loader_keeps_mcps_json_only_server_with_default_policy(self) -> None:
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
            config = base / "mcp.toml"
            config.write_text('compat_import = "mcps.json"\n', encoding="utf-8")

            servers = load_mcp_servers(str(config), str(compat))

            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].server_id, "github")
            self.assertEqual(servers[0].transport, "stdio")
            self.assertEqual(servers[0].session_mode, "shared_worker")
            self.assertEqual(servers[0].availability_policy, "fail_closed")
            self.assertEqual(servers[0].schema_cache_ttl_s, 300)
            self.assertEqual(servers[0].allowed_agents, [])
            self.assertEqual(servers[0].tools, [])
            self.assertEqual(servers[0].source_layers, ["mcps.json"])

    def test_loader_falls_back_to_example_when_mcp_toml_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            compat = base / "mcps.json"
            compat.write_text(json.dumps({"servers": {}}), encoding="utf-8")
            example = base / "mcp.example.toml"
            example.write_text(
                """
                compat_import = "mcps.json"

                [[servers]]
                server_id = "mock-search"
                transport = "mock"
                backend_id = "remote-mock"
                enabled = true

                [[servers.tools]]
                name = "mock_search"
                description = "demo"
                """,
                encoding="utf-8",
            )

            servers = load_mcp_servers(str(base / "mcp.toml"), str(compat))

            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].server_id, "mock-search")
            self.assertEqual(servers[0].source_layers, ["config/mcp.example.toml"])

    def test_loader_merges_mcps_json_and_toml_policy(self) -> None:
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
                                "args": [
                                    "run",
                                    "-i",
                                    "--rm",
                                    "-e",
                                    "GITHUB_PERSONAL_ACCESS_TOKEN",
                                    "ghcr.io/github/github-mcp-server",
                                ],
                                "env": {
                                    "GITHUB_PERSONAL_ACCESS_TOKEN": "$GITHUB_PERSONAL_ACCESS_TOKEN",
                                },
                                "cwd": None,
                                "timeout_seconds": 30,
                                "adapter": "github",
                            },
                            "http-echo": {
                                "transport": "http",
                                "url": "http://127.0.0.1:8765/mcp",
                                "headers": {
                                    "Authorization": "Bearer demo",
                                },
                                "timeout_seconds": 12,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = base / "mcp.toml"
            config.write_text(
                """
                compat_import = "mcps.json"

                [[servers]]
                server_id = "github"
                backend_id = "github-mcp"
                enabled = true
                timeout_ms = 45000
                availability_policy = "fail_closed"
                session_mode = "shared_worker"
                schema_cache_ttl_s = 300
                circuit_breaker_policy = "5_failures_60s"
                allowed_agents = ["assistant"]

                [[servers.tools]]
                name = "github_search_repositories"
                description = "Search repositories on GitHub."

                [[servers]]
                server_id = "http-echo"
                backend_id = "http-mcp"
                enabled = true
                session_mode = "per_run"
                schema_cache_ttl_s = 120
                circuit_breaker_policy = "3_failures_30s"

                [[servers.tools]]
                name = "echo"
                description = "Echo query over HTTP MCP."
                """,
                encoding="utf-8",
            )

            servers = load_mcp_servers(str(config), str(compat))
            by_id = {server.server_id: server for server in servers}

            self.assertEqual(sorted(by_id.keys()), ["github", "http-echo"])
            self.assertEqual(by_id["github"].command, "docker")
            self.assertEqual(by_id["github"].args[0], "run")
            self.assertEqual(by_id["github"].env["GITHUB_PERSONAL_ACCESS_TOKEN"], "$GITHUB_PERSONAL_ACCESS_TOKEN")
            self.assertEqual(by_id["github"].timeout_ms, 45000)
            self.assertEqual(by_id["github"].tools[0].name, "github_search_repositories")
            self.assertEqual(by_id["http-echo"].url, "http://127.0.0.1:8765/mcp")
            self.assertEqual(by_id["http-echo"].headers["Authorization"], "Bearer demo")
            self.assertEqual(by_id["http-echo"].timeout_ms, 12000)
            self.assertEqual(by_id["http-echo"].session_mode, "per_run")

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

    def test_registry_availability_session_and_cache_are_tracked(self) -> None:
        server = MCPServerSpec(
            server_id="mock-search",
            transport="mock",
            backend_id="remote-mock",
            enabled=True,
            session_mode="shared_worker",
        )
        registry = MCPRegistry()
        registry.register(server)
        availability = MCPAvailability(server_id=server.server_id, state="healthy")
        session = MCPClientSession(
            server_id=server.server_id,
            session_mode=server.session_mode,
            session_key="sess_mcp_1",
        )
        cache_entry = MCPSchemaCacheEntry(
            server_id=server.server_id,
            config_snapshot_id="cfg_bootstrap",
            expires_at=1234567890,
        )

        self.assertEqual(registry.list_servers(), ["mock-search"])
        self.assertEqual(availability.state, "healthy")
        self.assertEqual(session.session_mode, "shared_worker")
        self.assertEqual(cache_entry.config_snapshot_id, "cfg_bootstrap")


if __name__ == "__main__":
    unittest.main()
