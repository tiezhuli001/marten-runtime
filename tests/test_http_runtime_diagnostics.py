import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.session.models import SessionMessage
from tests.http_app_support import build_test_app
from marten_runtime.interfaces.http.runtime_diagnostics import (
    resolve_runtime_server_surface,
    serialize_runtime_diagnostics,
)


class HTTPRuntimeDiagnosticsTests(unittest.TestCase):
    def test_resolve_runtime_server_surface_prefers_request_base_url(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        request = Mock()
        request.base_url = "https://example.com/runtime/"

        surface = resolve_runtime_server_surface(runtime, request)

        self.assertEqual(surface["host"], "example.com")
        self.assertEqual(surface["port"], 443)
        self.assertEqual(surface["public_base_url"], "https://example.com/runtime")
        self.assertEqual(surface["configured_host"], runtime.platform_config.server.host)

    def test_serialize_runtime_diagnostics_preserves_server_and_channel_fields(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        request = Mock()
        request.base_url = "http://127.0.0.1:9000/"

        body = serialize_runtime_diagnostics(runtime, request)

        self.assertEqual(body["app_id"], runtime.app_manifest.app_id)
        self.assertEqual(body["server"]["host"], "127.0.0.1")
        self.assertEqual(body["server"]["port"], 9000)
        self.assertIn("feishu", body["channels"])
        self.assertIn("sessions", body)
        self.assertIn("provider_retry_policy", body)
        self.assertEqual(body["tool_count"], len(runtime.tool_registry.list()))
        self.assertEqual(body["sessions"]["store_kind"], runtime.session_store.storage_kind())
        self.assertEqual(body["sessions"]["count"], runtime.session_store.count())
        self.assertEqual(body["provider_count"], 2)
        self.assertEqual(
            sorted(provider["provider_ref"] for provider in body["providers"]),
            ["minimax", "openai"],
        )
        self.assertIn("api_key_env", body["providers"][0])
        self.assertNotIn("test-key", str(body["providers"]))

    def test_serialize_runtime_diagnostics_exposes_effective_provider_base_url(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.env["OPENAI_API_BASE"] = "https://openai-proxy.example/v1"
        request = Mock()
        request.base_url = "http://127.0.0.1:9000/"

        body = serialize_runtime_diagnostics(runtime, request)

        openai_provider = next(
            provider for provider in body["providers"] if provider["provider_ref"] == "openai"
        )
        self.assertEqual(openai_provider["base_url"], "https://openai-proxy.example/v1")
        self.assertEqual(openai_provider["configured_base_url"], "https://api.openai.com/v1")
        self.assertEqual(openai_provider["effective_base_url"], "https://openai-proxy.example/v1")

    def test_serialize_runtime_diagnostics_exposes_restore_contract_defaults(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        request = Mock()
        request.base_url = "http://127.0.0.1:9000/"

        body = serialize_runtime_diagnostics(runtime, request)

        self.assertEqual(
            body["sessions"]["session_replay_user_turns"],
            runtime.platform_config.runtime.session_replay_user_turns,
        )
        self.assertEqual(body["sessions"]["recent_tool_outcome_summary_limit"], 3)

    def test_serialize_runtime_diagnostics_includes_latest_session_transition(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        request = Mock()
        request.base_url = "http://127.0.0.1:9000/"
        current = runtime.session_store.create(
            session_id="sess_current",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        runtime.session_store.set_catalog_metadata(
            current.session_id,
            user_id="demo",
            agent_id="main",
            session_title="current",
            session_preview="current preview",
        )
        runtime.session_store.append_message(current.session_id, SessionMessage.user("历史 1"))
        runtime.session_store.append_message(current.session_id, SessionMessage.assistant("历史 1 完成"))
        runtime.session_store.append_message(current.session_id, SessionMessage.user("历史 2"))
        runtime.session_store.append_message(current.session_id, SessionMessage.assistant("历史 2 完成"))
        runtime.session_store.append_message(current.session_id, SessionMessage.user("切到新会话"))

        runtime.tool_registry.call(
            "session",
            {"action": "new"},
            tool_context={
                "channel_id": "http",
                "conversation_id": "conv-current",
                "session_id": current.session_id,
                "user_id": "demo",
                "message": "切到新会话",
                "llm_client": ScriptedLLMClient([LLMReply(final_text="当前进展：source 已压缩。")]),
                "session_replay_user_turns": 1,
            },
        )
        body = serialize_runtime_diagnostics(runtime, request)

        self.assertIn("latest_session_transition", body)
        self.assertEqual(body["latest_session_transition"]["action"], "new")
        self.assertEqual(
            body["latest_session_transition"]["source_session_id"],
            current.session_id,
        )
        self.assertTrue(body["latest_session_transition"]["compaction_attempted"])
        self.assertFalse(body["latest_session_transition"]["compaction_succeeded"])
        self.assertEqual(body["latest_session_transition"]["compaction_reason"], "deferred")
        self.assertEqual(
            body["latest_session_transition"]["compaction_job"]["enqueue_status"],
            "queued",
        )
        self.assertNotIn("test-key", str(body["latest_session_transition"]))

    def test_serialize_runtime_diagnostics_includes_compaction_worker_status(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        request = Mock()
        request.base_url = "http://127.0.0.1:9000/"
        current = runtime.session_store.create(
            session_id="sess_current",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        runtime.session_store.append_message(current.session_id, SessionMessage.user("历史 1"))
        job = runtime.session_store.enqueue_compaction_job(
            source_session_id=current.session_id,
            current_message="切换会话",
            preserved_tail_user_turns=1,
            source_message_range=[0, 1],
            snapshot_message_count=len(runtime.session_store.get(current.session_id).history),
        )
        runtime.session_store.claim_next_compaction_job()
        runtime.session_store.mark_compaction_job_succeeded(
            job["job_id"],
            queue_wait_ms=11,
            compaction_llm_ms=222,
            persist_ms=7,
            result_reason="generated",
            source_range_end=1,
            write_applied=True,
        )

        body = serialize_runtime_diagnostics(runtime, request)

        self.assertIn("compaction_worker", body)
        self.assertIn("latest_job", body["compaction_worker"])
        self.assertEqual(body["compaction_worker"]["queue_depth"], 0)
        self.assertEqual(body["compaction_worker"]["latest_job"]["status"], "succeeded")
        self.assertEqual(body["compaction_worker"]["latest_job"]["queue_wait_ms"], 11)
        self.assertEqual(body["compaction_worker"]["latest_job"]["compaction_llm_ms"], 222)
        self.assertEqual(body["compaction_worker"]["latest_job"]["persist_ms"], 7)
        self.assertEqual(body["compaction_worker"]["latest_job"]["source_range_end"], 1)
        self.assertNotIn("test-key", str(body["compaction_worker"]))

    def test_run_diagnostics_endpoint_exposes_bounded_finalization_fields(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        record = runtime.run_history.start(
            session_id="sess_diag_finalization",
            trace_id="trace_diag_finalization",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        runtime.run_history.set_finalization_state(
            record.run_id,
            assessment="retryable_degraded",
            request_kind="finalization_retry",
            required_evidence_count=3,
            missing_evidence_items=[
                "现在是北京时间 2026-04-20 12:30:00。",
                "当前上下文使用详情：预计占用 1234/184000 tokens。",
                "当前可用 MCP 服务共 1 个。",
                "本次请求共发生 4 次模型请求和 3 次工具调用，属于多次模型/工具往返。",
            ],
            retry_triggered=True,
            recovered_from_fragments=True,
            invalid_final_text="y" * 600,
        )

        with TestClient(app) as client:
            response = client.get(f"/diagnostics/run/{record.run_id}")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["finalization"]["assessment"], "retryable_degraded")
        self.assertEqual(body["finalization"]["request_kind"], "finalization_retry")
        self.assertEqual(body["finalization"]["required_evidence_count"], 3)
        self.assertTrue(body["finalization"]["retry_triggered"])
        self.assertTrue(body["finalization"]["recovered_from_fragments"])
        self.assertLessEqual(len(body["finalization"]["missing_evidence_items"]), 3)
        self.assertLessEqual(len(body["finalization"]["invalid_final_text"]), 280)


if __name__ == "__main__":
    unittest.main()
