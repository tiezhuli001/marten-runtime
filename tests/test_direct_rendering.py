import unittest
from unittest.mock import patch

from marten_runtime.runtime.direct_rendering import (
    is_partial_fragment_aggregation,
    render_recovery_fragment,
    render_recovery_fragments_text,
    render_direct_tool_text,
)
from marten_runtime.runtime.llm_client import ToolFollowupFragment


class DirectRenderingTests(unittest.TestCase):
    def test_render_recovery_fragment_normalizes_whitespace(self) -> None:
        text = render_recovery_fragment(
            ToolFollowupFragment(
                text="  第一段结果  \n\n",
                source="tool_result",
                tool_name="time",
            )
        )

        self.assertEqual(text, "第一段结果")

    def test_render_recovery_fragments_text_joins_arbitrary_fragments_in_order(self) -> None:
        text = render_recovery_fragments_text(
            [
                ToolFollowupFragment(text="第一段结果", source="tool_result", tool_name="time"),
                ToolFollowupFragment(text="第二段结果", source="tool_result", tool_name="runtime"),
                ToolFollowupFragment(text="第三段结果", source="loop_meta"),
            ]
        )

        self.assertEqual(text, "第一段结果\n\n第二段结果\n\n第三段结果")

    def test_is_partial_fragment_aggregation_matches_strict_ordered_subsequence(self) -> None:
        fragments = [
            ToolFollowupFragment(text="第一段结果", source="tool_result", tool_name="time"),
            ToolFollowupFragment(text="第二段结果", source="tool_result", tool_name="runtime"),
            ToolFollowupFragment(text="第三段结果", source="tool_result", tool_name="mcp"),
        ]

        self.assertTrue(
            is_partial_fragment_aggregation(
                fragments,
                "第一段结果\n\n第三段结果",
            )
        )

    def test_is_partial_fragment_aggregation_rejects_exact_full_match(self) -> None:
        fragments = [
            ToolFollowupFragment(text="第一段结果", source="tool_result", tool_name="time"),
            ToolFollowupFragment(text="第二段结果", source="tool_result", tool_name="runtime"),
        ]

        self.assertFalse(
            is_partial_fragment_aggregation(
                fragments,
                "第一段结果\n\n第二段结果",
            )
        )

    def test_is_partial_fragment_aggregation_rejects_substring_like_match(self) -> None:
        fragments = [
            ToolFollowupFragment(text="第一段结果", source="tool_result", tool_name="time"),
            ToolFollowupFragment(text="第二段结果", source="tool_result", tool_name="runtime"),
        ]

        self.assertFalse(
            is_partial_fragment_aggregation(
                fragments,
                "第一段",
            )
        )

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

    def test_render_direct_tool_text_formats_session_list(self) -> None:
        text = render_direct_tool_text(
            "session",
            {
                "action": "list",
                "count": 2,
                "current_session": {
                    "session_id": "sess_1",
                    "session_title": "排查 Feishu None 输出",
                    "message_count": 6,
                    "state": "running",
                },
                "items": [
                    {
                        "session_id": "sess_1",
                        "session_title": "排查 Feishu None 输出",
                        "message_count": 6,
                        "state": "running",
                        "is_current": True,
                    },
                    {
                        "session_id": "sess_2",
                        "session_preview": "查看会话列表",
                        "message_count": 2,
                    },
                ],
            },
            tool_payload={"action": "list"},
        )

        self.assertIn("当前有 2 个可见会话", text)
        self.assertIn("当前会话：排查 Feishu None 输出（running，6 条，session_id：sess_1）", text)
        self.assertIn("| 序号 | 标题 | 状态 | 消息数 | 创建时间 | session_id |", text)
        self.assertIn("| 1 | 当前 · 排查 Feishu None 输出 | running | 6 | - | sess_1 |", text)
        self.assertIn("| 2 | 查看会话列表 | unknown | 2 | - | sess_2 |", text)

    def test_render_direct_tool_text_sanitizes_session_catalog_mentions_and_links(self) -> None:
        text = render_direct_tool_text(
            "session",
            {
                "action": "list",
                "count": 1,
                "items": [
                    {
                        "session_id": "sess_dirty",
                        "session_title": "@_user_1 开启子代理查询github上…",
                        "session_preview": "@_user_1 开启子代理查询github上的[GitHub - tiezhuli001/codex-skills](https://github.com/tiezhuli001/codex-skills) 最近一次提交是什么时候。",
                        "message_count": 31,
                        "state": "running",
                        "created_at": "2026-04-19T15:30:41+00:00",
                    }
                ],
            },
            tool_payload={"action": "list"},
        )

        self.assertNotIn("@_user_1", text)
        self.assertIn("| 1 | 开启子代理查询github上… | running | 31 | 2026-04-19 23:30:41 | sess_dirty |", text)

    def test_render_direct_tool_text_formats_mcp_list(self) -> None:
        text = render_direct_tool_text(
            "mcp",
            {
                "action": "list",
                "servers": [
                    {"server_id": "github", "tool_count": 38, "state": "ready"},
                    {"server_id": "github-trending", "tool_count": 1, "state": "ready"},
                    {"server_id": "github_trending", "tool_count": 1, "state": "ready"},
                ],
            },
            tool_payload={"action": "list"},
        )

        self.assertIn("当前可用 MCP 服务共 2 个", text)
        self.assertIn("github", text)
        self.assertIn("github-trending", text)
        self.assertNotIn("github_trending", text)

if __name__ == "__main__":
    unittest.main()
