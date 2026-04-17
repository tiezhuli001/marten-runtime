import unittest

from fastapi.testclient import TestClient

from marten_runtime.observability.langfuse import build_langfuse_observer
from tests.http_app_support import build_test_app


class FakeLangfuseClient:
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


class ThrowingLangfuseClient:
    def create_trace(self, payload: dict) -> dict:
        del payload
        raise RuntimeError("langfuse create boom")

    def record_generation(self, payload: dict) -> None:
        del payload
        raise RuntimeError("langfuse generation boom")

    def record_tool_span(self, payload: dict) -> None:
        del payload
        raise RuntimeError("langfuse tool boom")

    def finalize_trace(self, payload: dict) -> None:
        del payload
        raise RuntimeError("langfuse finalize boom")

    def flush(self) -> None:
        raise RuntimeError("langfuse flush boom")

    def shutdown(self) -> None:
        raise RuntimeError("langfuse shutdown boom")


class LangfuseDiagnosticsContractTests(unittest.TestCase):
    def test_runtime_diagnostics_expose_langfuse_status(self) -> None:
        app = build_test_app()

        with TestClient(app) as client:
            body = client.get("/diagnostics/runtime").json()

        self.assertIn("observability", body)
        self.assertEqual(body["observability"]["langfuse"]["enabled"], False)
        self.assertEqual(body["observability"]["langfuse"]["healthy"], False)
        self.assertEqual(body["observability"]["langfuse"]["configured"], False)
        self.assertEqual(
            body["observability"]["langfuse"]["reason"], "missing_langfuse_config"
        )

    def test_run_and_trace_diagnostics_expose_langfuse_refs_when_observer_is_enabled(self) -> None:
        app = build_test_app()
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=FakeLangfuseClient(),
        )
        app.state.runtime.langfuse_observer = observer
        app.state.runtime.runtime_loop.langfuse_observer = observer

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "langfuse-diag",
                    "message_id": "1",
                    "body": "hello",
                },
            ).json()
            run_id = response["events"][-1]["run_id"]
            trace_id = response["trace_id"]
            run_diag = client.get(f"/diagnostics/run/{run_id}").json()
            trace_diag = client.get(f"/diagnostics/trace/{trace_id}").json()

        self.assertEqual(
            run_diag["external_observability"]["langfuse_trace_id"], trace_id
        )
        self.assertEqual(
            run_diag["external_observability"]["langfuse_url"],
            f"https://langfuse.example/trace/{trace_id}",
        )
        self.assertEqual(
            trace_diag["external_refs"]["langfuse_trace_id"], trace_id
        )
        self.assertEqual(
            trace_diag["external_refs"]["langfuse_url"],
            f"https://langfuse.example/trace/{trace_id}",
        )
        self.assertEqual(len(trace_diag["run_ids"]), 1)
        self.assertGreaterEqual(len(trace_diag["event_ids"]), 1)

    def test_runtime_diagnostics_mark_langfuse_unhealthy_after_client_error(self) -> None:
        app = build_test_app()
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=ThrowingLangfuseClient(),
        )
        app.state.runtime.langfuse_observer = observer
        app.state.runtime.runtime_loop.langfuse_observer = observer

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "langfuse-diag-error",
                    "message_id": "1",
                    "body": "hello",
                },
            )
            runtime_diag = client.get("/diagnostics/runtime").json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(runtime_diag["observability"]["langfuse"]["enabled"], True)
        self.assertEqual(runtime_diag["observability"]["langfuse"]["healthy"], False)
        self.assertEqual(runtime_diag["observability"]["langfuse"]["configured"], True)
        self.assertEqual(
            runtime_diag["observability"]["langfuse"]["reason"],
            "langfuse_client_error",
        )


if __name__ == "__main__":
    unittest.main()
