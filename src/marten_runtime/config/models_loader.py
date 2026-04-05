import tomllib

from pydantic import BaseModel

from marten_runtime.config.file_resolver import resolve_config_path


class ModelProfile(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None


class ModelsConfig(BaseModel):
    default_profile: str
    profiles: dict[str, ModelProfile]


def load_models_config(path: str) -> ModelsConfig:
    resolved = resolve_config_path(path)
    if resolved is None:
        data = {
            "default_profile": "minimax_coding",
            "profiles": {
                "default": {
                    "provider": "openai",
                    "model": "gpt-4.1",
                },
                "minimax_coding": {
                    "provider": "openai",
                    "model": "MiniMax-M2.5",
                    "base_url": "https://api.minimaxi.com/v1",
                    "api_key_env": "MINIMAX_API_KEY",
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
