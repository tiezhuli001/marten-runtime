import unittest
from unittest.mock import patch

from marten_runtime.runtime.direct_rendering import render_direct_tool_text


class DirectRenderingTests(unittest.TestCase):
    def test_render_direct_tool_text_formats_trending_mcp_payload(self) -> None:
        text = render_direct_tool_text(
            "mcp",
            {
                "server_id": "github_trending",
                "tool_name": "trending_repositories",
                "result_text": (
                    '{"since":"daily","fetched_at_display":"2026-04-08 16:42","items":['
                    '{"rank":1,"full_name":"google-ai-edge/gallery","language":"Kotlin","stars_period":897}'
                    ']}'
                ),
                "ok": True,
                "is_error": False,
            },
            tool_payload={"server_id": "github_trending", "tool_name": "trending_repositories"},
        )

        self.assertIn("GitHub 今日热榜", text)
        self.assertIn("google-ai-edge/gallery", text)

    def test_render_direct_tool_text_formats_github_commit_404(self) -> None:
        text = render_direct_tool_text(
            "mcp",
            {
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "ghost", "repo": "missing"},
                "result_text": "failed to list commits: 404 Not Found",
                "ok": False,
                "is_error": True,
            },
            tool_payload={
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {"owner": "ghost", "repo": "missing"},
            },
        )

        self.assertEqual(text, "该仓库 `ghost/missing` 不存在（404 Not Found），无法获取提交信息。")

    def test_render_direct_tool_text_formats_github_commit_in_local_timezone(self) -> None:
        with patch.dict("os.environ", {"TZ": "Asia/Shanghai"}):
            text = render_direct_tool_text(
                "mcp",
                {
                    "server_id": "github",
                    "tool_name": "list_commits",
                    "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
                    "result_text": (
                        '[{"sha":"abc","commit":{"message":"chore(release):发布0.3.3版本",'
                        '"author":{"date":"2026-04-01T02:24:49Z"}}}]'
                    ),
                    "ok": True,
                    "is_error": False,
                },
                tool_payload={
                    "server_id": "github",
                    "tool_name": "list_commits",
                    "arguments": {"owner": "CloudWide851", "repo": "easy-agent"},
                },
            )

        self.assertEqual(
            text,
            "CloudWide851/easy-agent 最近一次提交是 **2026-04-01 10:24:49**（北京时间），commit 信息为 `chore(release):发布0.3.3版本`。",
        )

    def test_render_direct_tool_text_flattens_multiline_commit_message(self) -> None:
        with patch.dict("os.environ", {"TZ": "Asia/Shanghai"}):
            text = render_direct_tool_text(
                "mcp",
                {
                    "server_id": "github",
                    "tool_name": "list_commits",
                    "arguments": {"owner": "tiezhuli001", "repo": "codex-skills"},
                    "result_text": (
                        '[{"sha":"abc","commit":{"message":"Merge pull request #1 from tiezhuli001/sync-skill-updates-2026-04-14\\n\\n'
                        'sync ai-repo-cleanup and long-run-execution",'
                        '"author":{"date":"2026-04-14T12:01:21Z"}}}]'
                    ),
                    "ok": True,
                    "is_error": False,
                },
                tool_payload={
                    "server_id": "github",
                    "tool_name": "list_commits",
                    "arguments": {"owner": "tiezhuli001", "repo": "codex-skills"},
                },
            )

        self.assertEqual(
            text,
            "tiezhuli001/codex-skills 最近一次提交是 **2026-04-14 20:01:21**（北京时间），commit 信息为 `Merge pull request #1 from tiezhuli001/sync-skill-updates-2026-04-14 sync ai-repo-cleanup and long-run-execution`。",
        )

    def test_render_direct_tool_text_does_not_expand_to_repo_metadata_rendering(self) -> None:
        text = render_direct_tool_text(
            "mcp",
            {
                "server_id": "github",
                "tool_name": "search_repositories",
                "result_text": '{"items":[{"full_name":"CloudWide851/easy-agent","default_branch":"main"}]}',
                "ok": True,
                "is_error": False,
            },
            tool_payload={
                "server_id": "github",
                "tool_name": "search_repositories",
                "arguments": {"query": "repo:CloudWide851/easy-agent"},
            },
        )

        self.assertEqual(text, "")


if __name__ == "__main__":
    unittest.main()
