import unittest

from marten_runtime.config.models_loader import ModelProfile
from marten_runtime.runtime.llm_client import LLMRequest, estimate_request_tokens
from marten_runtime.session.compaction_trigger import (
    CompactionDecision,
    build_compaction_settings,
    decide_compaction,
    is_reactive_compaction_error,
)
from marten_runtime.tools.registry import ToolSnapshot


class CompactionTriggerTests(unittest.TestCase):
    def test_decision_returns_none_below_threshold(self) -> None:
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="hello",
            agent_id="main",
            app_id="main_agent",
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1"),
        )
        settings = build_compaction_settings(
            ModelProfile(provider="openai", model="gpt-4.1", context_window_tokens=1000, reserve_output_tokens=100)
        )

        decision = decide_compaction(
            estimated_tokens=estimate_request_tokens(request),
            settings=settings,
            has_follow_up_work=False,
        )

        self.assertEqual(decision, CompactionDecision.NONE)

    def test_decision_returns_proactive_compact_when_ratio_and_followup_match(self) -> None:
        settings = build_compaction_settings(
            ModelProfile(
                provider="openai",
                model="gpt-4.1",
                context_window_tokens=1000,
                reserve_output_tokens=100,
                compact_trigger_ratio=0.5,
            )
        )

        decision = decide_compaction(
            estimated_tokens=600,
            settings=settings,
            has_follow_up_work=True,
        )

        self.assertEqual(decision, CompactionDecision.PROACTIVE)


    def test_decision_returns_advisory_without_followup_even_above_threshold(self) -> None:
        settings = build_compaction_settings(
            ModelProfile(
                provider="openai",
                model="gpt-4.1",
                context_window_tokens=1000,
                reserve_output_tokens=100,
                compact_trigger_ratio=0.5,
            )
        )

        decision = decide_compaction(
            estimated_tokens=600,
            settings=settings,
            has_follow_up_work=False,
        )

        self.assertEqual(decision, CompactionDecision.ADVISORY)

    def test_decision_uses_unknown_model_fallback_window(self) -> None:
        settings = build_compaction_settings(ModelProfile(provider="openai", model="gpt-4.1"))

        self.assertEqual(settings.context_window_tokens, 200000)
        self.assertEqual(settings.reserve_output_tokens, 16000)
        self.assertEqual(settings.compact_trigger_ratio, 0.8)


    def test_build_compaction_settings_preserves_explicit_zero_reserve_output_tokens(self) -> None:
        settings = build_compaction_settings(
            ModelProfile(
                provider="openai",
                model="gpt-4.1",
                context_window_tokens=80,
                reserve_output_tokens=0,
                compact_trigger_ratio=0.2,
            )
        )

        self.assertEqual(settings.context_window_tokens, 80)
        self.assertEqual(settings.reserve_output_tokens, 0)
        self.assertEqual(settings.effective_window, 80)
        self.assertEqual(settings.proactive_threshold, 16)

    def test_reactive_decision_matches_prompt_too_long_error(self) -> None:
        self.assertTrue(is_reactive_compaction_error(RuntimeError("provider_http_error:400:prompt too long")))
        self.assertFalse(is_reactive_compaction_error(RuntimeError("provider_transport_error:connection reset")))
