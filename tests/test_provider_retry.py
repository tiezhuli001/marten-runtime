import unittest

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
        for status in ("429", "502", "503", "504"):
            attempts = {"count": 0}

            def flaky_status() -> str:
                attempts["count"] += 1
                if attempts["count"] < 3:
                    raise RuntimeError(f"provider_http_error:{status}:temporary failure")
                return "ok"

            result = with_retry(flaky_status, policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0))

            self.assertEqual(result, "ok")
            self.assertEqual(attempts["count"], 3)

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


if __name__ == "__main__":
    unittest.main()
