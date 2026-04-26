import tomllib

from pydantic import BaseModel, Field, field_validator

from marten_runtime.config.file_resolver import resolve_config_path

SUPPORTED_ADAPTERS = {"openai_compat"}


class ProviderConfig(BaseModel):
    adapter: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    api_key_env: str = Field(min_length=1)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    header_env_map: dict[str, str] = Field(default_factory=dict)
    supports_responses_api: bool
    supports_responses_streaming: bool
    supports_chat_completions: bool

    @field_validator("adapter", "base_url", "api_key_env")
    @classmethod
    def _require_non_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class ProvidersConfig(BaseModel):
    providers: dict[str, ProviderConfig]


def load_providers_config(path: str) -> ProvidersConfig:
    resolved = resolve_config_path(path)
    if resolved is None:
        raise ValueError(f"missing_provider_config:{path}")
    data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    providers: dict[str, ProviderConfig] = {}
    for provider_ref, payload in data.get("providers", {}).items():
        try:
            provider = ProviderConfig(**payload)
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        if provider.adapter not in SUPPORTED_ADAPTERS:
            raise ValueError(f"unsupported_llm_adapter:{provider.adapter}")
        providers[provider_ref] = provider
    return ProvidersConfig(providers=providers)
