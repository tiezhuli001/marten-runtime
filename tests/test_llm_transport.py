import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import httpx

from marten_runtime.config.providers_loader import ProviderConfig
from marten_runtime.runtime.llm_client import (
    LLMRequest,
    OpenAIChatLLMClient,
    ToolExchange,
    _default_transport,
)
from marten_runtime.runtime.capabilities import (
    get_capability_declarations,
    render_capability_catalog,
)
from marten_runtime.runtime.llm_message_support import build_openai_chat_payload
from marten_runtime.runtime.provider_retry import ProviderTransportError
from marten_runtime.tools.registry import ToolSnapshot


class OpenAIChatClientTests(unittest.TestCase):
    def _provider(
        self,
        *,
        base_url: str = "https://api.openai.com/v1",
        api_key_env: str = "OPENAI_API_KEY",
        supports_responses_api: bool = True,
        supports_responses_streaming: bool = True,
        supports_chat_completions: bool = True,
        extra_headers: dict[str, str] | None = None,
        header_env_map: dict[str, str] | None = None,
    ) -> ProviderConfig:
        return ProviderConfig(
            adapter="openai_compat",
            base_url=base_url,
            api_key_env=api_key_env,
            extra_headers=extra_headers or {},
            header_env_map=header_env_map or {},
            supports_responses_api=supports_responses_api,
            supports_responses_streaming=supports_responses_streaming,
            supports_chat_completions=supports_chat_completions,
        )

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
                                        "arguments": '{"timezone": "UTC"}',
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
            agent_id="main",
            app_id="main_agent",
            available_tools=["time"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["time"]
            ),
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

    def test_openai_client_uses_tighter_budget_for_interactive_requests(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float,
        ) -> dict:
            del url, headers, body
            captured.append({"timeout_seconds": timeout_seconds})
            raise TimeoutError("timed out")

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="MiniMax-M2.5",
            profile_name="minimax_coding",
            transport=fake_transport,
        )

        with self.assertRaises(ProviderTransportError):
            client.complete(
                LLMRequest(
                    session_id="sess_1",
                    trace_id="trace_1",
                    message="hello",
                    agent_id="main",
                    app_id="main_agent",
                    request_kind="interactive",
                )
            )

        self.assertEqual(len(captured), 2)
        self.assertTrue(all(item["timeout_seconds"] == 20 for item in captured))
        assert client.last_call_diagnostics is not None
        self.assertEqual(client.last_call_diagnostics.request_kind, "interactive")
        self.assertEqual(client.last_call_diagnostics.timeout_seconds, 20)
        self.assertEqual(client.last_call_diagnostics.max_attempts, 2)
        self.assertEqual(len(client.last_call_diagnostics.attempts), 2)
        self.assertEqual(
            client.last_call_diagnostics.final_error_code, "PROVIDER_TIMEOUT"
        )

    def test_openai_client_treats_null_content_as_empty_final_text(self) -> None:
        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers, body
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": None,
                        }
                    }
                ]
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-5.4",
            profile_name="default",
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_1",
                trace_id="trace_1",
                message="hello",
                agent_id="main",
                app_id="main_agent",
                request_kind="interactive",
            )
        )

        self.assertIsNone(reply.tool_name)
        self.assertEqual(reply.final_text, "")

    def test_openai_5_series_uses_responses_api_for_text_reply(self) -> None:
        calls: list[tuple[str, dict]] = []

        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float = 30,
            *,
            stop_event=None,
            deadline_monotonic=None,
        ) -> dict:
            del headers, timeout_seconds, stop_event, deadline_monotonic
            calls.append((url, body))
            if url.endswith("/responses"):
                return {
                    "status": "completed",
                    "output_text": "你好",
                    "output": [],
                    "usage": {"input_tokens": 11, "output_tokens": 3, "total_tokens": 14},
                }
            return {
                "choices": [{"message": {"content": "should-not-be-used"}}]
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-5.4",
            profile_name="default",
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_1",
                trace_id="trace_1",
                message="hello",
                agent_id="main",
                app_id="main_agent",
                request_kind="interactive",
            )
        )

        self.assertEqual(reply.final_text, "你好")
        self.assertEqual([item[0] for item in calls], ["https://api.openai.com/v1/responses"])
        self.assertTrue(calls[0][1]["stream"])
        self.assertEqual(calls[0][1]["input"][0]["type"], "message")
        self.assertEqual(calls[0][1]["input"][0]["role"], "user")
        self.assertEqual(calls[0][1]["input"][0]["content"][0]["type"], "input_text")

    def test_openai_5_series_raises_invalid_response_when_completed_payload_has_no_visible_output(
        self,
    ) -> None:
        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float = 30,
            *,
            stop_event=None,
            deadline_monotonic=None,
        ) -> dict:
            del headers, body, timeout_seconds, stop_event, deadline_monotonic
            self.assertTrue(url.endswith("/responses"))
            return {
                "status": "completed",
                "output": [],
                "output_text": None,
                "error": None,
                "usage": {"input_tokens": 11, "output_tokens": 3, "total_tokens": 14},
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-5.4",
            profile_name="default",
            transport=fake_transport,
        )

        with self.assertRaisesRegex(RuntimeError, "provider_response_invalid"):
            client.complete(
                LLMRequest(
                    session_id="sess_1",
                    trace_id="trace_1",
                    message="hello",
                    agent_id="main",
                    app_id="main_agent",
                    request_kind="interactive",
                )
            )

    def test_openai_5_series_extracts_text_from_choices_fallback_shape(self) -> None:
        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float = 30,
            *,
            stop_event=None,
            deadline_monotonic=None,
        ) -> dict:
            del headers, body, timeout_seconds, stop_event, deadline_monotonic
            self.assertTrue(url.endswith("/responses"))
            return {
                "status": "completed",
                "output": [],
                "choices": [{"message": {"content": "你好，fallback"}}],
                "usage": {"input_tokens": 11, "output_tokens": 3, "total_tokens": 14},
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-5.4",
            profile_name="default",
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_1",
                trace_id="trace_1",
                message="hello",
                agent_id="main",
                app_id="main_agent",
                request_kind="interactive",
            )
        )

        self.assertEqual(reply.final_text, "你好，fallback")

    def test_openai_5_series_uses_responses_api_for_function_call(self) -> None:
        calls: list[tuple[str, dict]] = []

        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float = 30,
            *,
            stop_event=None,
            deadline_monotonic=None,
        ) -> dict:
            del headers, timeout_seconds, stop_event, deadline_monotonic
            calls.append((url, body))
            if url.endswith("/responses"):
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "name": "time",
                            "arguments": '{"timezone":"UTC"}',
                        }
                    ],
                    "usage": {"input_tokens": 11, "output_tokens": 3, "total_tokens": 14},
                }
            return {
                "choices": [{"message": {"content": "should-not-be-used"}}]
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-5.2",
            profile_name="default",
            transport=fake_transport,
        )
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="现在几点了",
            agent_id="main",
            app_id="main_agent",
            request_kind="interactive",
            available_tools=["time"],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1", builtin_tools=["time"]),
        )

        reply = client.complete(request)

        self.assertEqual(reply.tool_name, "time")
        self.assertEqual(reply.tool_payload, {"timezone": "UTC"})
        self.assertEqual([item[0] for item in calls], ["https://api.openai.com/v1/responses"])
        self.assertEqual(calls[0][1]["tools"][0]["name"], "time")

    def test_openai_5_series_encodes_tool_followup_as_structured_responses_items(self) -> None:
        captured: list[dict] = []

        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float = 30,
            *,
            stop_event=None,
            deadline_monotonic=None,
        ) -> dict:
            del url, headers, timeout_seconds, stop_event, deadline_monotonic
            captured.append(body)
            return {
                "status": "completed",
                "output_text": "done",
                "output": [],
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-5.4",
            profile_name="default",
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_1",
                trace_id="trace_1",
                message="继续",
                agent_id="main",
                app_id="main_agent",
                request_kind="interactive",
                tool_result={"iso_time": "2026-04-20T12:00:00Z"},
                requested_tool_name="time",
                requested_tool_payload={"timezone": "UTC"},
            )
        )

        self.assertEqual(reply.final_text, "done")
        input_items = captured[0]["input"]
        self.assertEqual(input_items[-2]["type"], "function_call")
        self.assertEqual(input_items[-2]["name"], "time")
        self.assertEqual(input_items[-1]["type"], "function_call_output")
        self.assertEqual(input_items[-1]["call_id"], "call_1")
        self.assertEqual(
            input_items[-1]["output"],
            '{"iso_time": "2026-04-20T12:00:00Z"}',
        )

    def test_openai_5_series_raises_invalid_response_for_multiple_function_calls(self) -> None:
        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float = 30,
            *,
            stop_event=None,
            deadline_monotonic=None,
        ) -> dict:
            del url, headers, body, timeout_seconds, stop_event, deadline_monotonic
            return {
                "status": "completed",
                "output": [
                    {"type": "function_call", "name": "time", "arguments": "{}"},
                    {"type": "function_call", "name": "date", "arguments": "{}"},
                ],
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-5.4",
            profile_name="default",
            transport=fake_transport,
        )

        with self.assertRaisesRegex(RuntimeError, "multiple_function_calls_not_supported"):
            client.complete(
                LLMRequest(
                    session_id="sess_1",
                    trace_id="trace_1",
                    message="hello",
                    agent_id="main",
                    app_id="main_agent",
                    request_kind="interactive",
                )
            )

    def test_openai_5_series_maps_failed_responses_status_to_upstream_unavailable(self) -> None:
        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float = 30,
            *,
            stop_event=None,
            deadline_monotonic=None,
        ) -> dict:
            del url, headers, body, timeout_seconds, stop_event, deadline_monotonic
            return {
                "status": "failed",
                "incomplete_details": {"reason": "upstream_error"},
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-5.4",
            profile_name="default",
            transport=fake_transport,
        )

        with self.assertRaises(ProviderTransportError) as ctx:
            client.complete(
                LLMRequest(
                    session_id="sess_1",
                    trace_id="trace_1",
                    message="hello",
                    agent_id="main",
                    app_id="main_agent",
                    request_kind="interactive",
                )
            )

        self.assertEqual(ctx.exception.error_code, "PROVIDER_UPSTREAM_UNAVAILABLE")

    def test_openai_5_series_omits_stream_flag_when_provider_disables_responses_streaming(
        self,
    ) -> None:
        captured: list[dict] = []

        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float = 30,
            *,
            stop_event=None,
            deadline_monotonic=None,
        ) -> dict:
            del url, headers, timeout_seconds, stop_event, deadline_monotonic
            captured.append(body)
            return {
                "status": "completed",
                "output_text": "ok",
                "output": [],
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-5.4",
            profile_name="default",
            provider=self._provider(supports_responses_streaming=False),
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_1",
                trace_id="trace_1",
                message="hello",
                agent_id="main",
                app_id="main_agent",
                request_kind="interactive",
            )
        )

        self.assertEqual(reply.final_text, "ok")
        self.assertNotIn("stream", captured[0])

    def test_openai_4_series_keeps_chat_completions_path(self) -> None:
        calls: list[str] = []

        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float = 30,
            *,
            stop_event=None,
            deadline_monotonic=None,
        ) -> dict:
            del headers, body, timeout_seconds, stop_event, deadline_monotonic
            calls.append(url)
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": None,
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_1",
                trace_id="trace_1",
                message="hello",
                agent_id="main",
                app_id="main_agent",
                request_kind="interactive",
            )
        )

        self.assertEqual(reply.final_text, "")
        self.assertEqual(calls, ["https://api.openai.com/v1/chat/completions"])

    def test_openai_client_injects_provider_extra_headers(self) -> None:
        captured: list[dict[str, dict[str, str]]] = []

        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, body
            captured.append({"headers": headers})
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="openai_gpt5",
            provider_name="openai",
            provider=self._provider(
                extra_headers={"X-Fixed": "fixed"},
                header_env_map={"X-Provider-Token": "PROVIDER_TOKEN"},
            ),
            env={"PROVIDER_TOKEN": "dynamic-token"},
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_1",
                trace_id="trace_1",
                message="hello",
                agent_id="main",
                app_id="main_agent",
            )
        )

        self.assertEqual(reply.final_text, "ok")
        self.assertEqual(captured[0]["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(captured[0]["headers"]["X-Fixed"], "fixed")
        self.assertEqual(captured[0]["headers"]["X-Provider-Token"], "dynamic-token")

    def test_openai_5_series_requires_provider_responses_support(self) -> None:
        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-5.4",
            profile_name="minimax_m25",
            provider_name="minimax",
            provider=self._provider(
                base_url="https://api.minimaxi.com/v1",
                api_key_env="MINIMAX_API_KEY",
                supports_responses_api=False,
            ),
        )

        with self.assertRaisesRegex(
            ValueError, "provider_missing_responses_api_support:minimax"
        ):
            client.complete(
                LLMRequest(
                    session_id="sess_1",
                    trace_id="trace_1",
                    message="hello",
                    agent_id="main",
                    app_id="main_agent",
                )
            )

    def test_chat_path_requires_provider_chat_support(self) -> None:
        client = OpenAIChatLLMClient(
            api_key="secret",
            model="kimi-k2",
            profile_name="kimi_k2",
            provider_name="kimi",
            provider=self._provider(
                base_url="https://api.moonshot.cn/v1",
                api_key_env="KIMI_API_KEY",
                supports_chat_completions=False,
            ),
        )

        with self.assertRaisesRegex(
            ValueError, "provider_missing_chat_completions_support:kimi"
        ):
            client.complete(
                LLMRequest(
                    session_id="sess_1",
                    trace_id="trace_1",
                    message="hello",
                    agent_id="main",
                    app_id="main_agent",
                )
            )

    def test_openai_client_keeps_wider_budget_for_automation_requests(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float,
        ) -> dict:
            del url, headers, body
            captured.append({"timeout_seconds": timeout_seconds})
            raise TimeoutError("timed out")

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="MiniMax-M2.5",
            profile_name="minimax_coding",
            transport=fake_transport,
        )

        with self.assertRaises(ProviderTransportError):
            client.complete(
                LLMRequest(
                    session_id="sess_1",
                    trace_id="trace_1",
                    message="hello",
                    agent_id="main",
                    app_id="main_agent",
                    request_kind="automation",
                )
            )

        self.assertEqual(len(captured), 3)
        self.assertTrue(all(item["timeout_seconds"] == 30 for item in captured))
        assert client.last_call_diagnostics is not None
        self.assertEqual(client.last_call_diagnostics.request_kind, "automation")
        self.assertEqual(client.last_call_diagnostics.timeout_seconds, 30)
        self.assertEqual(client.last_call_diagnostics.max_attempts, 3)

    def test_openai_client_tool_followup_keeps_tool_history_messages_and_adds_summary_only_as_system_context(
        self,
    ) -> None:
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
            session_id="sess_summary",
            trace_id="trace_summary",
            message="继续",
            agent_id="main",
            app_id="main_agent",
            tool_outcome_summary_text="Recent tool outcome summaries:\n- runtime.context_status: 峰值来自工具结果注入后。",
            tool_result={"iso_time": "2026-03-27T00:00:00Z"},
            requested_tool_name="time",
            requested_tool_payload={"timezone": "UTC"},
            available_tools=["time"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["time"]
            ),
        )

        client.complete(request)

        messages = captured[0]["messages"]
        self.assertTrue(
            any(
                item.get("role") == "system"
                and "Recent tool outcome summaries" in str(item.get("content", ""))
                for item in messages
            )
        )
        self.assertTrue(any(item.get("role") == "tool" for item in messages))

    def test_build_openai_chat_payload_omits_capability_catalog_for_explicit_runtime_query(self) -> None:
        request = LLMRequest(
            session_id="sess_runtime_query",
            trace_id="trace_runtime_query",
            message="当前会话记录的上下文多大",
            agent_id="main",
            app_id="main_agent",
            available_tools=["runtime", "session", "time"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_runtime_query",
                builtin_tools=["runtime", "session", "time"],
                tool_metadata={
                    "runtime": {"description": "runtime tool"},
                    "session": {"description": "session tool"},
                    "time": {"description": "time tool"},
                },
            ),
            capability_catalog_text="Capability catalog:\n- runtime\n- session\n- time",
        )

        payload = build_openai_chat_payload("gpt-4.1", request)

        system_text = "\n".join(
            str(item.get("content", ""))
            for item in payload["messages"]
            if item.get("role") == "system"
        )
        self.assertNotIn("Capability catalog:", system_text)
        self.assertEqual(
            [item["function"]["name"] for item in payload["tools"]],
            ["session", "runtime", "time"],
        )

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
            agent_id="main",
            app_id="main_agent",
            available_tools=["automation"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["automation"]
            ),
        )

        client.complete(request)

        schema = captured[0]["tools"][0]["function"]["parameters"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["action"]["type"], "string")
        self.assertIn("list", schema["properties"]["action"]["enum"])
        self.assertIn("required", schema)
        self.assertEqual(schema["required"], ["action"])

    def test_openai_client_omits_skill_heads_and_capability_catalog_on_tool_followup(
        self,
    ) -> None:
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "time",
                                        "arguments": '{"timezone": "UTC"}',
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
            agent_id="main",
            app_id="main_agent",
            skill_heads_text="Visible skills:\n- example_time",
            capability_catalog_text="Capability catalog:\n- time",
            available_tools=["time"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["time"]
            ),
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

    def test_openai_client_adds_runtime_specific_instruction_on_runtime_tool_followup(
        self,
    ) -> None:
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "runtime",
                                        "arguments": '{"action": "context_status"}',
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "ok"}}]},
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
            message="当前上下文窗口多大？",
            agent_id="main",
            app_id="main_agent",
            available_tools=["runtime"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1",
                builtin_tools=["runtime"],
                tool_metadata={"runtime": {"description": "runtime"}},
            ),
        )

        client.complete(request)
        client.complete(
            request.model_copy(
                update={
                    "tool_result": {
                        "action": "context_status",
                        "summary": "当前估算占用 100/184000 tokens（0%）。",
                    },
                    "requested_tool_name": "runtime",
                    "requested_tool_payload": {"action": "context_status"},
                }
            )
        )

        followup_messages = captured[1]["messages"]
        joined = "\n".join(str(item.get("content", "")) for item in followup_messages)
        self.assertIn("仅根据刚刚返回的 runtime 工具结果", joined)
        self.assertIn("不要重述无关的旧任务结果", joined)

    def test_openai_client_adds_combined_summary_instruction_on_non_runtime_tool_followup(
        self,
    ) -> None:
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "mcp",
                                        "arguments": '{"action": "call", "server_id": "github", "tool_name": "search_repositories"}',
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "ok"}}]},
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
            message="看下 easy-agent",
            agent_id="main",
            app_id="main_agent",
            available_tools=["mcp"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1",
                builtin_tools=["mcp"],
                tool_metadata={"mcp": {"description": "mcp"}},
            ),
        )

        client.complete(request)
        client.complete(
            request.model_copy(
                update={
                    "tool_result": {
                        "server_id": "github",
                        "full_name": "CloudWide851/easy-agent",
                    },
                    "requested_tool_name": "mcp",
                    "requested_tool_payload": {
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "search_repositories",
                    },
                }
            )
        )

        followup_messages = captured[1]["messages"]
        joined = "\n".join(str(item.get("content", "")) for item in followup_messages)
        self.assertIn("在正常回答用户后，请在末尾追加一个", joined)
        self.assertIn("```tool_episode_summary```", joined)

    def test_openai_client_injects_exact_multi_round_fact_for_late_tool_followup(
        self,
    ) -> None:
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
            session_id="sess_roundtrip",
            trace_id="trace_roundtrip",
            message="请总结这次链路",
            agent_id="main",
            app_id="main_agent",
            tool_history=[
                ToolExchange(tool_name="time", tool_payload={}, tool_result={"iso_time": "t"}),
                ToolExchange(
                    tool_name="runtime",
                    tool_payload={"action": "context_status"},
                    tool_result={"summary": "ok"},
                ),
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "list"},
                    tool_result={"servers": [{"server_id": "github"}]},
                ),
            ],
            tool_result={"servers": [{"server_id": "github"}]},
            requested_tool_name="mcp",
            requested_tool_payload={"action": "list"},
            available_tools=["time", "runtime", "mcp"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1",
                builtin_tools=["time", "runtime", "mcp"],
            ),
        )

        client.complete(request)

        joined = "\n".join(
            str(item.get("content", "")) for item in captured[0]["messages"]
        )
        self.assertIn("你现在正在第 4 次模型请求", joined)
        self.assertIn("不得写成单次模型执行", joined)

    def test_openai_client_extracts_embedded_tool_episode_summary_from_followup_reply(
        self,
    ) -> None:
        captured: list[dict] = []

        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers
            captured.append(body)
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "仓库默认分支是 main。\n\n```tool_episode_summary\n"
                                '{"summary":"上一轮通过 github MCP 查看了 easy-agent，并确认默认分支为 main。",'
                                '"facts":[{"key":"full_name","value":"CloudWide851/easy-agent"},{"key":"default_branch","value":"main"}],'
                                '"volatile":false,"keep_next_turn":true,"refresh_hint":""}'
                                "\n```"
                            )
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
            message="查一下 easy-agent",
            agent_id="main",
            app_id="main_agent",
            tool_result={
                "result_text": '{"items":[{"full_name":"CloudWide851/easy-agent","default_branch":"main"}]}'
            },
            requested_tool_name="mcp",
            requested_tool_payload={"action": "call"},
            available_tools=["mcp"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["mcp"]
            ),
        )

        reply = client.complete(request)

        self.assertEqual(reply.final_text, "仓库默认分支是 main。")
        self.assertEqual(
            reply.tool_episode_summary_draft.summary,
            "上一轮通过 github MCP 查看了 easy-agent，并确认默认分支为 main。",
        )
        joined = "\n".join(
            str(item.get("content", "")) for item in captured[0]["messages"]
        )
        self.assertIn("tool_episode_summary", joined)

    def test_openai_client_keeps_capability_catalog_on_first_turn_with_tools(
        self,
    ) -> None:
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
            agent_id="main",
            app_id="main_agent",
            capability_catalog_text="Capability catalog:\n- mcp: Use MCP progressively.\n- time: Check live time first.",
            available_tools=["mcp", "time"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["mcp", "time"]
            ),
        )

        client.complete(request)

        first_turn_messages = captured[0]["messages"]
        joined = "\n".join(str(item.get("content", "")) for item in first_turn_messages)
        self.assertIn("Capability catalog", joined)
        self.assertIn("Use MCP progressively", joined)
        self.assertIn("Check live time first", joined)

    def test_openai_client_omits_capability_catalog_and_narrows_tools_for_explicit_multi_step_request(
        self,
    ) -> None:
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
            session_id="sess_multi",
            trace_id="trace_multi",
            message="请严格按顺序先调用 time 获取当前时间，再调用 runtime 查看当前 run 的 context_status，再调用 mcp 列出 github server 的可用工具。",
            agent_id="main",
            app_id="main_agent",
            capability_catalog_text="Capability catalog:\n- time\n- runtime\n- mcp\n- session\n- skill",
            available_tools=["time", "runtime", "mcp", "session", "skill"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_multi",
                builtin_tools=["time", "runtime", "mcp", "session", "skill"],
            ),
        )

        client.complete(request)

        joined = "\n".join(str(item.get("content", "")) for item in captured[0]["messages"])
        self.assertNotIn("Capability catalog", joined)
        tool_names = [item["function"]["name"] for item in captured[0]["tools"]]
        self.assertEqual(tool_names, ["time", "runtime", "mcp"])

    def test_openai_client_omits_capability_catalog_for_explicit_subagent_request(
        self,
    ) -> None:
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
            session_id="sess_subagent_explicit",
            trace_id="trace_subagent_explicit",
            message="开启子代理查询 https://github.com/CloudWide851/easy-agent 最近一次提交是什么时候？",
            agent_id="main",
            app_id="main_agent",
            capability_catalog_text="Capability catalog:\n- mcp\n- spawn_subagent\n- cancel_subagent",
            available_tools=["mcp", "spawn_subagent", "cancel_subagent"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_subagent_explicit",
                builtin_tools=["mcp", "spawn_subagent", "cancel_subagent"],
            ),
        )

        client.complete(request)

        joined = "\n".join(str(item.get("content", "")) for item in captured[0]["messages"])
        self.assertNotIn("Capability catalog", joined)

    def test_openai_client_adds_runtime_guard_for_natural_language_context_followup(
        self,
    ) -> None:
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
            message="现在上下文用了多少，简短一点。",
            agent_id="main",
            app_id="main_agent",
            available_tools=["runtime", "mcp"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["runtime", "mcp"]
            ),
        )

        client.complete(request)

        joined = "\n".join(
            str(item.get("content", "")) for item in captured[0]["messages"]
        )
        self.assertIn("这是实时上下文查询", joined)
        self.assertIn("请先读取当前 runtime 状态", joined)
        self.assertIn("不要直接凭记忆概括当前上下文占用", joined)

    def test_openai_client_adds_direct_github_repo_mcp_hint_for_explicit_repo_query(
        self,
    ) -> None:
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
            message="请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库的默认分支和描述。",
            agent_id="main",
            app_id="main_agent",
            available_tools=["mcp"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["mcp"]
            ),
        )

        client.complete(request)

        joined = "\n".join(
            str(item.get("content", "")) for item in captured[0]["messages"]
        )
        self.assertNotIn("GitHub 仓库元数据查询", joined)
        self.assertNotIn("仓库元数据", joined)
        self.assertNotIn("search_repositories", joined)
        self.assertNotIn("repo:CloudWide851/easy-agent", joined)
        self.assertNotIn("{", joined)

    def test_openai_client_adds_direct_github_commit_hint_for_explicit_repo_commit_query(
        self,
    ) -> None:
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
            message="请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库最近一次提交是什么时候？",
            agent_id="main",
            app_id="main_agent",
            available_tools=["mcp"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["mcp"]
            ),
        )

        client.complete(request)

        joined = "\n".join(
            str(item.get("content", "")) for item in captured[0]["messages"]
        )
        self.assertNotIn("GitHub 仓库提交查询", joined)
        self.assertNotIn("最新 commit", joined)
        self.assertNotIn("list_commits", joined)
        self.assertNotIn("{", joined)
        self.assertNotIn("perPage", joined)
        self.assertNotIn("server_id", joined)
        self.assertNotIn("arguments", joined)

    def test_openai_client_exposes_spawn_subagent_capability_guidance(self) -> None:
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
        declarations = get_capability_declarations()
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="开启子代理查询 https://github.com/CloudWide851/easy-agent 最近一次提交是什么时候？",
            agent_id="main",
            app_id="main_agent",
            capability_catalog_text=render_capability_catalog(declarations),
            available_tools=["mcp", "spawn_subagent", "cancel_subagent"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1",
                builtin_tools=["mcp", "spawn_subagent", "cancel_subagent"],
                tool_metadata={
                    "mcp": {
                        "description": declarations["mcp"].summary,
                        "parameters_schema": declarations["mcp"].parameters_schema,
                    },
                    "spawn_subagent": {
                        "description": " ".join(
                            [
                                declarations["spawn_subagent"].summary,
                                f"Rules: {' '.join(declarations['spawn_subagent'].usage_rules)}",
                            ]
                        ),
                        "parameters_schema": declarations["spawn_subagent"].parameters_schema,
                    },
                    "cancel_subagent": {
                        "description": " ".join(
                            [
                                declarations["cancel_subagent"].summary,
                                f"Rules: {' '.join(declarations['cancel_subagent'].usage_rules)}",
                            ]
                        ),
                        "parameters_schema": declarations["cancel_subagent"].parameters_schema,
                    },
                },
            ),
        )

        client.complete(request)

        joined = "\n".join(
            str(item.get("content", "")) for item in captured[0]["messages"]
        )
        self.assertIn("这是显式子代理请求", joined)
        self.assertIn("优先使用 spawn_subagent", joined)
        tool_defs = captured[0]["tools"]
        self.assertEqual(
            [item["function"]["name"] for item in tool_defs],
            ["spawn_subagent", "mcp"],
        )
        spawn_desc = next(
            item["function"]["description"]
            for item in tool_defs
            if item["function"]["name"] == "spawn_subagent"
        )
        self.assertIn(
            "When the user explicitly asks to 开启子代理/后台执行, prefer this",
            spawn_desc,
        )
        self.assertIn(
            "Only use acceptance/waiting wording such as 已受理",
            spawn_desc,
        )

    def test_openai_client_adds_time_specific_instruction_for_live_time_query(self) -> None:
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
            message="请告诉我现在几点了？",
            agent_id="main",
            app_id="main_agent",
            available_tools=["time"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["time"]
            ),
        )

        client.complete(request)

        joined = "\n".join(
            str(item.get("content", "")) for item in captured[0]["messages"]
        )
        self.assertIn("这是当前时间查询", joined)
        self.assertIn("请先读取当前时间工具结果", joined)
        self.assertIn("不要直接凭记忆猜测现在时间", joined)

    def test_openai_client_injects_channel_protocol_instruction_when_provided(
        self,
    ) -> None:
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
        feishu_instruction = "Feishu 结构化回复协议：代码围栏标识必须是 `feishu_card`"
        request = LLMRequest(
            session_id="sess_1",
            trace_id="trace_1",
            message="请整理成适合飞书展示的结果。",
            agent_id="main",
            app_id="main_agent",
            channel_protocol_instruction_text=feishu_instruction,
            available_tools=["skill"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["skill"]
            ),
        )

        client.complete(request)

        joined = "\n".join(
            str(item.get("content", "")) for item in captured[0]["messages"]
        )
        self.assertIn("Feishu 结构化回复协议", joined)
        self.assertIn("代码围栏标识必须是 `feishu_card`", joined)

    def test_default_transport_raises_runtime_error_on_http_error(self) -> None:
        with mock.patch(
            "httpx.post",
            side_effect=httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("POST", "https://example.com"),
                response=httpx.Response(500, text="{}"),
            ),
        ):
            with self.assertRaises(Exception):
                _default_transport("https://example.com", {}, {})

    def test_openai_5_series_consumes_responses_sse_text_stream_with_default_transport(self) -> None:
        response = mock.MagicMock()
        response.iter_lines.return_value = iter(
            [
                'event: response.created',
                'data: {"type":"response.created","response":{"id":"resp_1","status":"in_progress","output":[],"error":null}}',
                "",
                'event: response.output_item.done',
                'data: {"type":"response.output_item.done","item":{"id":"msg_1","type":"message","status":"completed","role":"assistant","content":[{"type":"output_text","text":"OK"}]}}',
                "",
                'event: response.output_text.delta',
                'data: {"type":"response.output_text.delta","delta":"OK"}',
                "",
                'event: response.completed',
                'data: {"type":"response.completed","response":{"id":"resp_1","status":"completed","output":[],"error":null,"usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2}}}',
                "",
            ]
        )
        stream_cm = mock.MagicMock()
        stream_cm.__enter__.return_value = response
        stream_cm.__exit__.return_value = False

        with mock.patch(
            "marten_runtime.runtime.llm_adapters.openai_compat.httpx.stream",
            return_value=stream_cm,
        ) as stream_mock:
            client = OpenAIChatLLMClient(
                api_key="secret",
                model="gpt-5.4",
                profile_name="default",
            )
            reply = client.complete(
                LLMRequest(
                    session_id="sess_1",
                    trace_id="trace_1",
                    message="hello",
                    agent_id="main",
                    app_id="main_agent",
                    request_kind="interactive",
                )
            )

        self.assertEqual(reply.final_text, "OK")
        stream_mock.assert_called_once()

    def test_openai_5_series_consumes_responses_sse_function_call_stream_with_default_transport(
        self,
    ) -> None:
        response = mock.MagicMock()
        response.iter_lines.return_value = iter(
            [
                'event: response.output_item.added',
                'data: {"type":"response.output_item.added","item":{"id":"fc_1","type":"function_call","call_id":"call_1","name":"time","arguments":""}}',
                "",
                'event: response.function_call_arguments.delta',
                'data: {"type":"response.function_call_arguments.delta","call_id":"call_1","delta":"{\\"timezone\\":\\"UTC\\"}"}',
                "",
                'event: response.output_item.done',
                'data: {"type":"response.output_item.done","item":{"id":"fc_1","type":"function_call","call_id":"call_1","name":"time"}}',
                "",
                'event: response.completed',
                'data: {"type":"response.completed","response":{"id":"resp_1","status":"completed","output":[],"error":null}}',
                "",
            ]
        )
        stream_cm = mock.MagicMock()
        stream_cm.__enter__.return_value = response
        stream_cm.__exit__.return_value = False

        with mock.patch(
            "marten_runtime.runtime.llm_adapters.openai_compat.httpx.stream",
            return_value=stream_cm,
        ):
            client = OpenAIChatLLMClient(
                api_key="secret",
                model="gpt-5.4",
                profile_name="default",
            )
            reply = client.complete(
                LLMRequest(
                    session_id="sess_1",
                    trace_id="trace_1",
                    message="hello",
                    agent_id="main",
                    app_id="main_agent",
                    request_kind="interactive",
                    available_tools=["time"],
                    tool_snapshot=ToolSnapshot(
                        tool_snapshot_id="tool_1", builtin_tools=["time"]
                    ),
                )
            )

        self.assertEqual(reply.tool_name, "time")
        self.assertEqual(reply.tool_payload, {"timezone": "UTC"})

    def test_openai_client_stops_retry_when_stop_event_is_set(self) -> None:
        captured: list[dict[str, object]] = []
        stop_event = threading.Event()

        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float,
            **kwargs,
        ) -> dict:
            del url, headers, body
            captured.append({"timeout_seconds": timeout_seconds, **kwargs})
            stop_event.set()
            raise TimeoutError("timed out")

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="MiniMax-M2.5",
            profile_name="minimax_coding",
            transport=fake_transport,
        )

        with self.assertRaises(ProviderTransportError) as ctx:
            client.complete(
                LLMRequest(
                    session_id="sess_stop",
                    trace_id="trace_stop",
                    message="hello",
                    agent_id="main",
                    app_id="main_agent",
                    request_kind="interactive",
                    cooperative_stop_event=stop_event,
                )
            )

        self.assertEqual(len(captured), 1)
        self.assertIs(captured[0]["stop_event"], stop_event)
        self.assertEqual(ctx.exception.error_code, "PROVIDER_TIMEOUT")

    def test_openai_client_uses_wider_budget_for_explicit_subagent_request(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float,
            **kwargs,
        ) -> dict:
            del url, headers, body, kwargs
            captured.append({"timeout_seconds": timeout_seconds})
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="MiniMax-M2.5",
            profile_name="minimax_coding",
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_subagent_timeout",
                trace_id="trace_subagent_timeout",
                message="开启子代理查询 https://github.com/CloudWide851/easy-agent 最近一次提交是什么时候？",
                agent_id="main",
                app_id="main_agent",
                request_kind="interactive",
                available_tools=["spawn_subagent", "mcp"],
                tool_snapshot=ToolSnapshot(
                    tool_snapshot_id="tool_subagent_timeout",
                    builtin_tools=["spawn_subagent", "mcp"],
                ),
            )
        )

        self.assertEqual(reply.final_text, "ok")
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["timeout_seconds"], 30)

    def test_openai_client_preserves_subsecond_deadline_for_transport_timeout(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float,
            **kwargs,
        ) -> dict:
            del url, headers, body, kwargs
            captured.append({"timeout_seconds": timeout_seconds})
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="MiniMax-M2.5",
            profile_name="minimax_coding",
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_subsecond_deadline",
                trace_id="trace_subsecond_deadline",
                message="hello",
                agent_id="main",
                app_id="main_agent",
                request_kind="interactive",
                timeout_seconds_override=10,
                cooperative_deadline_monotonic=time.monotonic() + 0.2,
            )
        )

        self.assertEqual(reply.final_text, "ok")
        self.assertEqual(len(captured), 1)
        self.assertLess(captured[0]["timeout_seconds"], 0.5)

    def test_openai_client_passes_deadline_to_transport_and_clamps_timeout(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_transport(
            url: str,
            headers: dict[str, str],
            body: dict,
            timeout_seconds: float,
            **kwargs,
        ) -> dict:
            del url, headers, body
            captured.append({"timeout_seconds": timeout_seconds, **kwargs})
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="MiniMax-M2.5",
            profile_name="minimax_coding",
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_deadline",
                trace_id="trace_deadline",
                message="hello",
                agent_id="main",
                app_id="main_agent",
                request_kind="interactive",
                timeout_seconds_override=10,
                cooperative_deadline_monotonic=time.monotonic() + 1.0,
            )
        )

        self.assertEqual(reply.final_text, "ok")
        self.assertEqual(len(captured), 1)
        self.assertLessEqual(captured[0]["timeout_seconds"], 1.0)
        self.assertGreater(captured[0]["timeout_seconds"], 0.5)
        self.assertIn("deadline_monotonic", captured[0])


if __name__ == "__main__":
    unittest.main()
