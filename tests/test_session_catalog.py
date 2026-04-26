import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from marten_runtime.runtime.llm_client import (
    DemoLLMClient,
    LLMReply,
    LLMRequest,
    ScriptedLLMClient,
)
from marten_runtime.tools.registry import ToolSnapshot
from marten_runtime.session.title_summary import build_session_title_summary
from tests.test_acceptance import _build_repo_backed_test_app, _write_test_repo


class SessionCatalogTests(unittest.TestCase):
    def test_build_session_title_summary_prefers_one_shot_llm_summary(self) -> None:
        llm = ScriptedLLMClient(
            [
                LLMReply(
                    final_text="Title: 修复 durable session\nPreview: 为 runtime 增加跨重启会话恢复。"
                )
            ]
        )

        title, preview = build_session_title_summary(
            llm_client=llm,
            session_id="sess_1",
            trace_id="trace_1",
            app_id="main_agent",
            agent_id="main",
            user_message="我要让 runtime 在重启之后也能保留会话。",
        )

        self.assertEqual(title, "修复 durable session")
        self.assertEqual(preview, "为 runtime 增加跨重启会话恢复。")

    def test_build_session_title_summary_falls_back_to_message_truncation(self) -> None:
        class FailingSummaryLLM:
            def complete(self, request):  # noqa: ANN001
                raise RuntimeError("summary failed")

        title, preview = build_session_title_summary(
            llm_client=FailingSummaryLLM(),
            session_id="sess_1",
            trace_id="trace_1",
            app_id="main_agent",
            agent_id="main",
            user_message="我要让 runtime 在重启之后也能保留会话，而且标题生成失败时也要有降级方案。",
        )

        self.assertTrue(title)
        self.assertTrue(preview)
        self.assertIn("runtime", title + preview)

    def test_build_session_title_summary_does_not_consume_non_summary_scripted_reply(self) -> None:
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "UTC"}),
                LLMReply(final_text="正常主链路回复"),
            ]
        )

        title, preview = build_session_title_summary(
            llm_client=llm,
            session_id="sess_1",
            trace_id="trace_1",
            app_id="main_agent",
            agent_id="main",
            user_message="记住这个会话是关于 durable session 的。",
        )

        self.assertTrue(title)
        self.assertTrue(preview)
        followup = llm.complete(
            LLMRequest(
                session_id="sess_1",
                trace_id="trace_2",
                message="继续",
                agent_id="main",
                app_id="main_agent",
                available_tools=["time"],
                tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            )
        )
        self.assertEqual(followup.tool_name, "time")

    def test_build_session_title_summary_sanitizes_feishu_mentions_and_markdown_links(self) -> None:
        class FailingSummaryLLM:
            def complete(self, request):  # noqa: ANN001
                raise RuntimeError("summary failed")

        title, preview = build_session_title_summary(
            llm_client=FailingSummaryLLM(),
            session_id="sess_1",
            trace_id="trace_1",
            app_id="main_agent",
            agent_id="main",
            user_message=(
                "@_user_1 开启子代理查询github上的"
                "[GitHub - tiezhuli001/codex-skills](https://github.com/tiezhuli001/codex-skills) "
                "最近一次提交是什么时候"
            ),
        )

        self.assertNotIn("@_user_1", title)
        self.assertNotIn("@_user_1", preview)
        self.assertIn("GitHub - tiezhuli001/codex-skills", title + preview)

    def test_diagnostics_sessions_lists_catalog_metadata(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)
            app = _build_repo_backed_test_app(repo_root)
            scripted_llm = ScriptedLLMClient(
                [
                    LLMReply(final_text="Title: 修复 session 列表\nPreview: 会话目录展示切换目标。"),
                    LLMReply(final_text="first final"),
                ]
            )
            app.state.runtime.llm_client_factory.cache_client("minimax_m25", scripted_llm)
            app.state.runtime.runtime_loop.llm = scripted_llm

            with TestClient(app) as client:
                create = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "catalog-list",
                        "message_id": "1",
                        "body": "帮我做 durable session 的列表切换设计。",
                    },
                )
                listed = client.get("/diagnostics/sessions")

        self.assertEqual(create.status_code, 200)
        self.assertEqual(listed.status_code, 200)
        payload = listed.json()
        self.assertGreaterEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["conversation_id"], "catalog-list")
        self.assertTrue(payload["items"][0]["session_title"])
        self.assertTrue(payload["items"][0]["session_preview"])

    def test_diagnostics_sessions_is_operator_listing_not_user_filtered_tool_view(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)
            app = _build_repo_backed_test_app(repo_root)
            first_llm = ScriptedLLMClient(
                [
                    LLMReply(final_text="Title: user a\nPreview: first user session."),
                    LLMReply(final_text="first final"),
                    LLMReply(final_text="Title: user b\nPreview: second user session."),
                    LLMReply(final_text="second final"),
                ]
            )
            app.state.runtime.llm_client_factory.cache_client("minimax_m25", first_llm)
            app.state.runtime.runtime_loop.llm = first_llm

            with TestClient(app) as client:
                client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "user-a",
                        "conversation_id": "catalog-a",
                        "message_id": "1",
                        "body": "first user session",
                    },
                )
                client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "user-b",
                        "conversation_id": "catalog-b",
                        "message_id": "2",
                        "body": "second user session",
                    },
                )
                listed = client.get("/diagnostics/sessions")

        self.assertEqual(listed.status_code, 200)
        payload = listed.json()
        session_users = {item["user_id"] for item in payload["items"]}
        self.assertIn("user-a", session_users)
        self.assertIn("user-b", session_users)


if __name__ == "__main__":
    unittest.main()
