import unittest
from pathlib import Path
from unittest import mock

from marten_runtime.config.models_loader import ModelProfile, load_models_config, resolve_model_profile
from marten_runtime.runtime.llm_client import (
    DemoLLMClient,
    LLMRequest,
    OpenAIChatLLMClient,
    _default_transport,
    build_llm_client,
)
from marten_runtime.tools.registry import ToolSnapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_TOML = REPO_ROOT / "config/models.toml"


class ModelSmokeTests(unittest.TestCase):
    def test_demo_llm_client_does_not_route_tools_from_message_keywords(self) -> None:
        client = DemoLLMClient(provider_name="demo", model_name="demo-local", profile_name="demo")
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="search release notes and tell me the time",
            agent_id="assistant",
            app_id="example_assistant",
            available_tools=["mcp", "time"],
            capability_catalog_text="Capability catalog:\n- mcp: Inspect MCP servers progressively.",
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1", builtin_tools=["mcp", "time"]),
        )

        reply = client.complete(request)

        self.assertIsNone(reply.tool_name)
        self.assertEqual(reply.final_text, "search release notes and tell me the time")

    def test_models_loader_falls_back_to_example_when_models_toml_missing(self) -> None:
        with mock.patch("marten_runtime.config.models_loader.resolve_config_path") as resolve_mock:
            repo_root = Path(__file__).resolve().parents[1]
            example = repo_root / "config/models.example.toml"
            resolve_mock.return_value = example

            config = load_models_config(str(repo_root / "config/models.toml"))

        self.assertEqual(config.default_profile, "minimax_coding")
        self.assertIn("minimax_coding", config.profiles)
        self.assertEqual(
            config.profiles["minimax_coding"].base_url,
            "https://api.minimaxi.com/v1",
        )

    def test_models_loader_reads_default_profile(self) -> None:
        config = load_models_config(str(MODELS_TOML))
        profile_name, profile = resolve_model_profile(config)

        self.assertEqual(profile_name, "minimax_coding")
        self.assertEqual(profile.provider, "openai")
        self.assertEqual(profile.model, "MiniMax-M2.5")
        self.assertEqual(profile.base_url, "https://api.minimaxi.com/v1")

    def test_build_llm_client_fails_closed_without_api_key(self) -> None:
        config = load_models_config(str(MODELS_TOML))
        profile_name, profile = resolve_model_profile(config)

        with self.assertRaisesRegex(ValueError, "missing_llm_api_key:MINIMAX_API_KEY"):
            build_llm_client(profile_name=profile_name, profile=profile, env={})

    def test_build_llm_client_uses_custom_env_and_base_url_for_openai_compatible_profile(self) -> None:
        profile = ModelProfile(
            provider="openai",
            model="MiniMax-M2.5",
            base_url="https://api.minimaxi.com/v1",
            api_key_env="MINIMAX_API_KEY",
        )

        client = build_llm_client(
            profile_name="minimax_coding",
            profile=profile,
            env={"MINIMAX_API_KEY": "secret"},
        )

        self.assertIsInstance(client, OpenAIChatLLMClient)
        assert isinstance(client, OpenAIChatLLMClient)
        self.assertEqual(client.api_key, "secret")
        self.assertEqual(client.base_url, "https://api.minimaxi.com/v1")
        self.assertEqual(client.model_name, "MiniMax-M2.5")

    def test_build_llm_client_allows_openai_api_base_env_override(self) -> None:
        profile = ModelProfile(
            provider="openai",
            model="gpt-4.1",
        )

        client = build_llm_client(
            profile_name="default",
            profile=profile,
            env={
                "OPENAI_API_KEY": "secret",
                "OPENAI_API_BASE": "https://openai-proxy.example/v1",
            },
        )

        self.assertIsInstance(client, OpenAIChatLLMClient)
        assert isinstance(client, OpenAIChatLLMClient)
        self.assertEqual(client.base_url, "https://openai-proxy.example/v1")

    def test_build_llm_client_allows_minimax_api_base_env_override(self) -> None:
        profile = ModelProfile(
            provider="openai",
            model="MiniMax-M2.5",
            base_url="https://api.minimaxi.com/v1",
            api_key_env="MINIMAX_API_KEY",
        )

        client = build_llm_client(
            profile_name="minimax_coding",
            profile=profile,
            env={
                "MINIMAX_API_KEY": "secret",
                "MINIMAX_API_BASE": "https://api.minimax-proxy.example/v1",
            },
        )

        self.assertIsInstance(client, OpenAIChatLLMClient)
        assert isinstance(client, OpenAIChatLLMClient)
        self.assertEqual(client.base_url, "https://api.minimax-proxy.example/v1")

    def test_openai_client_maps_tool_calls_and_tool_results(self) -> None:
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "time",
                                        "arguments": "{\"timezone\": \"UTC\"}",
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "time=ok"}}]},
        ]
        captured: list[dict] = []

        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers
            captured.append(body)
            return responses.pop(0)

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=fake_transport,
        )
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="what time is it?",
            agent_id="assistant",
            app_id="example_assistant",
            available_tools=["time"],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1", builtin_tools=["time"]),
        )

        first = client.complete(request)
        second = client.complete(
            request.model_copy(
                update={
                    "tool_result": {"iso_time": "2026-03-27T00:00:00Z"},
                    "requested_tool_name": "time",
                    "requested_tool_payload": {"timezone": "UTC"},
                }
            )
        )

        self.assertEqual(first.tool_name, "time")
        self.assertEqual(first.tool_payload, {"timezone": "UTC"})
        self.assertEqual(second.final_text, "time=ok")
        self.assertEqual(captured[0]["tools"][0]["function"]["name"], "time")
        self.assertTrue(any(item["role"] == "tool" for item in captured[1]["messages"]))

    def test_openai_client_exposes_automation_action_schema_to_model(self) -> None:
        captured: list[dict] = []

        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers
            captured.append(body)
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="MiniMax-M2.5",
            profile_name="minimax_coding",
            transport=fake_transport,
        )
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="当前有哪些定时任务",
            agent_id="assistant",
            app_id="example_assistant",
            available_tools=["automation"],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1", builtin_tools=["automation"]),
        )

        client.complete(request)

        schema = captured[0]["tools"][0]["function"]["parameters"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["action"]["type"], "string")
        self.assertIn("list", schema["properties"]["action"]["enum"])
        self.assertIn("required", schema)
        self.assertEqual(schema["required"], ["action"])

    def test_openai_client_omits_skill_heads_and_capability_catalog_on_tool_followup(self) -> None:
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "time",
                                        "arguments": "{\"timezone\": \"UTC\"}",
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "time=ok"}}]},
        ]
        captured: list[dict] = []

        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers
            captured.append(body)
            return responses.pop(0)

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=fake_transport,
        )
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="what time is it?",
            agent_id="assistant",
            app_id="example_assistant",
            skill_heads_text="Visible skills:\n- example_time",
            capability_catalog_text="Capability catalog:\n- time",
            available_tools=["time"],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1", builtin_tools=["time"]),
        )

        client.complete(request)
        client.complete(
            request.model_copy(
                update={
                    "tool_result": {"iso_time": "2026-03-27T00:00:00Z"},
                    "requested_tool_name": "time",
                    "requested_tool_payload": {"timezone": "UTC"},
                }
            )
        )

        followup_messages = captured[1]["messages"]
        joined = "\n".join(str(item.get("content", "")) for item in followup_messages)
        self.assertNotIn("Visible skills", joined)
        self.assertNotIn("Capability catalog", joined)

    def test_openai_client_keeps_capability_catalog_on_first_turn_with_tools(self) -> None:
        captured: list[dict] = []

        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers
            captured.append(body)
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="MiniMax-M2.5",
            profile_name="minimax_coding",
            transport=fake_transport,
        )
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="帮我看下今天 github 热门仓库",
            agent_id="assistant",
            app_id="example_assistant",
            capability_catalog_text="Capability catalog:\n- mcp: Use MCP progressively.\n- time: Check live time first.",
            available_tools=["mcp", "time"],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1", builtin_tools=["mcp", "time"]),
        )

        client.complete(request)

        first_turn_messages = captured[0]["messages"]
        joined = "\n".join(str(item.get("content", "")) for item in first_turn_messages)
        self.assertIn("Capability catalog", joined)
        self.assertIn("Use MCP progressively", joined)
        self.assertIn("Check live time first", joined)

    def test_default_transport_raises_runtime_error_on_http_error(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=mock.Mock(read=lambda: b"{}", code=500)):
            with self.assertRaises(Exception):
                _default_transport("https://example.com", {}, {})


if __name__ == "__main__":
    unittest.main()
