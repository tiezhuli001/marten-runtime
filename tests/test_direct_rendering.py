import unittest
from unittest.mock import patch

from marten_runtime.runtime.direct_rendering import (
    render_direct_tool_history_text,
    render_direct_tool_text,
)
from marten_runtime.runtime.llm_client import ToolExchange


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

    def test_render_direct_tool_text_formats_session_list(self) -> None:
        text = render_direct_tool_text(
            "session",
            {
                "action": "list",
                "count": 2,
                "items": [
                    {
                        "session_id": "sess_1",
                        "session_title": "排查 Feishu None 输出",
                        "message_count": 6,
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
        self.assertIn("1. 标题：排查 Feishu None 输出", text)
        self.assertIn("状态：unknown", text)
        self.assertIn("session_id：sess_2", text)

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
        self.assertIn("GitHub - tiezhuli001/codex-skills", text)
        self.assertIn("状态：running", text)
        self.assertIn("创建时间：2026-04-19 23:30:41", text)

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

    def test_render_direct_tool_history_text_formats_fixed_three_step_sequence(self) -> None:
        history = [
            ToolExchange(
                tool_name="time",
                tool_payload={"timezone": "Asia/Shanghai"},
                tool_result={"timezone": "Asia/Shanghai", "iso_time": "2026-04-20T12:30:00+08:00"},
            ),
            ToolExchange(
                tool_name="runtime",
                tool_payload={"action": "context_status"},
                tool_result={
                    "ok": True,
                    "action": "context_status",
                    "summary": "当前估算占用 1200/184000 tokens（1%）。",
                    "current_run": {
                        "initial_input_tokens_estimate": 1200,
                        "peak_input_tokens_estimate": 1200,
                        "peak_stage": "initial_request",
                        "actual_cumulative_input_tokens": 0,
                        "actual_cumulative_output_tokens": 0,
                        "actual_cumulative_total_tokens": 0,
                        "actual_peak_input_tokens": None,
                        "actual_peak_output_tokens": None,
                        "actual_peak_total_tokens": None,
                        "actual_peak_stage": None,
                    },
                    "next_request_estimate": {
                        "input_tokens_estimate": 1200,
                        "effective_window_tokens": 184000,
                        "context_window_tokens": 200000,
                        "estimator_kind": "rough",
                        "degraded": True,
                    },
                    "effective_window": 184000,
                    "context_window": 200000,
                    "estimated_usage": 1200,
                    "usage_percent": 1,
                    "compaction_status": "none",
                    "latest_checkpoint": "none",
                    "estimate_source": "rough",
                    "last_actual_usage": None,
                    "last_completed_run": None,
                    "model_profile": "minimax_m25",
                },
            ),
            ToolExchange(
                tool_name="mcp",
                tool_payload={"action": "list"},
                tool_result={
                    "action": "list",
                    "servers": [{"server_id": "github", "tool_count": 38, "state": "ready"}],
                },
            ),
        ]

        text = render_direct_tool_history_text(history)

        self.assertIn("现在是北京时间 2026年4月20日 12:30", text)
        self.assertIn("当前上下文使用详情", text)
        self.assertIn("当前可用 MCP 服务共 1 个", text)
        self.assertIn("属于多次模型/工具往返", text)


if __name__ == "__main__":
    unittest.main()
