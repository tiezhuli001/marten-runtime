from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMClient, LLMRequest
from marten_runtime.runtime.llm_failover import next_fallback_profile, should_failover


@dataclass
class ProviderFailoverState:
    active_profile_name: str
    active_tokenizer_family: str | None
    attempted_profiles: list[str]
    attempted_providers: list[str]
    failover_trigger: str | None = None
    failover_stage: str | None = None
    failover_candidates: list[str] = field(default_factory=list)

    @property
    def initial_provider_ref(self) -> str | None:
        if self.attempted_providers:
            return self.attempted_providers[0]
        return None

    def register_candidates(self, profile: Any) -> None:
        for fallback_name in list(getattr(profile, "fallback_profiles", [])):
            if fallback_name in self.failover_candidates:
                continue
            self.failover_candidates.append(fallback_name)


def build_provider_failover_state(
    *,
    llm: LLMClient,
    active_profile_name: str,
    tokenizer_family: str | None,
    profile_runtime_resolver: Callable[[str], tuple[LLMClient, object]] | None,
) -> ProviderFailoverState:
    state = ProviderFailoverState(
        active_profile_name=active_profile_name,
        active_tokenizer_family=tokenizer_family,
        attempted_profiles=[active_profile_name],
        attempted_providers=[getattr(llm, "provider_name", "unknown")],
    )
    if profile_runtime_resolver is not None:
        try:
            _, initial_profile = profile_runtime_resolver(active_profile_name)
        except ValueError:
            initial_profile = None
        if initial_profile is not None:
            state.register_candidates(initial_profile)
    return state


def set_history_failover_state(
    history: InMemoryRunHistory,
    *,
    run_id: str,
    state: ProviderFailoverState,
    final_provider_ref: str | None,
) -> None:
    history.set_failover_state(
        run_id,
        provider_ref=state.initial_provider_ref,
        attempted_profiles=state.attempted_profiles,
        attempted_providers=state.attempted_providers,
        failover_trigger=state.failover_trigger,
        failover_stage=state.failover_stage,
        final_provider_ref=final_provider_ref,
    )


@dataclass
class ProviderFailoverResult:
    llm: LLMClient
    first_request: LLMRequest
    current_request: LLMRequest


def try_provider_failover(
    *,
    state: ProviderFailoverState,
    history: InMemoryRunHistory,
    run_id: str,
    profile_runtime_resolver: Callable[[str], tuple[LLMClient, object]] | None,
    stage: str,
    error_code: str,
    first_request: LLMRequest,
    current_request: LLMRequest,
    request_adapter: Callable[[LLMRequest, LLMClient, str | None], LLMRequest],
) -> ProviderFailoverResult | None:
    if profile_runtime_resolver is None:
        return None
    if not should_failover(error_code, stage):
        return None
    while True:
        fallback_name = next_fallback_profile(
            state.active_profile_name,
            state.failover_candidates,
            state.attempted_profiles,
        )
        if fallback_name is None:
            return None
        try:
            fallback_llm, fallback_profile = profile_runtime_resolver(fallback_name)
        except ValueError as exc:
            state.attempted_profiles.append(fallback_name)
            history.record_failover_skipped_profile(
                run_id,
                profile_name=fallback_name,
                reason=str(exc),
            )
            continue
        state.active_profile_name = fallback_name
        state.active_tokenizer_family = getattr(fallback_profile, "tokenizer_family", None)
        state.register_candidates(fallback_profile)
        state.attempted_profiles.append(fallback_name)
        state.attempted_providers.append(getattr(fallback_llm, "provider_name", "unknown"))
        state.failover_trigger = error_code
        state.failover_stage = stage
        rebound_first_request = request_adapter(
            first_request,
            fallback_llm,
            state.active_tokenizer_family,
        )
        rebound_current_request = request_adapter(
            current_request,
            fallback_llm,
            state.active_tokenizer_family,
        )
        set_history_failover_state(
            history,
            run_id=run_id,
            state=state,
            final_provider_ref=getattr(fallback_llm, "provider_name", None),
        )
        return ProviderFailoverResult(
            llm=fallback_llm,
            first_request=rebound_first_request,
            current_request=rebound_current_request,
        )
