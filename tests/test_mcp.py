import json
import tempfile
import unittest
from pathlib import Path

from marten_runtime.mcp.loader import load_mcp_servers
from marten_runtime.mcp.models import MCPServerSpec


class MCPTests(unittest.TestCase):
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
