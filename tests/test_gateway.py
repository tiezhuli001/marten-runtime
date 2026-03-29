import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from marten_runtime.gateway.dedupe import build_dedupe_key
from marten_runtime.gateway.ingress import ingest_message
from marten_runtime.gateway.models import InboundEnvelope
from tests.http_app_support import build_test_app


class GatewayTests(unittest.TestCase):
    def test_build_dedupe_key_is_stable(self) -> None:
        key_a = build_dedupe_key(
            channel_id="http",
            conversation_id="conv-1",
            user_id="user-1",
            message_id="msg-1",
        )
        key_b = build_dedupe_key(
            channel_id="http",
            conversation_id="conv-1",
            user_id="user-1",
            message_id="msg-1",
        )

        self.assertEqual(key_a, key_b)
        self.assertGreaterEqual(len(key_a), 8)

    def test_ingest_message_generates_trace_and_envelope(self) -> None:
        envelope = ingest_message(
            {
                "channel_id": "http",
                "user_id": "demo",
                "conversation_id": "conv-1",
                "message_id": "msg-1",
                "body": "hello",
            }
        )

        self.assertIsInstance(envelope, InboundEnvelope)
        self.assertEqual(envelope.channel_id, "http")
        self.assertEqual(envelope.body, "hello")
        self.assertTrue(envelope.trace_id.startswith("trace_"))
        self.assertGreaterEqual(len(envelope.dedupe_key), 8)

    def test_inbound_envelope_requires_trace_and_dedupe(self) -> None:
        envelope = InboundEnvelope(
            channel_id="http",
            user_id="demo",
            conversation_id="conv-1",
            message_id="msg-1",
            body="hello",
            received_at=datetime.now(timezone.utc),
            dedupe_key="dedupe_1",
            trace_id="trace_1",
        )

        self.assertEqual(envelope.trace_id, "trace_1")
        self.assertEqual(envelope.dedupe_key, "dedupe_1")

    def test_http_sessions_endpoint_returns_session_id(self) -> None:
        with TestClient(build_test_app()) as client:
            response = client.post("/sessions", json={})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("session_id", payload)
        self.assertTrue(payload["session_id"].startswith("sess_"))

    def test_http_messages_endpoint_returns_progress_and_final_events(self) -> None:
        with TestClient(build_test_app()) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-http",
                    "message_id": "msg-http-1",
                    "body": "hello",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("session_id", payload)
        self.assertEqual(len(payload["events"]), 2)
        self.assertEqual(payload["events"][0]["event_type"], "progress")
        self.assertEqual(payload["events"][1]["event_type"], "final")
        self.assertEqual(payload["events"][0]["run_id"], payload["events"][1]["run_id"])
        self.assertEqual(payload["events"][0]["trace_id"], payload["events"][1]["trace_id"])


if __name__ == "__main__":
    unittest.main()
