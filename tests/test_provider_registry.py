import tempfile
import textwrap
import unittest
from pathlib import Path

from marten_runtime.config.models_loader import load_models_config
from marten_runtime.config.providers_loader import load_providers_config
from marten_runtime.runtime.provider_registry import (
    resolve_fallback_profiles,
    resolve_provider,
    resolve_provider_ref,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class ProviderRegistryTests(unittest.TestCase):
    def test_resolve_provider_returns_primary_provider_metadata(self) -> None:
        models = load_models_config(str(REPO_ROOT / "config/models.toml"))
        providers = load_providers_config(str(REPO_ROOT / "config/providers.toml"))

        provider = resolve_provider(
            profile_name="openai_gpt5",
            models_config=models,
            providers_config=providers,
        )

        self.assertEqual(provider.adapter, "openai_compat")
        self.assertEqual(provider.base_url, "https://api.openai.com/v1")

    def test_resolve_fallback_profiles_preserves_declared_order(self) -> None:
        models = load_models_config(str(REPO_ROOT / "config/models.toml"))
        providers = load_providers_config(str(REPO_ROOT / "config/providers.toml"))

        fallbacks = resolve_fallback_profiles(
            profile_name="openai_gpt5",
            models_config=models,
            providers_config=providers,
        )

        self.assertEqual([item[0] for item in fallbacks], ["kimi_k2", "minimax_m25"])
        self.assertEqual([item[1].base_url for item in fallbacks], [
            "https://api.moonshot.cn/v1",
            "https://api.minimaxi.com/v1",
        ])

    def test_unknown_provider_reference_fails(self) -> None:
        models = self._load_models_from_text(
            """
            default_profile = "broken"

            [profiles.broken]
            provider_ref = "missing"
            model = "gpt-5.4"
            """
        )
        providers = load_providers_config(str(REPO_ROOT / "config/providers.toml"))

        with self.assertRaisesRegex(ValueError, "unknown_provider_ref:missing"):
            resolve_provider(
                profile_name="broken",
                models_config=models,
                providers_config=providers,
            )

    def test_resolve_provider_ref_returns_provider_metadata(self) -> None:
        providers = load_providers_config(str(REPO_ROOT / "config/providers.toml"))

        provider = resolve_provider_ref(
            provider_ref="openai",
            providers_config=providers,
        )

        self.assertEqual(provider.adapter, "openai_compat")
        self.assertEqual(provider.api_key_env, "OPENAI_API_KEY")

    def test_unknown_fallback_profile_fails(self) -> None:
        models = self._load_models_from_text(
            """
            default_profile = "openai_gpt5"

            [profiles.openai_gpt5]
            provider_ref = "openai"
            model = "gpt-5.4"
            fallback_profiles = ["missing_profile"]
            """
        )
        providers = load_providers_config(str(REPO_ROOT / "config/providers.toml"))

        with self.assertRaisesRegex(ValueError, "unknown_fallback_profile:missing_profile"):
            resolve_fallback_profiles(
                profile_name="openai_gpt5",
                models_config=models,
                providers_config=providers,
            )

    def test_duplicate_fallback_entries_fail(self) -> None:
        models = self._load_models_from_text(
            """
            default_profile = "openai_gpt5"

            [profiles.openai_gpt5]
            provider_ref = "openai"
            model = "gpt-5.4"
            fallback_profiles = ["kimi_k2", "kimi_k2"]

            [profiles.kimi_k2]
            provider_ref = "kimi"
            model = "kimi-k2"
            """
        )
        providers = load_providers_config(str(REPO_ROOT / "config/providers.toml"))

        with self.assertRaisesRegex(ValueError, "duplicate_fallback_profile:kimi_k2"):
            resolve_fallback_profiles(
                profile_name="openai_gpt5",
                models_config=models,
                providers_config=providers,
            )

    def _load_models_from_text(self, config_text: str):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "models.toml"
            path.write_text(textwrap.dedent(config_text), encoding="utf-8")
            return load_models_config(str(path))


if __name__ == "__main__":
    unittest.main()
