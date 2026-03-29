import unittest

from fastapi.testclient import TestClient

from marten_runtime.channels.dead_letter import InMemoryDeadLetterQueue
from marten_runtime.channels.delivery_retry import DeliveryRetryPolicy
from marten_runtime.channels.feishu.delivery import FeishuDeliveryClient, FeishuDeliveryPayload
from marten_runtime.channels.feishu.delivery_session import InMemoryFeishuDeliverySessionStore
from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.session.compaction import compact_context
from tests.http_app_support import build_test_app


class ContractCompatibilityTests(unittest.TestCase):
    def test_http_and_event_contracts_keep_required_fields(self) -> None:
        with TestClient(build_test_app()) as client:
            message = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "compat",
                    "message_id": "1",
                    "body": "hello",
                },
            ).json()
        event = OutboundEvent(
            session_id="sess_1",
            run_id="run_1",
            event_id="evt_1",
            event_type="final",
            sequence=2,
            trace_id="trace_1",
            payload={"text": "ok"},
            created_at=compact_context("sess_1", "goal", 10).model_fields["snapshot_id"].default if False else __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )

        self.assertIn("session_id", message)
        self.assertIn("events", message)
        self.assertEqual(event.trace_id, "trace_1")
        snapshot = compact_context("sess_1", "goal", 10)
        self.assertEqual(snapshot.session_id, "sess_1")
        self.assertTrue(hasattr(snapshot, "manifest_id"))

    def test_metrics_and_diagnostics_endpoints_exist(self) -> None:
        with TestClient(build_test_app()) as client:
            message = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "compat-observe",
                    "message_id": "2",
                    "body": "hello",
                },
            ).json()
            session_id = message["session_id"]
            run_id = message["events"][-1]["run_id"]

            metrics = client.get("/metrics")
            session_diag = client.get(f"/diagnostics/session/{session_id}")
            run_diag = client.get(f"/diagnostics/run/{run_id}")
            queue_diag = client.get("/diagnostics/queue")
            runtime_diag = client.get("/diagnostics/runtime")

        self.assertEqual(metrics.status_code, 200)
        self.assertIn("session_created_total", metrics.text)
        self.assertIn("provider_request_total", metrics.text)
        self.assertEqual(session_diag.status_code, 200)
        self.assertEqual(session_diag.json()["session_id"], session_id)
        self.assertEqual(run_diag.status_code, 200)
        self.assertEqual(run_diag.json()["run_id"], run_id)
        self.assertEqual(queue_diag.status_code, 200)
        self.assertIn("queue_depth", queue_diag.json())
        self.assertEqual(runtime_diag.status_code, 200)
        self.assertIn("default_agent_id", runtime_diag.json())
        self.assertIn("mcp_server_count", runtime_diag.json())
        self.assertIn("env_loaded", runtime_diag.json())
        self.assertIn("server", runtime_diag.json())
        self.assertIn("public_base_url", runtime_diag.json()["server"])
        self.assertIn("channels", runtime_diag.json())
        self.assertIn("websocket", runtime_diag.json()["channels"]["feishu"])
        self.assertIn("mcp_servers", runtime_diag.json())
        mock_search = next(
            item for item in runtime_diag.json()["mcp_servers"] if item["server_id"] == "mock-search"
        )
        self.assertIn("source_layers", mock_search)
        self.assertTrue(
            any(layer in {"config/mcp.toml", "config/mcp.example.toml"} for layer in mock_search["source_layers"])
        )

    def test_runtime_diagnostics_expose_feishu_channel_hardening_signals(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        receipts = InMemoryReceiptStore()
        receipts.claim(
            channel_id="feishu",
            dedupe_key="dedupe_diag",
            trace_id="trace_diag",
            conversation_id="chat_diag",
            message_id="evt_diag",
        )
        receipts.claim(
            channel_id="feishu",
            dedupe_key="dedupe_diag",
            trace_id="trace_diag_2",
            conversation_id="chat_diag",
            message_id="evt_diag",
        )
        sessions = InMemoryFeishuDeliverySessionStore()
        sessions.start_or_get(
            channel_id="feishu",
            conversation_id="chat_diag",
            run_id="run_diag",
            trace_id="trace_diag",
        )
        dead_letters = InMemoryDeadLetterQueue()
        dead_letters.record(
            channel_id="feishu",
            conversation_id="chat_diag",
            payload=FeishuDeliveryPayload(
                chat_id="chat_diag",
                event_type="error",
                event_id="evt_dead_diag",
                run_id="run_diag",
                trace_id="trace_diag",
                sequence=7,
                text="failed",
            ),
            attempts=3,
            error="boom",
        )
        delivery = FeishuDeliveryClient(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            session_store=sessions,
            retry_policy=DeliveryRetryPolicy(
                progress_max_retries=2,
                final_max_retries=5,
                error_max_retries=5,
                base_backoff_seconds=0.1,
                max_backoff_seconds=0.5,
            ),
            dead_letter_queue=dead_letters,
        )

        runtime.feishu_receipts = receipts
        runtime.feishu_delivery = delivery
        with TestClient(app) as client:
            runtime_diag = client.get("/diagnostics/runtime")

        self.assertEqual(runtime_diag.status_code, 200)
        feishu = runtime_diag.json()["channels"]["feishu"]
        self.assertEqual(feishu["connection_mode"], "websocket")
        self.assertIn("receipt_store", feishu)
        self.assertEqual(feishu["receipt_store"]["duplicate_total"], 1)
        self.assertEqual(feishu["receipt_store"]["last_duplicate"]["trace_id"], "trace_diag")
        self.assertIn("delivery_sessions", feishu)
        self.assertEqual(feishu["delivery_sessions"]["active_count"], 1)
        self.assertIn("dead_letter", feishu)
        self.assertEqual(feishu["dead_letter"]["count"], 1)
        self.assertIn("retry_policy", feishu)
        self.assertEqual(feishu["retry_policy"]["progress_max_retries"], 2)
        self.assertIn("websocket", feishu)

    def test_runtime_diagnostics_redact_feishu_websocket_endpoint_secrets(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.feishu_socket_service.state.endpoint_url = (
            "wss://msg-frontier.feishu.cn/ws/v2"
            "?device_id=123"
            "&access_key=secret-access"
            "&service_id=456"
            "&ticket=secret-ticket"
        )
        runtime.feishu_socket_service.state.connection_id = "123"
        runtime.feishu_socket_service.state.service_id = "456"
        with TestClient(app) as client:
            runtime_diag = client.get("/diagnostics/runtime")

        self.assertEqual(runtime_diag.status_code, 200)
        websocket = runtime_diag.json()["channels"]["feishu"]["websocket"]
        self.assertEqual(
            websocket["endpoint_url"],
            "wss://msg-frontier.feishu.cn/ws/v2?device_id=123&access_key=REDACTED&service_id=456&ticket=REDACTED",
        )


if __name__ == "__main__":
    unittest.main()
