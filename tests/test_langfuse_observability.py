import unittest
from unittest.mock import patch

from marten_runtime.observability.langfuse import (
    LangfuseRunHandle,
    _SDKLangfuseClient,
    build_langfuse_observer,
)


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.traces: list[dict] = []
        self.generations: list[dict] = []
        self.tool_spans: list[dict] = []
        self.finalizations: list[dict] = []
        self.flush_count = 0
        self.shutdown_count = 0

    def create_trace(self, payload: dict) -> dict:
        self.traces.append(payload)
        return {
            "trace_id": payload.get("trace_id") or "lf-trace-generated",
            "url": "https://langfuse.example/trace/lf-trace-generated",
        }

    def record_generation(self, payload: dict) -> None:
        self.generations.append(payload)

    def record_tool_span(self, payload: dict) -> None:
        self.tool_spans.append(payload)

    def finalize_trace(self, payload: dict) -> None:
        self.finalizations.append(payload)

    def flush(self) -> None:
        self.flush_count += 1

    def shutdown(self) -> None:
        self.shutdown_count += 1


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


class FlushFailingShutdownCountingClient:
    def __init__(self) -> None:
        self.flush_count = 0
        self.shutdown_count = 0

    def create_trace(self, payload: dict) -> dict:
        return {
            "trace_id": payload.get("trace_id") or "lf-trace-generated",
            "url": None,
        }

    def record_generation(self, payload: dict) -> None:
        del payload

    def record_tool_span(self, payload: dict) -> None:
        del payload

    def finalize_trace(self, payload: dict) -> None:
        del payload

    def flush(self) -> None:
        self.flush_count += 1
        raise RuntimeError("langfuse flush boom")

    def shutdown(self) -> None:
        self.shutdown_count += 1


