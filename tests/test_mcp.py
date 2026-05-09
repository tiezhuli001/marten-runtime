import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
