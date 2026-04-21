import tomllib

from pydantic import BaseModel, Field

from marten_runtime.config.file_resolver import resolve_config_path


class ModelProfile(BaseModel):
    provider_ref: str
    model: str
    fallback_profiles: list[str] = Field(default_factory=list)
    context_window_tokens: int | None = None
    reserve_output_tokens: int | None = None
    compact_trigger_ratio: float | None = None
    tokenizer_family: str | None = None
    supports_provider_usage: bool | None = None


class ModelsConfig(BaseModel):
    default_profile: str
    profiles: dict[str, ModelProfile]


def load_models_config(path: str) -> ModelsConfig:
    resolved = resolve_config_path(path)
    if resolved is None:
        data = {
            "default_profile": "openai_gpt5",
            "profiles": {
                "openai_gpt5": {
                    "provider_ref": "openai",
                    "model": "gpt-5.4",
                    "fallback_profiles": ["kimi_k2", "minimax_m25"],
                },
                "kimi_k2": {
                    "provider_ref": "kimi",
                    "model": "kimi-k2",
                },
                "minimax_m25": {
                    "provider_ref": "minimax",
                    "model": "MiniMax-M2.5",
                },
            },
        }
    else:
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    profiles = {
        name: ModelProfile(**payload)
        for name, payload in data.get("profiles", {}).items()
    }
    return ModelsConfig(default_profile=data["default_profile"], profiles=profiles)


def resolve_model_profile(config: ModelsConfig, profile_name: str | None = None) -> tuple[str, ModelProfile]:
    resolved_name = profile_name or config.default_profile
    return resolved_name, config.profiles[resolved_name]
