import unittest

from fastapi.testclient import TestClient

from tests.http_app_support import build_test_app


class TraceCorrelationTests(unittest.TestCase):
    def test_trace_endpoint_correlates_to_run_and_events(self) -> None:
        with TestClient(build_test_app()) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "trace-corr",
                    "message_id": "1",
                    "body": "hello",
                },
            ).json()
            trace_id = response["events"][0]["trace_id"]
            diagnostics = client.get(f"/diagnostics/trace/{trace_id}").json()

        self.assertEqual(diagnostics["trace_id"], trace_id)
        self.assertEqual(len(diagnostics["run_ids"]), 1)
        self.assertEqual(len(diagnostics["event_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
