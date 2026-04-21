import unittest
from pathlib import Path
from unittest import mock

from marten_runtime.config.models_loader import (
    ModelProfile,
    load_models_config,
    resolve_model_profile,
)
from marten_runtime.config.providers_loader import load_providers_config
from marten_runtime.runtime.llm_client import (
    DemoLLMClient,
    LLMRequest,
    OpenAIChatLLMClient,
    build_llm_client,
)
from marten_runtime.tools.registry import ToolSnapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_TOML = REPO_ROOT / "config/models.toml"
PROVIDERS_TOML = REPO_ROOT / "config/providers.toml"


class ModelSmokeTests(unittest.TestCase):
    def test_demo_llm_client_does_not_route_tools_from_message_keywords(self) -> None:
        client = DemoLLMClient(
            provider_name="demo", model_name="demo-local", profile_name="demo"
        )
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="search release notes and tell me the time",
            agent_id="main",
            app_id="main_agent",
            available_tools=["mcp", "time"],
            capability_catalog_text="Capability catalog:\n- mcp: Inspect MCP servers progressively.",
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["mcp", "time"]
            ),
        )

        reply = client.complete(request)

        self.assertIsNone(reply.tool_name)
        self.assertEqual(reply.final_text, "search release notes and tell me the time")

    def test_models_loader_falls_back_to_example_when_models_toml_missing(self) -> None:
        with mock.patch(
            "marten_runtime.config.models_loader.resolve_config_path"
        ) as resolve_mock:
            repo_root = Path(__file__).resolve().parents[1]
            example = repo_root / "config/models.example.toml"
            resolve_mock.return_value = example

            config = load_models_config(str(repo_root / "config/models.toml"))

        self.assertEqual(config.default_profile, "openai_gpt5")
        self.assertEqual(
            sorted(config.profiles.keys()),
            ["kimi_k2", "minimax_m25", "openai_gpt5"],
        )
        self.assertEqual(config.profiles["openai_gpt5"].model, "gpt-5.4")
        self.assertEqual(config.profiles["minimax_m25"].provider_ref, "minimax")

    def test_models_loader_reads_default_profile(self) -> None:
        config = load_models_config(str(MODELS_TOML))
        profile_name, profile = resolve_model_profile(config)

        self.assertEqual(profile_name, "openai_gpt5")
        self.assertEqual(profile.provider_ref, "openai")
        self.assertEqual(profile.model, "gpt-5.4")
        self.assertEqual(profile.fallback_profiles, ["kimi_k2", "minimax_m25"])

    def test_models_loader_accepts_optional_context_window_metadata(self) -> None:
        profile = ModelProfile(
            provider_ref="openai",
            model="gpt-4.1",
            context_window_tokens=256000,
            reserve_output_tokens=12000,
            compact_trigger_ratio=0.75,
            tokenizer_family="openai_o200k",
            supports_provider_usage=True,
        )

        self.assertEqual(profile.context_window_tokens, 256000)
        self.assertEqual(profile.reserve_output_tokens, 12000)
        self.assertEqual(profile.compact_trigger_ratio, 0.75)
        self.assertEqual(profile.tokenizer_family, "openai_o200k")
        self.assertTrue(profile.supports_provider_usage)
        self.assertEqual(profile.fallback_profiles, [])

    def test_build_llm_client_fails_closed_without_api_key(self) -> None:
        config = load_models_config(str(MODELS_TOML))
        providers = load_providers_config(str(PROVIDERS_TOML))
        profile_name, profile = resolve_model_profile(config)

        with self.assertRaisesRegex(ValueError, "missing_llm_api_key:OPENAI_API_KEY"):
            build_llm_client(
                profile_name=profile_name,
                profile=profile,
                providers_config=providers,
                env={},
            )

    def test_build_llm_client_allows_openai_api_base_env_override(self) -> None:
        profile = ModelProfile(
            provider_ref="openai",
            model="gpt-4.1",
        )
        providers = load_providers_config(str(PROVIDERS_TOML))

        client = build_llm_client(
            profile_name="openai_gpt5",
            profile=profile,
            providers_config=providers,
            env={
                "OPENAI_API_KEY": "secret",
                "OPENAI_API_BASE": "https://openai-proxy.example/v1",
            },
        )

        self.assertIsInstance(client, OpenAIChatLLMClient)
        assert isinstance(client, OpenAIChatLLMClient)
        self.assertEqual(client.base_url, "https://openai-proxy.example/v1")


if __name__ == "__main__":
    unittest.main()
