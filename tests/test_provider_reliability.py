import unittest
from types import SimpleNamespace

from marten_runtime.runtime.llm_client import LLMRequest
from marten_runtime.runtime.usage_models import ProviderCallAttempt, ProviderCallDiagnostics
from marten_runtime.runtime.provider_reliability import (
    build_provider_call_diagnostics,
    build_provider_health_summary,
    classify_provider_error_kind,
)


class ProviderReliabilityTests(unittest.TestCase):
    def test_classify_provider_error_kind_maps_expected_codes_and_details(self) -> None:
        self.assertEqual(
            classify_provider_error_kind(error_code="PROVIDER_AUTH_ERROR", error_detail="401"),
            "auth",
        )
        self.assertEqual(
            classify_provider_error_kind(
                error_code="PROVIDER_RATE_LIMITED",
                error_detail="429 rate limit exceeded",
            ),
            "quota",
        )
        self.assertEqual(
            classify_provider_error_kind(
                error_code="PROVIDER_HTTP_ERROR",
                error_detail="400 prompt too long",
            ),
            "context",
        )
        self.assertEqual(
            classify_provider_error_kind(
                error_code="PROVIDER_RESPONSE_INVALID",
                error_detail="missing choices",
            ),
            "protocol",
        )
        self.assertEqual(
            classify_provider_error_kind(
                error_code="PROVIDER_PROTOCOL_ERROR",
                error_detail="provider_missing_responses_api_support:minimax",
            ),
            "protocol",
        )
        self.assertEqual(
            classify_provider_error_kind(
                error_code="PROVIDER_TRANSPORT_ERROR",
                error_detail="connection reset",
            ),
            "transient",
        )
        self.assertEqual(
            classify_provider_error_kind(
                error_code="PROVIDER_HTTP_ERROR",
                error_detail="503 Service Unavailable",
            ),
            "transient",
        )
        self.assertEqual(
            classify_provider_error_kind(
                error_code="PROVIDER_HTTP_ERROR",
                error_detail="502 Bad Gateway",
            ),
            "transient",
        )
        self.assertEqual(
            classify_provider_error_kind(
                error_code="PROVIDER_HTTP_ERROR",
                error_detail="request token count 5000 error id 1503",
            ),
            "protocol",
        )

    def test_build_provider_call_diagnostics_sets_provider_metadata_and_retry_hint(self) -> None:
        diagnostics = build_provider_call_diagnostics(
            request_kind="interactive",
            timeout_seconds=20,
            max_attempts=3,
            completed=False,
            final_error_code="PROVIDER_RATE_LIMITED",
            attempts=[
                ProviderCallAttempt(
                    attempt=1,
                    elapsed_ms=12,
                    ok=False,
                    error_code="PROVIDER_RATE_LIMITED",
                    error_detail="429 rate limit exceeded",
                    retryable=True,
                )
            ],
            provider_name="openai",
            model_name="gpt-5.4",
            profile_name="openai_primary",
            error_detail="429 rate limit exceeded",
        )

        self.assertIsInstance(diagnostics, ProviderCallDiagnostics)
        self.assertEqual(diagnostics.provider_name, "openai")
        self.assertEqual(diagnostics.model_name, "gpt-5.4")
        self.assertEqual(diagnostics.profile_name, "openai_primary")
        self.assertEqual(diagnostics.error_kind, "quota")
        self.assertEqual(diagnostics.retry_after_seconds, 30)

    def test_build_provider_health_summary_uses_stable_shape(self) -> None:
        successful_call = ProviderCallDiagnostics(
            request_kind="interactive",
            timeout_seconds=20,
            max_attempts=3,
            completed=True,
            final_error_code=None,
            attempts=[
                ProviderCallAttempt(
                    attempt=1,
                    elapsed_ms=9,
                    ok=True,
                    error_code=None,
                    error_detail=None,
                    retryable=False,
                )
            ],
            provider_name="openai",
            model_name="gpt-5.4",
            profile_name="openai_primary",
            error_kind=None,
            retry_after_seconds=0,
        )
        failed_call = ProviderCallDiagnostics(
            request_kind="interactive",
            timeout_seconds=20,
            max_attempts=3,
            completed=False,
            final_error_code="PROVIDER_TRANSPORT_ERROR",
            attempts=[
                ProviderCallAttempt(
                    attempt=1,
                    elapsed_ms=11,
                    ok=False,
                    error_code="PROVIDER_TRANSPORT_ERROR",
                    error_detail="connection reset",
                    retryable=True,
                ),
                ProviderCallAttempt(
                    attempt=2,
                    elapsed_ms=14,
                    ok=False,
                    error_code="PROVIDER_TRANSPORT_ERROR",
                    error_detail="connection reset",
                    retryable=True,
                ),
            ],
            provider_name="minimax",
            model_name="MiniMax-M2.5",
            profile_name="minimax_fast",
            error_kind="transient",
            retry_after_seconds=2,
        )
        runs = [
            SimpleNamespace(
                run_id="run_1",
                status="succeeded",
                provider_calls=[successful_call],
                attempted_providers=["openai"],
                final_provider_ref="openai",
                final_text="ok",
            ),
            SimpleNamespace(
                run_id="run_2",
                status="failed",
                provider_calls=[failed_call],
                attempted_providers=["openai", "minimax"],
                final_provider_ref="minimax",
                final_text="",
            ),
        ]

        summary = build_provider_health_summary(runs, window_size=20)

        self.assertEqual(summary.window_size, 20)
        self.assertEqual(summary.run_count, 2)
        self.assertEqual(summary.retry_count, 1)
        self.assertEqual(summary.fallback_count, 1)
        self.assertEqual(summary.provider_error_count, 1)
        self.assertEqual(summary.empty_output_count, 1)
        self.assertEqual(summary.latest_final_provider_ref, "minimax")
        self.assertEqual(summary.top_error_kinds[0].error_kind, "transient")
        self.assertEqual(summary.latest_runs[-1].run_id, "run_2")
        self.assertEqual(summary.latest_runs[-1].retry_count, 1)


if __name__ == "__main__":
    unittest.main()
