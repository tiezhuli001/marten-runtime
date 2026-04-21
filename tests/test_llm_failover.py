import unittest

from marten_runtime.runtime.llm_failover import (
    next_fallback_profile,
    should_failover,
)


class LLMFailoverTests(unittest.TestCase):
    def test_allowed_provider_errors_trigger_failover(self) -> None:
        for error_code in (
            "PROVIDER_RATE_LIMITED",
            "PROVIDER_UPSTREAM_UNAVAILABLE",
            "PROVIDER_TIMEOUT",
            "PROVIDER_TRANSPORT_ERROR",
            "PROVIDER_RESPONSE_INVALID",
            "EMPTY_FINAL_RESPONSE",
        ):
            self.assertTrue(should_failover(error_code, "llm_first"))
            self.assertTrue(should_failover(error_code, "llm_second"))

    def test_auth_and_config_errors_do_not_trigger_failover(self) -> None:
        self.assertFalse(should_failover("PROVIDER_AUTH_ERROR", "llm_first"))
        self.assertFalse(should_failover("RUNTIME_LOOP_FAILED", "llm_second"))

    def test_next_fallback_profile_preserves_declared_order(self) -> None:
        fallback = next_fallback_profile(
            "openai_gpt5",
            ["kimi_k2", "minimax_m25"],
            ["openai_gpt5"],
        )

        self.assertEqual(fallback, "kimi_k2")

    def test_next_fallback_profile_skips_attempted_profiles(self) -> None:
        fallback = next_fallback_profile(
            "openai_gpt5",
            ["kimi_k2", "minimax_m25"],
            ["openai_gpt5", "kimi_k2"],
        )

        self.assertEqual(fallback, "minimax_m25")

    def test_next_fallback_profile_returns_none_when_chain_exhausted(self) -> None:
        fallback = next_fallback_profile(
            "openai_gpt5",
            ["kimi_k2"],
            ["openai_gpt5", "kimi_k2"],
        )

        self.assertIsNone(fallback)


if __name__ == "__main__":
    unittest.main()
