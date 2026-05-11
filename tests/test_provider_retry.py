import threading
import unittest
from unittest import mock

import httpx

from marten_runtime.runtime.provider_retry import ProviderTransportError, RetryPolicy, with_retry


class ProviderRetryTests(unittest.TestCase):
    def test_retry_succeeds_after_timeout(self) -> None:
        attempts = {"count": 0}

        def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise TimeoutError("timed out")
            return "ok"

        result = with_retry(flaky, policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0))

        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 3)

    def test_retry_wraps_final_transport_failure_with_stable_code(self) -> None:
        attempts = {"count": 0}

        def broken() -> str:
            attempts["count"] += 1
            raise RuntimeError("provider_transport_error:connection reset")

        with self.assertRaises(ProviderTransportError) as ctx:
            with_retry(broken, policy=RetryPolicy(max_attempts=2, base_backoff_seconds=0))

        self.assertEqual(ctx.exception.error_code, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(attempts["count"], 2)

    def test_retry_does_not_retry_auth_failures(self) -> None:
        attempts = {"count": 0}

        def unauthorized() -> str:
            attempts["count"] += 1
            raise RuntimeError("provider_http_error:401:unauthorized")

        with self.assertRaises(ProviderTransportError) as ctx:
            with_retry(unauthorized, policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0))

        self.assertEqual(ctx.exception.error_code, "PROVIDER_AUTH_ERROR")
        self.assertEqual(attempts["count"], 1)

    def test_retry_retries_retryable_upstream_http_statuses(self) -> None:
        for status in ("429", "502", "503", "504", "529"):
            attempts = {"count": 0}

            def flaky_status() -> str:
                attempts["count"] += 1
                if attempts["count"] < 3:
                    raise RuntimeError(f"provider_http_error:{status}:temporary failure")
                return "ok"

            result = with_retry(flaky_status, policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0))

            self.assertEqual(result, "ok")
            self.assertEqual(attempts["count"], 3)

    def test_retry_retries_httpx_status_error_from_stream_transport(self) -> None:
        attempts = {"count": 0}

        def flaky_status() -> str:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise httpx.HTTPStatusError(
                    "Server error '502 Bad Gateway' for url 'https://example.com/responses'",
                    request=httpx.Request("POST", "https://example.com/responses"),
                    response=httpx.Response(502, text="bad gateway"),
                )
            return "ok"

        result = with_retry(
            flaky_status,
            policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0),
        )

        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 3)

    def test_retry_after_seconds_reads_http_date_header(self) -> None:
        request = httpx.Request("POST", "https://example.com/responses")
        response = httpx.Response(
            429,
            request=request,
            headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"},
        )
        error = httpx.HTTPStatusError("rate limited", request=request, response=response)

        from datetime import datetime, timezone

        frozen_now = datetime(2026, 10, 21, 7, 27, 30, tzinfo=timezone.utc)
        with mock.patch("marten_runtime.runtime.provider_retry._utc_now", return_value=frozen_now):
            with self.assertRaises(ProviderTransportError) as ctx:
                with_retry(
                    lambda: (_ for _ in ()).throw(error),
                    policy=RetryPolicy(max_attempts=1, base_backoff_seconds=0),
                )

        self.assertEqual(ctx.exception.retry_after_seconds, 30.0)

    def test_retry_does_not_retry_forbidden_failures(self) -> None:
        attempts = {"count": 0}

        def forbidden() -> str:
            attempts["count"] += 1
            raise RuntimeError("provider_http_error:403:forbidden")

        with self.assertRaises(ProviderTransportError) as ctx:
            with_retry(forbidden, policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0))

        self.assertEqual(ctx.exception.error_code, "PROVIDER_AUTH_ERROR")
        self.assertEqual(attempts["count"], 1)

    def test_retry_does_not_retry_response_invalid_failures(self) -> None:
        attempts = {"count": 0}

        def invalid_response() -> str:
            attempts["count"] += 1
            raise RuntimeError("provider_response_invalid:missing choices")

        with self.assertRaises(ProviderTransportError) as ctx:
            with_retry(invalid_response, policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0))

        self.assertEqual(ctx.exception.error_code, "PROVIDER_RESPONSE_INVALID")
        self.assertEqual(attempts["count"], 1)

    def test_retry_stops_during_backoff_when_stop_event_is_set(self) -> None:
        attempts = {"count": 0}
        stop_event = threading.Event()
        sleeps: list[float] = []

        def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] == 1:
                stop_event.set()
                raise TimeoutError("timed out")
            return "ok"

        with self.assertRaises(TimeoutError) as ctx:
            with_retry(
                flaky,
                policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0.5, jitter_ratio=0),
                stop_event=stop_event,
                sleeper=sleeps.append,
            )

        self.assertIn("PROVIDER_CALL_CANCELLED", str(ctx.exception))
        self.assertEqual(attempts["count"], 1)
        self.assertEqual(sleeps, [])

    def test_retry_stops_when_deadline_expires_before_next_attempt(self) -> None:
        attempts = {"count": 0}
        sleeps: list[float] = []

        def flaky() -> str:
            attempts["count"] += 1
            raise TimeoutError("timed out")

        with self.assertRaises(TimeoutError) as ctx:
            with_retry(
                flaky,
                policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0.5, jitter_ratio=0),
                deadline_monotonic=0.0,
                sleeper=sleeps.append,
            )

        self.assertIn("PROVIDER_CALL_TIMED_OUT", str(ctx.exception))
        self.assertEqual(attempts["count"], 0)
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()
