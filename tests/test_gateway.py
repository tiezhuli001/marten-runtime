import threading
import time
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from marten_runtime.gateway.dedupe import build_dedupe_key
from marten_runtime.gateway.ingress import ingest_message
from marten_runtime.gateway.models import InboundEnvelope
from marten_runtime.runtime.events import OutboundEvent
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

    def test_http_messages_endpoint_queues_same_conversation_overlap(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        first_started = threading.Event()
        release_first = threading.Event()
        entered: list[str] = []

        def blocking_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            entered.append(trace_id or "")
            if len(entered) == 1:
                first_started.set()
                release_first.wait(timeout=2)
            run_id = f"run_{len(entered)}"
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id=run_id,
                    event_id=f"evt_{run_id}_progress",
                    event_type="progress",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "running"},
                    created_at=datetime.now(timezone.utc),
                ),
                OutboundEvent(
                    session_id=session_id,
                    run_id=run_id,
                    event_id=f"evt_{run_id}_final",
                    event_type="final",
                    sequence=2,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": message},
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        runtime.runtime_loop.run = blocking_run  # type: ignore[method-assign]
        responses: dict[str, object] = {}

        with TestClient(app) as client:
            def send(name: str, body: str) -> None:
                responses[name] = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "conv-busy",
                        "message_id": f"msg-{name}",
                        "body": body,
                    },
                )

            first_thread = threading.Thread(target=send, args=("first", "hello-1"))
            second_thread = threading.Thread(target=send, args=("second", "hello-2"))
            first_thread.start()
            self.assertTrue(first_started.wait(timeout=2))
            second_thread.start()
            payload = None
            for _ in range(20):
                queue_diag = client.get("/diagnostics/queue")
                self.assertEqual(queue_diag.status_code, 200)
                payload = queue_diag.json()
                if payload["queued_lane_count"] == 1:
                    break
                time.sleep(0.02)
            assert payload is not None
            self.assertEqual(payload["active_lane_count"], 1)
            self.assertEqual(payload["queued_lane_count"], 1)
            self.assertEqual(payload["queued_items_total"], 1)
            release_first.set()
            first_thread.join(timeout=2)
            second_thread.join(timeout=2)

        first_response = responses["first"]
        second_response = responses["second"]
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.json()["events"][-1]["payload"]["text"], "hello-1")
        self.assertEqual(second_response.json()["events"][-1]["payload"]["text"], "hello-2")
        self.assertEqual(entered, [first_response.json()["trace_id"], second_response.json()["trace_id"]])

    def test_http_messages_endpoint_still_runs_for_different_conversation(self) -> None:
        app = build_test_app()
        with TestClient(app) as client:
            left = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-left",
                    "message_id": "msg-http-left",
                    "body": "hello-left",
                },
            )
            right = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-right",
                    "message_id": "msg-http-right",
                    "body": "hello-right",
                },
            )

        self.assertEqual(left.status_code, 200)
        self.assertEqual(right.status_code, 200)
        self.assertEqual(left.json()["events"][-1]["event_type"], "final")
        self.assertEqual(right.json()["events"][-1]["event_type"], "final")


if __name__ == "__main__":
    unittest.main()
