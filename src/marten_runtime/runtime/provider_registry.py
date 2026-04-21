from marten_runtime.config.models_loader import ModelsConfig
from marten_runtime.config.providers_loader import ProviderConfig, ProvidersConfig


def resolve_provider_ref(
    *,
    provider_ref: str,
    providers_config: ProvidersConfig,
) -> ProviderConfig:
    provider = providers_config.providers.get(provider_ref)
    if provider is None:
        raise ValueError(f"unknown_provider_ref:{provider_ref}")
    return provider


def resolve_provider(
    *,
    profile_name: str,
    models_config: ModelsConfig,
    providers_config: ProvidersConfig,
) -> ProviderConfig:
    profile = models_config.profiles[profile_name]
    return resolve_provider_ref(
        provider_ref=profile.provider_ref,
        providers_config=providers_config,
    )


def resolve_fallback_profiles(
    *,
    profile_name: str,
    models_config: ModelsConfig,
    providers_config: ProvidersConfig,
) -> list[tuple[str, ProviderConfig]]:
    profile = models_config.profiles[profile_name]
    seen: set[str] = set()
    resolved: list[tuple[str, ProviderConfig]] = []
    for fallback_name in profile.fallback_profiles:
        if fallback_name in seen:
            raise ValueError(f"duplicate_fallback_profile:{fallback_name}")
        seen.add(fallback_name)
        fallback = models_config.profiles.get(fallback_name)
        if fallback is None:
            raise ValueError(f"unknown_fallback_profile:{fallback_name}")
        provider = resolve_provider_ref(
            provider_ref=fallback.provider_ref,
            providers_config=providers_config,
        )
        resolved.append((fallback_name, provider))
    return resolved
