import unittest
from types import SimpleNamespace

from marten_runtime.mcp.client import MCPClient
from marten_runtime.mcp.models import MCPServerSpec, MCPToolSpec
from marten_runtime.mcp.normalize import normalize_mcp_request
from marten_runtime.mcp.request_models import NormalizedMCPRequest
from marten_runtime.tools.builtins.mcp_tool import build_mcp_capability_catalog, run_mcp_tool
from tests.support.mcp_fixtures import build_server_map


class RuntimeMCPGitHubShortcutTests(unittest.TestCase):

    def _server_map(self, *servers: MCPServerSpec) -> dict[str, MCPServerSpec]:
        return build_server_map(*servers)

    def _github_server(self, *tools: MCPToolSpec) -> MCPServerSpec:
        return MCPServerSpec(
            server_id="github",
            transport="stdio",
            backend_id="github",
            tools=list(tools),
        )

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

    def test_normalize_mcp_request_accepts_list_commit_alias_payloads(self) -> None:
        server_map = self._server_map(
            self._github_server(MCPToolSpec(name="list_commits", description="List repo commits."))
        )
        cases = [
            {
                "payload": {
                    "action": "call",
                    "server": "github",
                    "tool": "list_commits",
                    "parameters": '{"owner":"jiji262","repo":"ai-agent-021","per_page":1}',
                },
                "expected_arguments": {"owner": "jiji262", "repo": "ai-agent-021", "per_page": 1},
            },
            {
                "payload": {
                    "action": "call",
                    "server": "github",
                    "tool": "list_commits",
                    "input": '{"repo":"jiji262/ai-agent-021","perPage":1}',
                },
                "expected_arguments": {"owner": "jiji262", "repo": "ai-agent-021", "per_page": 1},
            },
        ]

        for case in cases:
            with self.subTest(payload=case["payload"]):
                request = normalize_mcp_request(server_map, case["payload"])
                self.assertEqual(request.server_id, "github")
                self.assertEqual(request.tool_name, "list_commits")
                self.assertEqual(request.arguments, case["expected_arguments"])

    def test_normalize_mcp_request_does_not_repair_unknown_github_alias_tool_name(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                self._github_server(
                    MCPToolSpec(name="search_repositories", description="Search repositories.")
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

    def test_normalize_mcp_request_maps_search_repositories_q_alias_to_query(self) -> None:
        request = normalize_mcp_request(
            self._server_map(
                self._github_server(
                    MCPToolSpec(name="search_repositories", description="Search GitHub repositories.")
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
                self._github_server(
                    MCPToolSpec(name="list_commits", description="List GitHub commits.")
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
