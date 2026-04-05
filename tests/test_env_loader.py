import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from marten_runtime.config.env_loader import load_env_file
from marten_runtime.config.models_loader import ModelProfile
from marten_runtime.runtime.llm_client import OpenAIChatLLMClient, build_llm_client


class EnvLoaderTests(unittest.TestCase):
    def test_load_env_file_sets_missing_values_without_overriding_existing_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("MINIMAX_API_KEY=file-secret\nOPENAI_API_KEY=file-openai\n", encoding="utf-8")

            with patch.dict(os.environ, {"OPENAI_API_KEY": "existing-openai"}, clear=True):
                loaded = load_env_file(env_path)

                self.assertTrue(loaded.loaded)
                self.assertEqual(loaded.path, str(env_path))
                self.assertEqual(os.environ["OPENAI_API_KEY"], "existing-openai")
                self.assertEqual(os.environ["MINIMAX_API_KEY"], "file-secret")

    def test_loaded_env_values_are_visible_to_model_client_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("MINIMAX_API_KEY=file-secret\n", encoding="utf-8")
            profile = ModelProfile(
                provider="openai",
                model="MiniMax-M2.5",
                base_url="https://api.minimaxi.com/v1",
                api_key_env="MINIMAX_API_KEY",
            )

            with patch.dict(os.environ, {}, clear=True):
                load_env_file(env_path)
                client = build_llm_client(profile_name="minimax_coding", profile=profile, env=os.environ)

                self.assertIsInstance(client, OpenAIChatLLMClient)
                assert isinstance(client, OpenAIChatLLMClient)
                self.assertEqual(client.api_key, "file-secret")


if __name__ == "__main__":
    unittest.main()
