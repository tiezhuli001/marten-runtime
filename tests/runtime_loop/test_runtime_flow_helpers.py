import unittest

from marten_runtime.config.models_loader import ModelProfile
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMRequest, ToolExchange
from marten_runtime.runtime.provider_flow import (
    build_provider_failover_state,
    try_provider_failover,
)
from marten_runtime.runtime.request_flow import (
    resolve_request_responses_api,
    resolve_request_timeout_seconds,
)
from marten_runtime.runtime.tool_followup_support import build_finalization_retry_request


class DummyLLM:
    def __init__(self, *, provider_name: str, model_name: str, profile_name: str) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.profile_name = profile_name

    def complete(self, request):  # noqa: ANN001
        raise AssertionError("unused")


def _request(*, model_name: str = "primary", tokenizer_family: str | None = None) -> LLMRequest:
    return LLMRequest(
        session_id="sess_test",
        trace_id="trace_test",
        message="hello",
        agent_id="main",
        model_name=model_name,
        tokenizer_family=tokenizer_family,
    )


class RuntimeProviderFlowHelperTests(unittest.TestCase):
    def test_resolve_request_timeout_seconds_uses_request_kind_defaults(self) -> None:
        self.assertEqual(resolve_request_timeout_seconds(_request()), 30)
        self.assertEqual(
            resolve_request_timeout_seconds(_request().model_copy(update={"request_kind": "finalization_retry"})),
            20,
        )
        self.assertEqual(
            resolve_request_timeout_seconds(_request().model_copy(update={"request_kind": "contract_repair"})),
            30,
        )

    def test_resolve_request_timeout_seconds_prefers_override_and_special_kinds(self) -> None:
        self.assertEqual(
            resolve_request_timeout_seconds(
                _request().model_copy(update={"timeout_seconds_override": 1.25})
            ),
            2,
        )
        self.assertEqual(
            resolve_request_timeout_seconds(
                _request().model_copy(update={"request_kind": "interactive"})
            ),
            20,
        )
        self.assertEqual(
            resolve_request_timeout_seconds(
                _request().model_copy(update={"request_kind": "subagent"})
            ),
            60,
        )
        self.assertEqual(
            resolve_request_timeout_seconds(
                _request().model_copy(
                    update={
                        "tool_history": [ToolExchange(tool_name="time")],
                    }
                )
            ),
            20,
        )
        self.assertEqual(
            resolve_request_timeout_seconds(
                _request().model_copy(
                    update={
                        "request_kind": "interactive",
                        "tool_history": [ToolExchange(tool_name="time")],
                    }
                ),
                model_name="gpt-5.4",
                responses_api=False,
            ),
            40,
        )

    def test_bazi_finalization_has_budget_for_detailed_analysis(self) -> None:
        request = _request().model_copy(
            update={"agent_id": "bazi", "request_kind": "finalization_retry"}
        )

        self.assertEqual(resolve_request_timeout_seconds(request), 90)
        self.assertEqual(
            resolve_request_timeout_seconds(
                request.model_copy(update={"agent_id": "main"})
            ),
            20,
        )
        self.assertEqual(
            resolve_request_timeout_seconds(
                request.model_copy(update={"request_kind": "bazi_output_repair"})
            ),
            90,
        )

    def test_bazi_finalization_retry_discards_nonessential_context(self) -> None:
        request = _request().model_copy(
            update={
                "agent_id": "bazi",
                "compact_summary_text": "large summary",
                "working_context": {"large": "context"},
                "working_context_text": "large working context",
                "skill_heads_text": "skill heads",
                "capability_catalog_text": "capabilities",
                "always_on_skill_text": "always on",
                "channel_protocol_instruction_text": "card protocol",
                "repository_context_text": "repository context",
                "activated_skill_ids": ["bazi_analysis"],
                "activated_skill_bodies": ["large skill body"],
            }
        )

        retry = build_finalization_retry_request(
            request,
            tool_history=[],
        )

        self.assertIsNone(retry.compact_summary_text)
        self.assertEqual(retry.working_context, {})
        self.assertIsNone(retry.working_context_text)
        self.assertIsNone(retry.skill_heads_text)
        self.assertIsNone(retry.capability_catalog_text)
        self.assertIsNone(retry.always_on_skill_text)
        self.assertIsNone(retry.channel_protocol_instruction_text)
        self.assertIsNone(retry.repository_context_text)
        self.assertEqual(retry.activated_skill_ids, [])
        self.assertEqual(retry.activated_skill_bodies, [])

    def test_bazi_generation_after_knowledge_search_has_detailed_analysis_budget(self) -> None:
        request = _request(model_name="gpt-5.4").model_copy(
            update={
                "agent_id": "bazi",
                "request_kind": "interactive",
                "tool_history": [
                    ToolExchange(
                        tool_name="knowledge",
                        tool_payload={"action": "search"},
                        tool_result={"ok": True, "action": "search"},
                    )
                ],
            }
        )

        self.assertEqual(
            resolve_request_timeout_seconds(
                request,
                model_name="gpt-5.4",
                responses_api=False,
            ),
            90,
        )

    def test_resolve_request_responses_api_tracks_gpt_5_chat_fallback(self) -> None:
        self.assertTrue(
            resolve_request_responses_api(
                _request(model_name="gpt-5.4"),
                model_name="gpt-5.4",
                supports_responses_api=True,
                supports_chat_completions=True,
            )
        )
        self.assertFalse(
            resolve_request_responses_api(
                _request(model_name="gpt-5.4"),
                model_name="gpt-5.4",
                supports_responses_api=False,
                supports_chat_completions=True,
            )
        )
        self.assertIsNone(
            resolve_request_responses_api(
                _request(model_name="gpt-5.4"),
                model_name="gpt-5.4",
                supports_responses_api=False,
                supports_chat_completions=False,
            )
        )

    def test_try_provider_failover_updates_provider_state_and_rebinds_requests(self) -> None:
        primary_llm = DummyLLM(
            provider_name="openai",
            model_name="gpt-5.4",
            profile_name="openai_primary",
        )
        fallback_llm = DummyLLM(
            provider_name="minimax",
            model_name="MiniMax-M2.5",
            profile_name="minimax_fast",
        )
        profiles = {
            "openai_primary": ModelProfile(
                provider_ref="openai",
                model="gpt-5.4",
                fallback_profiles=["missing_profile", "minimax_fast"],
                tokenizer_family="o200k_base",
            ),
            "minimax_fast": ModelProfile(
                provider_ref="minimax",
                model="MiniMax-M2.5",
                tokenizer_family="minimax",
            ),
        }

        def resolver(name: str):  # noqa: ANN001
            if name == "missing_profile":
                raise ValueError("profile unavailable")
            return fallback_llm, profiles[name]

        state = build_provider_failover_state(
            llm=primary_llm,
            active_profile_name="openai_primary",
            tokenizer_family="o200k_base",
            profile_runtime_resolver=lambda name: (primary_llm, profiles[name]),
        )
        history = InMemoryRunHistory()
        run = history.start(
            session_id="sess_test",
            trace_id="trace_test",
            config_snapshot_id="cfg",
            bootstrap_manifest_id="boot",
            context_snapshot_id="ctx",
            skill_snapshot_id="skill",
            tool_snapshot_id="tool",
        )

        result = try_provider_failover(
            state=state,
            history=history,
            run_id=run.run_id,
            profile_runtime_resolver=resolver,
            stage="llm_first",
            error_code="PROVIDER_TRANSPORT_ERROR",
            first_request=_request(model_name="gpt-5.4", tokenizer_family="o200k_base"),
            current_request=_request(model_name="gpt-5.4", tokenizer_family="o200k_base"),
            request_adapter=lambda request, llm, tokenizer: request.model_copy(
                update={
                    "model_name": llm.model_name,
                    "tokenizer_family": tokenizer,
                }
            ),
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIs(result.llm, fallback_llm)
        self.assertEqual(result.first_request.model_name, "MiniMax-M2.5")
        self.assertEqual(result.current_request.tokenizer_family, "minimax")
        self.assertEqual(state.active_profile_name, "minimax_fast")
        self.assertEqual(state.attempted_profiles, ["openai_primary", "missing_profile", "minimax_fast"])
        self.assertEqual(state.attempted_providers, ["openai", "minimax"])
        self.assertEqual(state.failover_trigger, "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(state.failover_stage, "llm_first")
        run_record = history.get(run.run_id)
        self.assertEqual(run_record.final_provider_ref, "minimax")
        self.assertEqual(run_record.failover_skipped_profiles[0]["profile_name"], "missing_profile")

    def test_try_provider_failover_ignores_unapproved_stage(self) -> None:
        llm = DummyLLM(
            provider_name="openai",
            model_name="gpt-5.4",
            profile_name="openai_primary",
        )
        profile = ModelProfile(
            provider_ref="openai",
            model="gpt-5.4",
            fallback_profiles=["minimax_fast"],
        )
        state = build_provider_failover_state(
            llm=llm,
            active_profile_name="openai_primary",
            tokenizer_family=None,
            profile_runtime_resolver=lambda name: (llm, profile),
        )
        history = InMemoryRunHistory()
        run = history.start(
            session_id="sess_test",
            trace_id="trace_test",
            config_snapshot_id="cfg",
            bootstrap_manifest_id="boot",
            context_snapshot_id="ctx",
            skill_snapshot_id="skill",
            tool_snapshot_id="tool",
        )

        result = try_provider_failover(
            state=state,
            history=history,
            run_id=run.run_id,
            profile_runtime_resolver=lambda name: (llm, profile),
            stage="tool_execution",
            error_code="PROVIDER_TRANSPORT_ERROR",
            first_request=_request(),
            current_request=_request(),
            request_adapter=lambda request, _llm, _tokenizer: request,
        )

        self.assertIsNone(result)
        self.assertEqual(state.attempted_profiles, ["openai_primary"])


if __name__ == "__main__":
    unittest.main()
