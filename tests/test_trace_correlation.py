import unittest

from fastapi.testclient import TestClient

from marten_runtime.observability.langfuse import build_langfuse_observer
from tests.http_app_support import build_test_app


class _TraceFakeLangfuseClient:
    def create_trace(self, payload: dict) -> dict:
        trace_id = str(payload.get("trace_id") or "lf-generated")
        return {"trace_id": trace_id, "url": f"https://langfuse.example/trace/{trace_id}"}

    def record_generation(self, payload: dict) -> None:
        pass

    def record_tool_span(self, payload: dict) -> None:
        pass

    def finalize_trace(self, payload: dict) -> None:
        pass

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


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

    def test_trace_endpoint_preserves_run_and_event_lists_when_langfuse_refs_are_present(self) -> None:
        app = build_test_app()
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=_TraceFakeLangfuseClient(),
        )
        app.state.runtime.langfuse_observer = observer
        app.state.runtime.runtime_loop.langfuse_observer = observer

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "trace-corr-langfuse",
                    "message_id": "1",
                    "body": "hello",
                },
            ).json()
            trace_id = response["trace_id"]
            diagnostics = client.get(f"/diagnostics/trace/{trace_id}").json()

        self.assertEqual(diagnostics["trace_id"], trace_id)
        self.assertEqual(diagnostics["external_refs"]["langfuse_trace_id"], trace_id)
        self.assertEqual(len(diagnostics["run_ids"]), 1)
        self.assertEqual(len(diagnostics["event_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
