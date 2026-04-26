import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from marten_runtime.interfaces.http.app import create_app
from marten_runtime.interfaces.http.bootstrap_runtime import build_http_runtime
from marten_runtime.observability.langfuse import build_langfuse_observer


class CountingObserver:
    def __init__(self, *, enabled: bool = True, configured: bool = True) -> None:
        self._enabled = enabled
        self._configured = configured
        self.flush_count = 0
        self.shutdown_count = 0

    @property
    def base_url(self) -> str | None:
        return "https://langfuse.example" if self._configured else None

    def enabled(self) -> bool:
        return self._enabled

    def configured(self) -> bool:
        return self._configured

    def config_reason(self) -> str | None:
        return None if self._configured else "missing_langfuse_config"

    def status(self) -> dict[str, object]:
        return {
            "enabled": self._enabled,
            "configured": self._configured,
            "base_url": self.base_url,
            "reason": self.config_reason(),
        }

    def flush(self) -> None:
        self.flush_count += 1

    def shutdown(self) -> None:
        self.shutdown_count += 1


class FlushFailingObserver(CountingObserver):
    def flush(self) -> None:
        self.flush_count += 1
        raise RuntimeError("flush boom")


class LangfuseBootstrapTests(unittest.TestCase):
    def test_build_http_runtime_attaches_noop_observer_without_langfuse_config(self) -> None:
        runtime = build_http_runtime(
            env={"MINIMAX_API_KEY": "test-key", "OPENAI_API_KEY": "test-key"},
            load_env_file=False,
        )

        self.assertTrue(hasattr(runtime, "langfuse_observer"))
        self.assertFalse(runtime.langfuse_observer.enabled())
        self.assertFalse(runtime.langfuse_observer.configured())
        self.assertEqual(
            runtime.langfuse_observer.config_reason(), "missing_langfuse_config"
        )

    def test_build_http_runtime_can_attach_enabled_observer_when_builder_returns_one(self) -> None:
        expected = CountingObserver(enabled=True, configured=True)
        with patch(
            "marten_runtime.interfaces.http.bootstrap_runtime.build_langfuse_observer",
            return_value=expected,
        ):
            runtime = build_http_runtime(
                env={
                    "MINIMAX_API_KEY": "test-key",
                    "OPENAI_API_KEY": "test-key",
                    "LANGFUSE_PUBLIC_KEY": "pk-test",
                    "LANGFUSE_SECRET_KEY": "sk-test",
                    "LANGFUSE_BASE_URL": "https://langfuse.example",
                },
                load_env_file=False,
            )

        self.assertIs(runtime.langfuse_observer, expected)
        self.assertTrue(runtime.langfuse_observer.enabled())
        self.assertTrue(runtime.langfuse_observer.configured())

    def test_create_app_lifespan_flushes_and_shuts_down_langfuse_observer_once(self) -> None:
        app = create_app(
            env={"MINIMAX_API_KEY": "test-key", "OPENAI_API_KEY": "test-key"},
            load_env_file=False,
        )
        observer = CountingObserver(enabled=True, configured=True)
        app.state.runtime.langfuse_observer = observer

        with TestClient(app):
            pass

        self.assertEqual(observer.flush_count, 1)
        self.assertEqual(observer.shutdown_count, 1)

    def test_create_app_lifespan_continues_shutdown_when_langfuse_flush_raises(self) -> None:
        app = create_app(
            env={"MINIMAX_API_KEY": "test-key", "OPENAI_API_KEY": "test-key"},
            load_env_file=False,
        )
        observer = FlushFailingObserver(enabled=True, configured=True)
        app.state.runtime.langfuse_observer = observer

        with TestClient(app):
            pass

        self.assertEqual(observer.flush_count, 1)
        self.assertEqual(observer.shutdown_count, 1)

    def test_build_langfuse_observer_keeps_full_config_disabled_when_sdk_is_unavailable(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
