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

    def test_models_loader_reads_default_profile(self) -> None:
        config = load_models_config(str(MODELS_TOML))
        profile_name, profile = resolve_model_profile(config)

        self.assertEqual(profile_name, "minimax_coding")
        self.assertEqual(profile.provider, "openai")
        self.assertEqual(profile.model, "MiniMax-M2.5")

    def test_build_llm_client_falls_back_to_demo_without_api_key(self) -> None:
        config = load_models_config(str(MODELS_TOML))
        profile_name, profile = resolve_model_profile(config)

        client = build_llm_client(profile_name=profile_name, profile=profile, env={})

        self.assertEqual(client.provider_name, "demo-fallback")
        self.assertEqual(client.model_name, "openai:MiniMax-M2.5")

    def test_build_llm_client_uses_custom_env_and_base_url_for_openai_compatible_profile(self) -> None:
        profile = ModelProfile(
            provider="openai",
            model="MiniMax-M2.5",
            base_url="https://api.minimax.io/v1",
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
        self.assertEqual(client.base_url, "https://api.minimax.io/v1")
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
            base_url="https://api.minimax.io/v1",
            api_key_env="MINIMAX_API_KEY",
        )

        client = build_llm_client(
            profile_name="minimax_coding",
            profile=profile,
            env={
                "MINIMAX_API_KEY": "secret",
                "MINIMAX_API_BASE": "https://api.minimaxi.com/v1",
            },
        )

        self.assertIsInstance(client, OpenAIChatLLMClient)
        assert isinstance(client, OpenAIChatLLMClient)
        self.assertEqual(client.base_url, "https://api.minimaxi.com/v1")

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
            system_prompt="system",
            skill_heads_text="skills",
            capability_catalog_text="catalog",
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

        first_messages = captured[0]["messages"]
        second_messages = captured[1]["messages"]
        first_system = next(item["content"] for item in first_messages if item["role"] == "system")
        second_system = next(item["content"] for item in second_messages if item["role"] == "system")
        self.assertIn("skills", first_system)
        self.assertNotIn("catalog", first_system)
        self.assertNotIn("skills", second_system)
        self.assertNotIn("catalog", second_system)

    def test_openai_client_omits_capability_catalog_when_tools_are_already_declared(self) -> None:
        captured: list[dict] = []

        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers
            captured.append(body)
            return {"choices": [{"message": {"content": "ok"}}]}

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
            system_prompt="system",
            skill_heads_text="skills",
            capability_catalog_text="catalog",
            available_tools=["time"],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1", builtin_tools=["time"]),
        )

        reply = client.complete(request)

        self.assertEqual(reply.final_text, "ok")
        messages = captured[0]["messages"]
        system_message = next(item["content"] for item in messages if item["role"] == "system")
        self.assertIn("skills", system_message)
        self.assertNotIn("catalog", system_message)
        self.assertEqual(captured[0]["tools"][0]["function"]["name"], "time")

    def test_openai_client_keeps_capability_catalog_when_no_function_tools_are_declared(self) -> None:
        captured: list[dict] = []

        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers
            captured.append(body)
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=fake_transport,
        )
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="hello",
            agent_id="assistant",
            app_id="example_assistant",
            capability_catalog_text="catalog",
        )

        client.complete(request)

        messages = captured[0]["messages"]
        self.assertTrue(any(item.get("content") == "catalog" for item in messages))

    def test_openai_client_accepts_empty_tool_arguments_string(self) -> None:
        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers, body
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "time",
                                        "arguments": "",
                                    }
                                }
                            ]
                        }
                    }
                ]
            }

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

        reply = client.complete(request)

        self.assertEqual(reply.tool_name, "time")
        self.assertEqual(reply.tool_payload, {})

    def test_openai_client_accepts_fenced_json_tool_arguments(self) -> None:
        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers, body
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "time",
                                        "arguments": "```json\n{\"timezone\":\"UTC\"}\n```",
                                    }
                                }
                            ]
                        }
                    }
                ]
            }

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

        reply = client.complete(request)

        self.assertEqual(reply.tool_name, "time")
        self.assertEqual(reply.tool_payload, {"timezone": "UTC"})

    def test_openai_client_strips_think_blocks_from_final_text(self) -> None:
        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers, body
            return {
                "choices": [
                    {
                        "message": {
                            "content": "<think>\ninternal reasoning\n</think>\n\nVisible answer.",
                        }
                    }
                ]
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=fake_transport,
        )
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="hello",
            agent_id="assistant",
            app_id="example_assistant",
        )

        reply = client.complete(request)

        self.assertEqual(reply.final_text, "Visible answer.")

    def test_openai_client_includes_system_prompt_in_messages(self) -> None:
        captured: list[dict] = []

        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers
            captured.append(body)
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=fake_transport,
        )
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="hello",
            agent_id="assistant",
            app_id="example_assistant",
            system_prompt="You are marten-runtime.",
        )

        reply = client.complete(request)

        self.assertEqual(reply.final_text, "ok")
        self.assertEqual(captured[0]["messages"][0]["role"], "system")
        self.assertEqual(captured[0]["messages"][0]["content"], "You are marten-runtime.")
        self.assertEqual(captured[0]["messages"][1]["role"], "user")

    def test_openai_client_collapses_multiple_system_messages_into_one(self) -> None:
        captured: list[dict] = []

        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers
            captured.append(body)
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=fake_transport,
        )
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="hello",
            agent_id="assistant",
            app_id="example_assistant",
            system_prompt="system",
            skill_heads_text="skills",
            capability_catalog_text="catalog",
            working_context_text="working",
        )

        reply = client.complete(request)

        self.assertEqual(reply.final_text, "ok")
        system_messages = [item for item in captured[0]["messages"] if item["role"] == "system"]
        self.assertEqual(len(system_messages), 1)
        self.assertEqual(system_messages[0]["content"], "system\n\nskills\n\ncatalog\n\nworking")

    def test_openai_client_retries_retryable_transport_failures(self) -> None:
        attempts = {"count": 0}

        def flaky_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers, body
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise TimeoutError("timed out")
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=flaky_transport,
        )
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="hello",
            agent_id="assistant",
            app_id="example_assistant",
        )

        reply = client.complete(request)

        self.assertEqual(reply.final_text, "ok")
        self.assertEqual(attempts["count"], 3)

    def test_default_transport_sets_user_agent_header(self) -> None:
        captured: dict[str, object] = {}

        class _FakeResponse:
            def __enter__(self) -> "_FakeResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        def fake_urlopen(req, timeout=30):
            captured["request"] = req
            captured["timeout"] = timeout
            return _FakeResponse()

        with mock.patch("marten_runtime.runtime.llm_client.urllib_request.urlopen", side_effect=fake_urlopen):
            payload = _default_transport(
                "https://example.com/v1/chat/completions",
                {"Authorization": "Bearer secret", "Content-Type": "application/json"},
                {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hello"}]},
            )

        self.assertEqual(payload["choices"][0]["message"]["content"], "ok")
        req = captured["request"]
        self.assertEqual(req.get_header("User-agent"), "marten-runtime/0.1")


if __name__ == "__main__":
    unittest.main()
