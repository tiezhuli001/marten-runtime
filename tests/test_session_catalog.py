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
from marten_runtime.session.models import SessionMessage
from marten_runtime.tools.registry import ToolSnapshot
from marten_runtime.session.title_summary import build_session_title_summary
from tests.test_acceptance import _build_repo_backed_test_app, _write_test_repo
from tests.support.finalization_contracts import contracted_final_reply


class SessionCatalogTests(unittest.TestCase):
    @staticmethod
    def _non_summary_requests(llm: ScriptedLLMClient) -> list[LLMRequest]:
        return [request for request in llm.requests if request.request_kind != "session_summary"]

    def test_build_session_title_summary_prefers_one_shot_llm_summary(self) -> None:
        llm = ScriptedLLMClient(
            [],
            session_summary_replies=[
                LLMReply(
                    final_text="Title: 修复 durable session\nPreview: 为 runtime 增加跨重启会话恢复。"
                )
            ],
        )

        title, preview = build_session_title_summary(
            llm_client=llm,
            session_id="sess_1",
            trace_id="trace_1",
            agent_id="main",
            user_message="我要让 runtime 在重启之后也能保留会话。",
        )

        self.assertEqual(title, "修复 durable session")
        self.assertEqual(preview, "为 runtime 增加跨重启会话恢复。")

    def test_build_session_title_summary_falls_back_to_generic_placeholder(self) -> None:
        class FailingSummaryLLM:
            def complete(self, request):  # noqa: ANN001
                raise RuntimeError("summary failed")

        title, preview = build_session_title_summary(
            llm_client=FailingSummaryLLM(),
            session_id="sess_1",
            trace_id="trace_1",
            agent_id="main",
            user_message="我要让 runtime 在重启之后也能保留会话，而且标题生成失败时也要有降级方案。",
        )

        self.assertEqual(title, "新会话")
        self.assertEqual(preview, "用户开启了一个新会话。")

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
                available_tools=["time"],
                tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
            )
        )
        self.assertEqual(followup.tool_name, "time")

    def test_build_session_title_summary_sanitizes_feishu_mentions_and_markdown_links(self) -> None:
        class CapturingSummaryLLM:
            def __init__(self) -> None:
                self.request = None

            def complete(self, request):  # noqa: ANN001
                self.request = request
                return LLMReply(final_text="Title: github 提交\nPreview: 查询最近一次提交时间。")

        llm = CapturingSummaryLLM()
        build_session_title_summary(
            llm_client=llm,
            session_id="sess_1",
            trace_id="trace_1",
            agent_id="main",
            user_message=(
                "@_user_1 开启子代理查询github上的"
                "[GitHub - tiezhuli001/codex-skills](https://github.com/tiezhuli001/codex-skills) "
                "最近一次提交是什么时候"
            ),
        )

        self.assertIsNotNone(llm.request)
        self.assertNotIn("@_user_1", llm.request.summary_input_text or "")
        self.assertIn(
            "GitHub - tiezhuli001/codex-skills",
            llm.request.summary_input_text or "",
        )

    def test_build_session_title_summary_rejects_template_placeholders_from_demo_echo(self) -> None:
        title, preview = build_session_title_summary(
            llm_client=DemoLLMClient(),
            session_id="sess_demo",
            trace_id="trace_demo",
            agent_id="main",
            user_message="帮我排查会话标题生成。",
        )

        self.assertEqual(title, "新会话")
        self.assertEqual(preview, "用户开启了一个新会话。")

    def test_diagnostics_sessions_lists_catalog_metadata(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)
            app = _build_repo_backed_test_app(repo_root)
            scripted_llm = ScriptedLLMClient(
                [LLMReply(final_text="first final")],
                session_summary_replies=[
                    LLMReply(final_text="Title: 修复 session 列表\nPreview: 会话目录展示切换目标。"),
                ],
            )
            app.state.runtime.llm_client_factory.cache_client("minimax_m2_7_highspeed", scripted_llm)
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

    def test_first_turn_catalog_metadata_uses_placeholder_without_session_summary_call(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)
            app = _build_repo_backed_test_app(repo_root)
            main_llm = ScriptedLLMClient([contracted_final_reply("first final")])
            summary_llm = ScriptedLLMClient(
                [],
                session_summary_replies=[
                    LLMReply(final_text="Title: 真标题\nPreview: 真预览。"),
                ],
            )
            app.state.runtime.llm_client_factory.cache_client("minimax_m2_7_highspeed", main_llm)
            app.state.runtime.runtime_loop.llm = main_llm
            app.state.runtime.llm_client_factory.create_session_summary_client = (  # type: ignore[method-assign]
                lambda profile_name, default_client=None: summary_llm
            )

            with TestClient(app) as client:
                response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "catalog-placeholder",
                        "message_id": "1",
                        "body": "帮我排查首轮为什么这么慢。",
                    },
                )
                listed = client.get("/diagnostics/sessions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(listed.status_code, 200)
        item = listed.json()["items"][0]
        self.assertEqual(item["conversation_id"], "catalog-placeholder")
        self.assertEqual(item["session_title"], "新会话")
        self.assertEqual(item["session_preview"], "用户开启了一个新会话。")
        self.assertEqual(summary_llm.requests, [])
        self.assertEqual(
            [request.request_kind for request in main_llm.requests],
            ["interactive"],
        )
        self.assertEqual(
            [request.request_kind for request in self._non_summary_requests(main_llm)],
            ["interactive"],
        )

    def test_diagnostics_sessions_is_operator_listing_not_user_filtered_tool_view(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)
            app = _build_repo_backed_test_app(repo_root)
            first_llm = ScriptedLLMClient(
                [
                    LLMReply(final_text="first final"),
                    LLMReply(final_text="second final"),
                ],
                session_summary_replies=[
                    LLMReply(final_text="Title: user a\nPreview: first user session."),
                    LLMReply(final_text="Title: user b\nPreview: second user session."),
                ],
            )
            app.state.runtime.llm_client_factory.cache_client("minimax_m2_7_highspeed", first_llm)
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

    def test_diagnostics_session_catalog_refreshes_existing_generic_title_via_session_summary_client(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)
            app = _build_repo_backed_test_app(repo_root)
            main_llm = ScriptedLLMClient(
                [contracted_final_reply("继续处理标题刷新。")],
            )
            summary_llm = ScriptedLLMClient(
                [],
                session_summary_replies=[
                    LLMReply(
                        final_text=(
                            "Title: 修复 session 标题刷新\n"
                            "Preview: 避免占位值持续污染 session catalog。"
                        )
                    )
                ],
            )
            app.state.runtime.llm_client_factory.cache_client("minimax_m2_7_highspeed", main_llm)
            app.state.runtime.runtime_loop.llm = main_llm
            app.state.runtime.llm_client_factory.create_session_summary_client = (  # type: ignore[method-assign]
                lambda profile_name, default_client=None: summary_llm
            )
            session = app.state.runtime.session_store.create(
                session_id="sess_catalog_refresh",
                conversation_id="catalog-refresh",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="http",
                user_id="demo",
            )
            app.state.runtime.session_store.append_message(
                session.session_id,
                SessionMessage.user("修复 session 标题刷新，避免占位值污染 catalog。"),
            )
            app.state.runtime.session_store.set_catalog_metadata(
                session.session_id,
                user_id="demo",
                agent_id="main",
                session_title="新会话",
                session_preview="用户开启了一个新会话。",
            )

            with TestClient(app) as client:
                response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "catalog-refresh",
                        "message_id": "1",
                        "body": "继续",
                    },
                )
                refreshed_session = client.get(f"/diagnostics/session/{response.json()['session_id']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(refreshed_session.status_code, 200)
        self.assertEqual(
            refreshed_session.json()["session_title"],
            "修复 session 标题刷新",
        )
        self.assertEqual(
            refreshed_session.json()["session_preview"],
            "避免占位值持续污染 session catalog。",
        )
        self.assertEqual(
            [request.request_kind for request in summary_llm.requests],
            ["session_summary"],
        )
        self.assertEqual(
            [request.request_kind for request in self._non_summary_requests(main_llm)],
            ["interactive"],
        )


if __name__ == "__main__":
    unittest.main()