class FlakyCreateTraceClient:
    def __init__(self) -> None:
        self.create_calls = 0

    def create_trace(self, payload: dict) -> dict:
        self.create_calls += 1
        if self.create_calls == 1:
            raise RuntimeError("langfuse create boom")
        return {
            "trace_id": payload.get("trace_id") or "lf-trace-generated",
            "url": "https://langfuse.example/trace/recovered",
        }

    def record_generation(self, payload: dict) -> None:
        del payload

    def record_tool_span(self, payload: dict) -> None:
        del payload

    def finalize_trace(self, payload: dict) -> None:
        del payload

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class LangfuseObservabilityTests(unittest.TestCase):
    def test_sdk_client_normalizes_runtime_trace_id_into_langfuse_hex_trace_id(self) -> None:
        class StubObservation:
            def __init__(self, trace_id: str) -> None:
                self.trace_id = trace_id

            def start_observation(self, **kwargs):
                return StubObservation(self.trace_id)

            def update(self, **kwargs) -> None:
                del kwargs

            def end(self) -> None:
                pass

        class StubSDKClient:
            def __init__(self) -> None:
                self.received_trace_context = None
                self.seed = None

            def create_trace_id(self, *, seed: str) -> str:
                self.seed = seed
                return "0123456789abcdef0123456789abcdef"

            def start_observation(self, **kwargs):
                self.received_trace_context = kwargs.get("trace_context")
                return StubObservation(kwargs["trace_context"]["trace_id"])

            def get_trace_url(self, *, trace_id: str) -> str:
                return f"https://langfuse.example/trace/{trace_id}"

            def flush(self) -> None:
                pass

            def shutdown(self) -> None:
                pass

        client = _SDKLangfuseClient(StubSDKClient())

        created = client.create_trace(
            {
                "name": "runtime.turn",
                "trace_id": "trace_runtime_123",
                "input_text": "hello",
                "metadata": {"run_id": "run_123"},
            }
        )

        self.assertEqual(
            created["trace_id"], "0123456789abcdef0123456789abcdef"
        )
        self.assertEqual(
            created["url"],
            "https://langfuse.example/trace/0123456789abcdef0123456789abcdef",
        )

    def test_observer_defaults_to_disabled_and_unconfigured_without_env(self) -> None:
        observer = build_langfuse_observer(env={})

        self.assertFalse(observer.enabled())
        self.assertFalse(observer.healthy())
        self.assertFalse(observer.configured())
        self.assertEqual(observer.config_reason(), "missing_langfuse_config")
        self.assertIsNone(observer.base_url)
        self.assertEqual(observer.status(), {
            "enabled": False,
            "healthy": False,
            "configured": False,
            "base_url": None,
            "reason": "missing_langfuse_config",
        })

    def test_observer_reports_partial_config_as_disabled_noop(self) -> None:
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            }
        )

        self.assertFalse(observer.enabled())
        self.assertFalse(observer.healthy())
        self.assertFalse(observer.configured())
        self.assertEqual(observer.config_reason(), "missing_langfuse_config")
        self.assertEqual(observer.base_url, "https://langfuse.example")

        handle = observer.start_run_trace(
            name="runtime.turn",
            trace_id="trace_partial",
            metadata={"run_id": "run_partial"},
        )
        self.assertEqual(handle.trace_id, "trace_partial")
        self.assertIsNone(handle.url)
        observer.observe_generation(
            handle,
            name="llm.first",
            model="gpt-4.1",
            status="success",
            latency_ms=12,
        )
        observer.observe_tool_call(
            handle,
            name="tool.call",
            tool_name="time",
            status="success",
            latency_ms=5,
        )
        observer.finalize_run(
            handle,
            status="succeeded",
            final_text="ok",
            total_ms=20,
        )
        observer.flush()
        observer.shutdown()

    def test_observer_reports_enabled_with_full_config_and_fake_client(self) -> None:
        fake_client = FakeLangfuseClient()
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=fake_client,
        )

        self.assertTrue(observer.enabled())
        self.assertTrue(observer.healthy())
        self.assertTrue(observer.configured())
        self.assertIsNone(observer.config_reason())
        self.assertEqual(observer.base_url, "https://langfuse.example")

    def test_observer_builds_sdk_client_from_full_config_when_factory_is_available(self) -> None:
        fake_client = FakeLangfuseClient()
        with patch(
            "marten_runtime.observability.langfuse._build_sdk_client",
            return_value=fake_client,
        ):
            observer = build_langfuse_observer(
                env={
                    "LANGFUSE_PUBLIC_KEY": "pk-test",
                    "LANGFUSE_SECRET_KEY": "sk-test",
                    "LANGFUSE_BASE_URL": "https://langfuse.example",
                }
            )

        self.assertTrue(observer.enabled())
        self.assertTrue(observer.healthy())
        self.assertTrue(observer.configured())
        self.assertIsNone(observer.config_reason())
        handle = observer.start_run_trace(name="runtime.turn", trace_id="trace_sdk")
        self.assertEqual(handle.trace_id, "trace_sdk")

    def test_observer_keeps_full_config_noop_when_sdk_factory_is_unavailable(self) -> None:
        with patch(
            "marten_runtime.observability.langfuse._build_sdk_client",
            return_value=None,
        ):
            observer = build_langfuse_observer(
                env={
                    "LANGFUSE_PUBLIC_KEY": "pk-test",
                    "LANGFUSE_SECRET_KEY": "sk-test",
                    "LANGFUSE_BASE_URL": "https://langfuse.example",
                }
            )

        self.assertFalse(observer.enabled())
        self.assertFalse(observer.healthy())
        self.assertTrue(observer.configured())
        self.assertEqual(observer.config_reason(), "langfuse_sdk_unavailable")

    def test_start_run_trace_returns_handle_with_stable_ids(self) -> None:
        fake_client = FakeLangfuseClient()
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=fake_client,
        )

        handle = observer.start_run_trace(
            name="runtime.turn",
            trace_id="trace_123",
            input_text="hello",
            metadata={"run_id": "run_123", "agent_id": "main"},
            tags=["interactive"],
        )

        self.assertIsInstance(handle, LangfuseRunHandle)
        self.assertEqual(handle.trace_id, "trace_123")
        self.assertEqual(handle.url, "https://langfuse.example/trace/lf-trace-generated")
        self.assertEqual(fake_client.traces[0]["name"], "runtime.turn")
        self.assertEqual(fake_client.traces[0]["input_text"], "hello")
        self.assertEqual(fake_client.traces[0]["metadata"]["run_id"], "run_123")
        self.assertEqual(fake_client.traces[0]["tags"], ["interactive"])

    def test_generation_and_tool_observations_are_recorded_with_status_and_latency(self) -> None:
        fake_client = FakeLangfuseClient()
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=fake_client,
        )
        handle = observer.start_run_trace(name="runtime.turn", trace_id="trace_123")

        observer.observe_generation(
            handle,
            name="llm.first",
            model="gpt-4.1",
            provider="openai",
            input_payload={"message": "hello"},
            output_payload={"final_text": "world"},
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            status="success",
            latency_ms=42,
            metadata={"request_kind": "interactive"},
        )
        observer.observe_tool_call(
            handle,
            name="tool.call",
            tool_name="time",
            tool_payload={"timezone": "UTC"},
            tool_result={"iso_time": "2026-04-17T00:00:00Z"},
            status="success",
            latency_ms=7,
            metadata={"stage": "tool"},
        )

        self.assertEqual(len(fake_client.generations), 1)
        self.assertEqual(fake_client.generations[0]["name"], "llm.first")
        self.assertEqual(fake_client.generations[0]["model"], "gpt-4.1")
        self.assertEqual(fake_client.generations[0]["provider"], "openai")
        self.assertEqual(fake_client.generations[0]["status"], "success")
        self.assertEqual(fake_client.generations[0]["latency_ms"], 42)
        self.assertEqual(fake_client.generations[0]["usage"]["total_tokens"], 15)

        self.assertEqual(len(fake_client.tool_spans), 1)
        self.assertEqual(fake_client.tool_spans[0]["tool_name"], "time")
        self.assertEqual(fake_client.tool_spans[0]["status"], "success")
        self.assertEqual(fake_client.tool_spans[0]["latency_ms"], 7)

    def test_finalize_run_flush_and_shutdown_are_idempotent(self) -> None:
        fake_client = FakeLangfuseClient()
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=fake_client,
        )
        handle = observer.start_run_trace(name="runtime.turn", trace_id="trace_123")

        observer.finalize_run(
            handle,
            status="failed",
            final_text=None,
            error_code="PROVIDER_TIMEOUT",
            usage={"total_tokens": 20},
            total_ms=99,
            metadata={"llm_request_count": 1},
        )
        observer.flush()
        observer.flush()
        observer.shutdown()
        observer.shutdown()

        self.assertEqual(len(fake_client.finalizations), 1)
        self.assertEqual(fake_client.finalizations[0]["trace_id"], "trace_123")
        self.assertEqual(fake_client.finalizations[0]["status"], "failed")
        self.assertEqual(fake_client.finalizations[0]["error_code"], "PROVIDER_TIMEOUT")
        self.assertEqual(fake_client.finalizations[0]["total_ms"], 99)
        self.assertEqual(fake_client.flush_count, 2)
        self.assertEqual(fake_client.shutdown_count, 2)

    def test_sdk_client_finalize_trace_passes_usage_details_and_metadata_fallback(self) -> None:
        class StubObservation:
            def __init__(self, trace_id: str) -> None:
                self.trace_id = trace_id
                self.update_calls: list[dict] = []
                self.end_count = 0

            def start_observation(self, **kwargs):
                del kwargs
                return self

            def update(self, **kwargs) -> None:
                self.update_calls.append(kwargs)

            def end(self) -> None:
                self.end_count += 1

        class StubSDKClient:
            def __init__(self) -> None:
                self.root = StubObservation("0123456789abcdef0123456789abcdef")

            def create_trace_id(self, *, seed: str) -> str:
                del seed
                return self.root.trace_id

            def start_observation(self, **kwargs):
                del kwargs
                return self.root

            def get_trace_url(self, *, trace_id: str) -> str:
                return f"https://langfuse.example/trace/{trace_id}"

            def flush(self) -> None:
                pass

            def shutdown(self) -> None:
                pass

        sdk_client = StubSDKClient()
        client = _SDKLangfuseClient(sdk_client)
        created = client.create_trace({"name": "runtime.turn", "trace_id": "trace_runtime_123"})

        client.finalize_trace(
            {
                "trace_id": created["trace_id"],
                "status": "succeeded",
                "usage": {
                    "input_tokens": 45,
                    "output_tokens": 15,
                    "total_tokens": 60,
                },
                "total_ms": 12,
            }
        )

        update_payload = sdk_client.root.update_calls[-1]
        self.assertEqual(
            update_payload["usage_details"],
            {"input_tokens": 45, "output_tokens": 15, "total_tokens": 60},
        )
        self.assertEqual(
            update_payload["metadata"]["cumulative_usage"],
            {"input_tokens": 45, "output_tokens": 15, "total_tokens": 60},
        )
        self.assertEqual(update_payload["metadata"]["status"], "succeeded")
        self.assertEqual(update_payload["metadata"]["total_ms"], 12)
        self.assertEqual(sdk_client.root.end_count, 1)

    def test_observer_fail_opens_when_client_methods_raise(self) -> None:
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=ThrowingLangfuseClient(),
        )

        handle = observer.start_run_trace(name="runtime.turn", trace_id="trace_fail_open")
        self.assertEqual(handle.trace_id, "trace_fail_open")
        self.assertIsNone(handle.url)
        self.assertTrue(observer.enabled())
        self.assertFalse(observer.healthy())
        self.assertEqual(observer.config_reason(), "langfuse_client_error")

        observer.observe_generation(
            handle,
            name="llm.first",
            model="gpt-4.1",
            status="success",
            latency_ms=12,
        )
        observer.observe_tool_call(
            handle,
            name="tool.call",
            tool_name="time",
            status="success",
            latency_ms=5,
        )
        observer.finalize_run(
            handle,
            status="succeeded",
            final_text="ok",
            total_ms=20,
        )
        observer.flush()
        observer.shutdown()
        self.assertTrue(observer.enabled())
        self.assertFalse(observer.healthy())
        self.assertEqual(observer.config_reason(), "langfuse_client_error")

    def test_shutdown_still_calls_client_after_flush_marks_observer_unhealthy(self) -> None:
        client = FlushFailingShutdownCountingClient()
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=client,
        )

        observer.flush()
        self.assertTrue(observer.enabled())
        self.assertFalse(observer.healthy())
        self.assertEqual(observer.config_reason(), "langfuse_client_error")

        observer.shutdown()

        self.assertEqual(client.flush_count, 1)
        self.assertEqual(client.shutdown_count, 1)
        self.assertTrue(observer.enabled())
        self.assertTrue(observer.healthy())
        self.assertIsNone(observer.config_reason())

    def test_observer_recovers_after_transient_create_trace_failure(self) -> None:
        client = FlakyCreateTraceClient()
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=client,
        )

        first = observer.start_run_trace(name="runtime.turn", trace_id="trace_first")
        self.assertEqual(first.trace_id, "trace_first")
        self.assertTrue(observer.enabled())
        self.assertFalse(observer.healthy())
        self.assertEqual(observer.config_reason(), "langfuse_client_error")

        second = observer.start_run_trace(name="runtime.turn", trace_id="trace_second")
        self.assertEqual(second.trace_id, "trace_second")
        self.assertEqual(second.url, "https://langfuse.example/trace/recovered")
        self.assertEqual(client.create_calls, 2)
        self.assertTrue(observer.enabled())
        self.assertTrue(observer.healthy())
        self.assertIsNone(observer.config_reason())


if __name__ == "__main__":
    unittest.main()
