import sys
import json
import unittest
from datetime import datetime
from pathlib import Path

from marten_runtime.mcp.client import MCPClient
from marten_runtime.mcp.models import MCPServerSpec
from marten_runtime.mcp_servers.github_trending import (
    TrendingRepositoriesRequest,
    parse_trending_repositories,
)


class GitHubTrendingMCPTests(unittest.TestCase):
    def setUp(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        self.fixture_html = (repo_root / "tests" / "fixtures" / "github_trending_daily.html").read_text(
            encoding="utf-8"
        )

    def test_request_defaults_to_daily_and_top_ten(self) -> None:
        request = TrendingRepositoriesRequest()

        self.assertEqual(request.since, "daily")
        self.assertEqual(request.limit, 10)
        self.assertIsNone(request.language)

    def test_request_normalizes_all_language_to_none(self) -> None:
        request = TrendingRepositoriesRequest(language="all")

        self.assertIsNone(request.language)

    def test_request_rejects_invalid_since(self) -> None:
        with self.assertRaisesRegex(ValueError, "since"):
            TrendingRepositoriesRequest(since="hourly")

    def test_request_rejects_non_positive_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit"):
            TrendingRepositoriesRequest(limit=0)

    def test_request_rejects_limit_above_max_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit"):
            TrendingRepositoriesRequest(limit=26)

    def test_parser_extracts_repositories_from_fixture(self) -> None:
        items = parse_trending_repositories(self.fixture_html, limit=10)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].rank, 1)
        self.assertEqual(items[0].full_name, "owner-one/repo-one")
        self.assertEqual(items[0].url, "https://github.com/owner-one/repo-one")
        self.assertEqual(items[0].description, "Repo one description.")
        self.assertEqual(items[0].language, "Python")
        self.assertEqual(items[0].stars_total, 1234)
        self.assertEqual(items[0].stars_period, 321)
        self.assertEqual(items[1].rank, 2)
        self.assertEqual(items[1].full_name, "owner-two/repo-two")

    def test_parser_respects_limit(self) -> None:
        items = parse_trending_repositories(self.fixture_html, limit=1)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].rank, 1)

    def test_parser_prefers_repository_anchor_over_star_button_and_svg_noise(self) -> None:
        html = """
        <article class="Box-row">
          <div class="float-right d-flex">
            <a href="/login?return_to=%2Fgoogle-ai-edge%2Fgallery" class="btn">
              <svg><path d="M8 .25 16 42"></path></svg>
              Star
            </a>
          </div>
          <h2 class="h3 lh-condensed">
            <a href="/google-ai-edge/gallery" class="Link">
              <svg><path d="M1 2"></path></svg>
              <span class="text-normal">google-ai-edge /</span>
              gallery
            </a>
          </h2>
          <p>A gallery that showcases on-device ML/GenAI use cases and allows people to try and use models locally.</p>
          <div class="f6 color-fg-muted mt-2">
            <span itemprop="programmingLanguage">Kotlin</span>
            <a href="/google-ai-edge/gallery/stargazers"><svg><path d="M123 456"></path></svg>16,421</a>
            <span class="d-inline-block float-sm-right"><svg><path d="M789"></path></svg>286 stars today</span>
          </div>
        </article>
        """

        items = parse_trending_repositories(html, limit=10)

        self.assertEqual(items[0].url, "https://github.com/google-ai-edge/gallery")
        self.assertEqual(items[0].full_name, "google-ai-edge/gallery")
        self.assertEqual(items[0].stars_total, 16421)
        self.assertEqual(items[0].stars_period, 286)

    def test_stdio_mcp_server_exposes_trending_tool_and_returns_schema(self) -> None:
        server = MCPServerSpec(
            server_id="github-trending",
            transport="stdio",
            backend_id="github-trending",
            command=sys.executable,
            args=["-m", "marten_runtime.mcp_servers.github_trending"],
            timeout_ms=5_000,
            env={"GITHUB_TRENDING_FIXTURE_PATH": str(Path(__file__).resolve().parent / "fixtures" / "github_trending_daily.html")},
        )
        client = MCPClient([server])

        tools = client.list_tools(server.server_id)
        result = client.call_tool(server.server_id, "trending_repositories", {"since": "daily", "limit": 2})

        self.assertEqual([tool.name for tool in tools], ["trending_repositories"])
        self.assertIn("today", tools[0].description.lower())
        self.assertIn("stars_period", tools[0].description)
        self.assertIn("fetched_at", tools[0].description)
        self.assertIn("fetched_at_display", tools[0].description)
        self.assertIn("rank", tools[0].description)
        self.assertIn("YYYY-MM-DD HH:MM", tools[0].description)
        self.assertIn("already in the official GitHub Trending page order", tools[0].description)
        self.assertIn("official GitHub Trending page order", tools[0].description)
        self.assertIn("may not match a descending stars sort", tools[0].description)
        self.assertIn("Do not re-sort", tools[0].description)
        self.assertIn("alphabetical markers", tools[0].description)
        self.assertTrue(result["ok"])
        payload = json.loads(result["result_text"])
        self.assertEqual(payload["source"], "github_trending")
        self.assertEqual(payload["since"], "daily")
        self.assertEqual(payload["order_basis"], "github_trending_page_rank")
        self.assertIn("official GitHub Trending page order", payload["order_note"])
        datetime.fromisoformat(payload["fetched_at"])
        self.assertRegex(payload["fetched_at_display"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual(payload["items"][0]["full_name"], "owner-one/repo-one")


if __name__ == "__main__":
    unittest.main()
