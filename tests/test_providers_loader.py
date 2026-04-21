import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from marten_runtime.config.providers_loader import load_providers_config

REPO_ROOT = Path(__file__).resolve().parents[1]


class ProvidersLoaderTests(unittest.TestCase):
    def test_providers_loader_falls_back_to_example_when_file_missing(self) -> None:
        with mock.patch(
            "marten_runtime.config.providers_loader.resolve_config_path"
        ) as resolve_mock:
            example = REPO_ROOT / "config/providers.example.toml"
            resolve_mock.return_value = example

            config = load_providers_config(str(REPO_ROOT / "config/providers.toml"))

        self.assertEqual(sorted(config.providers.keys()), ["kimi", "minimax", "openai"])
        self.assertEqual(config.providers["openai"].adapter, "openai_compat")
        self.assertTrue(config.providers["openai"].supports_responses_api)
        self.assertTrue(config.providers["openai"].supports_responses_streaming)
        self.assertTrue(config.providers["minimax"].supports_chat_completions)

    def test_missing_adapter_fails(self) -> None:
        self._assert_invalid_config(
            """
            [providers.openai]
            base_url = "https://api.openai.com/v1"
            api_key_env = "OPENAI_API_KEY"
            supports_responses_api = true
            supports_responses_streaming = true
            supports_chat_completions = true
            """,
            "adapter",
        )

    def test_missing_api_key_env_fails(self) -> None:
        self._assert_invalid_config(
            """
            [providers.openai]
            adapter = "openai_compat"
            base_url = "https://api.openai.com/v1"
            supports_responses_api = true
            supports_responses_streaming = true
            supports_chat_completions = true
            """,
            "api_key_env",
        )

    def test_missing_base_url_fails(self) -> None:
        self._assert_invalid_config(
            """
            [providers.openai]
            adapter = "openai_compat"
            api_key_env = "OPENAI_API_KEY"
            supports_responses_api = true
            supports_responses_streaming = true
            supports_chat_completions = true
            """,
            "base_url",
        )

    def test_blank_base_url_fails(self) -> None:
        self._assert_invalid_config(
            """
            [providers.openai]
            adapter = "openai_compat"
            base_url = "   "
            api_key_env = "OPENAI_API_KEY"
            supports_responses_api = true
            supports_responses_streaming = true
            supports_chat_completions = true
            """,
            "value must not be blank",
        )

    def test_blank_api_key_env_fails(self) -> None:
        self._assert_invalid_config(
            """
            [providers.openai]
            adapter = "openai_compat"
            base_url = "https://api.openai.com/v1"
            api_key_env = "   "
            supports_responses_api = true
            supports_responses_streaming = true
            supports_chat_completions = true
            """,
            "value must not be blank",
        )

    def test_missing_supports_responses_api_fails(self) -> None:
        self._assert_invalid_config(
            """
            [providers.openai]
            adapter = "openai_compat"
            base_url = "https://api.openai.com/v1"
            api_key_env = "OPENAI_API_KEY"
            supports_responses_streaming = true
            supports_chat_completions = true
            """,
            "supports_responses_api",
        )

    def test_missing_supports_responses_streaming_fails(self) -> None:
        self._assert_invalid_config(
            """
            [providers.openai]
            adapter = "openai_compat"
            base_url = "https://api.openai.com/v1"
            api_key_env = "OPENAI_API_KEY"
            supports_responses_api = true
            supports_chat_completions = true
            """,
            "supports_responses_streaming",
        )

    def test_missing_supports_chat_completions_fails(self) -> None:
        self._assert_invalid_config(
            """
            [providers.openai]
            adapter = "openai_compat"
            base_url = "https://api.openai.com/v1"
            api_key_env = "OPENAI_API_KEY"
            supports_responses_api = true
            supports_responses_streaming = true
            """,
            "supports_chat_completions",
        )

    def test_unknown_adapter_fails(self) -> None:
        self._assert_invalid_config(
            """
            [providers.openai]
            adapter = "unknown"
            base_url = "https://api.openai.com/v1"
            api_key_env = "OPENAI_API_KEY"
            supports_responses_api = true
            supports_responses_streaming = true
            supports_chat_completions = true
            """,
            "unsupported_llm_adapter:unknown",
        )

    def _assert_invalid_config(self, config_text: str, message: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "providers.toml"
            path.write_text(textwrap.dedent(config_text), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, message):
                load_providers_config(str(path))


if __name__ == "__main__":
    unittest.main()
