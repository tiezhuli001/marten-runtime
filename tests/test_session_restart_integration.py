import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from marten_runtime.interfaces.http.app import create_app
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.runtime.llm_client import DemoLLMClient, LLMReply, ScriptedLLMClient
from tests.test_acceptance import _build_repo_backed_test_app, _write_test_repo


class SessionRestartIntegrationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
