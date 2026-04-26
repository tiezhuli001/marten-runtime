import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from marten_runtime.interfaces.http.app import create_app
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.llm_client import DemoLLMClient, LLMReply, ScriptedLLMClient
from tests.test_acceptance import _build_repo_backed_test_app, _write_test_repo


class SessionRestartIntegrationTests(unittest.TestCase):
    def test_feishu_structured_reply_survives_runtime_rebuild_with_durable_detail(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)

            app_one = _build_repo_backed_test_app(repo_root)

            def fake_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
                return [
                    OutboundEvent(
                        session_id=session_id,
                        run_id="run_restart_feishu_durable",
                        event_id="evt_restart_feishu_durable_progress",
                        event_type="progress",
                        sequence=1,
                        trace_id=trace_id or "trace_missing",
                        payload={"text": "running"},
                        created_at=datetime.now(timezone.utc),
                    ),
                    OutboundEvent(
                        session_id=session_id,
                        run_id="run_restart_feishu_durable",
                        event_id="evt_restart_feishu_durable_final",
                        event_type="final",
                        sequence=2,
                        trace_id=trace_id or "trace_missing",
                        payload={
                            "text": (
                                "检查完成。\n\n"
                                "```feishu_card\n"
                                '{"title":"检查结果","summary":"共 2 项","sections":[{"items":["builtin 正常","mcp 正常"]}]}\n'
                                "```"
                            )
                        },
                        created_at=datetime.now(timezone.utc),
                    ),
                ]

            app_one.state.runtime.runtime_loop.run = fake_run  # type: ignore[method-assign]
            with TestClient(app_one) as client:
                response = client.post(
                    "/messages",
                    json={
                        "channel_id": "feishu",
                        "user_id": "demo",
                        "conversation_id": "restart-feishu-durable",
                        "message_id": "1",
                        "body": "first durable feishu turn",
                    },
                )
                session_id = response.json()["session_id"]

            app_two = _build_repo_backed_test_app(repo_root)
            with TestClient(app_two) as client:
                restored = client.get(f"/diagnostics/session/{session_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(restored.status_code, 200)
        payload = restored.json()
        self.assertEqual(
            payload["history"][-1]["content"],
            "检查完成。\n\n共 2 项\n\n- builtin 正常\n- mcp 正常",
        )

    def test_http_session_history_survives_runtime_rebuild(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)

            app_one = _build_repo_backed_test_app(repo_root)
            app_one.state.runtime.runtime_loop.llm = DemoLLMClient(
                provider_name="test-demo",
                model_name="test-demo",
                profile_name="test",
            )
            with TestClient(app_one) as client:
                response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "restart-history",
                        "message_id": "1",
                        "body": "first durable turn",
                    },
                )
                session_id = response.json()["session_id"]

            app_two = _build_repo_backed_test_app(repo_root)
            with TestClient(app_two) as client:
                restored = client.get(f"/diagnostics/session/{session_id}")

            self.assertEqual(restored.status_code, 200)
            payload = restored.json()
            self.assertEqual(payload["session_id"], session_id)
            self.assertEqual(payload["conversation_id"], "restart-history")
            self.assertEqual(payload["history"][-2]["content"], "first durable turn")

    def test_http_session_compacted_context_and_tool_summaries_survive_runtime_rebuild(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)

            app_one = _build_repo_backed_test_app(repo_root)
            scripted_llm = ScriptedLLMClient(
                [
                    LLMReply(tool_name="time", tool_payload={"timezone": "UTC"}),
                    LLMReply(final_text="first durable reply"),
                ]
            )
            app_one.state.runtime.llm_client_factory.cache_client("minimax_m25", scripted_llm)
            app_one.state.runtime.runtime_loop.llm = scripted_llm
            with TestClient(app_one) as client:
                first = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "restart-state",
                        "message_id": "1",
                        "body": "请先调用时间工具，然后回复。",
                    },
                )
                session_id = first.json()["session_id"]
                app_one.state.runtime.session_store.set_compacted_context(
                    session_id,
                    CompactedContext(
                        compact_id="cmp_restart_1",
                        session_id=session_id,
                        summary_text="当前进展：旧历史已压缩。",
                        source_message_range=[0, 2],
                    ),
                )
                app_one.state.runtime.session_store.append_tool_outcome_summary(
                    session_id,
                    {
                        "summary_id": "sum_restart_1",
                        "run_id": first.json()["events"][-1]["run_id"],
                        "source_kind": "builtin",
                        "summary_text": "上一轮调用了 time 工具。",
                    },
                )

            app_two = _build_repo_backed_test_app(repo_root)
            with TestClient(app_two) as client:
                restored = client.get(f"/diagnostics/session/{session_id}")

            self.assertEqual(first.status_code, 200)
            self.assertEqual(restored.status_code, 200)
            payload = restored.json()
            self.assertIsNotNone(payload["latest_compacted_context"])
            self.assertIn("当前进展", payload["latest_compacted_context"]["summary_text"])
            self.assertGreaterEqual(len(payload["recent_tool_outcome_summaries"]), 1)

    def test_runtime_diagnostics_expose_restored_session_store_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)

            app_one = _build_repo_backed_test_app(repo_root)
            app_one.state.runtime.runtime_loop.llm = DemoLLMClient(
                provider_name="test-demo",
                model_name="test-demo",
                profile_name="test",
            )
            with TestClient(app_one) as client:
                client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "restart-diagnostics",
                        "message_id": "1",
                        "body": "durable diagnostics turn",
                    },
                )

            app_two = _build_repo_backed_test_app(repo_root)
            with TestClient(app_two) as client:
                restored_runtime = client.get("/diagnostics/runtime")

            self.assertEqual(restored_runtime.status_code, 200)
            payload = restored_runtime.json()
            self.assertEqual(payload["sessions"]["store_kind"], "sqlite")
            self.assertGreaterEqual(payload["sessions"]["count"], 1)
            self.assertGreaterEqual(payload["sessions"]["binding_count"], 1)

    def test_restart_restores_compacted_summary_replay_tail_and_tool_summaries_on_next_turn(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)

            app_one = _build_repo_backed_test_app(repo_root)
            session = app_one.state.runtime.session_store.create(
                session_id="sess_restart_restore",
                conversation_id="restart-restore",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="http",
            )
            for turn in range(1, 11):
                app_one.state.runtime.session_store.append_message(
                    session.session_id,
                    SessionMessage.user(f"u{turn}"),
                )
                app_one.state.runtime.session_store.append_message(
                    session.session_id,
                    SessionMessage.assistant(f"a{turn}"),
                )
            app_one.state.runtime.session_store.set_compacted_context(
                session.session_id,
                CompactedContext(
                    compact_id="cmp_restart_restore",
                    session_id=session.session_id,
                    summary_text="当前进展：前两轮已压缩。",
                    source_message_range=[0, 5],
                    preserved_tail_user_turns=8,
                ),
            )
            app_one.state.runtime.session_store.append_tool_outcome_summary(
                session.session_id,
                {
                    "summary_id": "sum_restart_restore",
                    "run_id": "run_restart_restore",
                    "source_kind": "builtin",
                    "summary_text": "上一轮调用了 time 工具，timezone=UTC。",
                },
            )

            app_two = _build_repo_backed_test_app(repo_root)
            restored_llm = ScriptedLLMClient([LLMReply(final_text="after restart")])
            app_two.state.runtime.llm_client_factory.cache_client("minimax_m25", restored_llm)
            app_two.state.runtime.runtime_loop.llm = restored_llm
            with TestClient(app_two) as client:
                response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "restart-restore",
                        "message_id": "1",
                        "body": "继续处理",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn("当前进展", restored_llm.requests[0].compact_summary_text or "")
        self.assertIn("time 工具", restored_llm.requests[0].tool_outcome_summary_text or "")
        self.assertEqual(
            [item.content for item in restored_llm.requests[0].conversation_messages],
            [entry for turn in range(3, 11) for entry in (f"u{turn}", f"a{turn}")],
        )

    def test_restart_expands_modern_checkpoint_tail_when_replay_user_turns_increases(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)

            app_one = _build_repo_backed_test_app(repo_root)
            session = app_one.state.runtime.session_store.create(
                session_id="sess_restart_modern_expand",
                conversation_id="restart-modern-expand",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="http",
            )
            for turn in range(1, 5):
                app_one.state.runtime.session_store.append_message(
                    session.session_id,
                    SessionMessage.user(f"u{turn}"),
                )
                app_one.state.runtime.session_store.append_message(
                    session.session_id,
                    SessionMessage.assistant(f"a{turn}"),
                )
            app_one.state.runtime.session_store.set_compacted_context(
                session.session_id,
                CompactedContext(
                    compact_id="cmp_restart_modern_expand",
                    session_id=session.session_id,
                    summary_text="当前进展：旧历史已压缩。",
                    source_message_range=[0, 6],
                    preserved_tail_user_turns=1,
                ),
            )

            app_two = _build_repo_backed_test_app(repo_root)
            app_two.state.runtime.platform_config.runtime.session_replay_user_turns = 3
            restored_llm = ScriptedLLMClient([LLMReply(final_text="after restart")])
            app_two.state.runtime.llm_client_factory.cache_client("minimax_m25", restored_llm)
            app_two.state.runtime.runtime_loop.llm = restored_llm
            with TestClient(app_two) as client:
                response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "restart-modern-expand",
                        "message_id": "1",
                        "body": "继续处理",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item.content for item in restored_llm.requests[0].conversation_messages],
            ["u2", "a2", "u3", "a3", "u4", "a4"],
        )
        self.assertIn("u1", restored_llm.requests[0].compact_summary_text or "")
        self.assertIn("a1", restored_llm.requests[0].compact_summary_text or "")
        self.assertNotIn("u2", restored_llm.requests[0].compact_summary_text or "")


if __name__ == "__main__":
    unittest.main()
