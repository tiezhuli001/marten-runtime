from __future__ import annotations

ALLOWED_FAILOVER_ERRORS = {
    "PROVIDER_UPSTREAM_UNAVAILABLE",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_TIMEOUT",
    "PROVIDER_TRANSPORT_ERROR",
    "PROVIDER_RESPONSE_INVALID",
    "EMPTY_FINAL_RESPONSE",
}

ALLOWED_FAILOVER_STAGES = {"llm_first", "llm_second"}


def should_failover(error_code: str, stage: str) -> bool:
    return stage in ALLOWED_FAILOVER_STAGES and error_code in ALLOWED_FAILOVER_ERRORS


def next_fallback_profile(
    current_profile: str,
    fallback_profiles: list[str],
    attempted_profiles: list[str],
) -> str | None:
    del current_profile
    attempted = set(attempted_profiles)
    for profile_name in fallback_profiles:
        if profile_name not in attempted:
            return profile_name
    return None
