import unittest

from marten_runtime.runtime.llm_client import LLMRequest, OpenAIChatLLMClient
from marten_runtime.tools.registry import ToolSnapshot


class RuntimeUsageTests(unittest.TestCase):
    def test_openai_client_extracts_usage_from_text_reply(self) -> None:
        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers, body
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 123,
                    "completion_tokens": 45,
                    "total_tokens": 168,
                    "prompt_tokens_details": {"cached_tokens": 7},
                    "completion_tokens_details": {"reasoning_tokens": 9},
                },
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_usage_text",
                trace_id="trace_usage_text",
                message="hello",
                agent_id="main",
                app_id="main_agent",
            )
        )

        self.assertEqual(reply.final_text, "ok")
        self.assertIsNotNone(reply.usage)
        assert reply.usage is not None
        self.assertEqual(reply.usage.input_tokens, 123)
        self.assertEqual(reply.usage.output_tokens, 45)
        self.assertEqual(reply.usage.total_tokens, 168)
        self.assertEqual(reply.usage.cached_input_tokens, 7)
        self.assertEqual(reply.usage.reasoning_output_tokens, 9)

    def test_openai_client_extracts_usage_from_tool_call_reply(self) -> None:
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
                                        "arguments": "{\"timezone\":\"UTC\"}",
                                    }
                                }
                            ]
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 88,
                    "completion_tokens": 12,
                    "total_tokens": 100,
                },
            }

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_usage_tool",
                trace_id="trace_usage_tool",
                message="what time",
                agent_id="main",
                app_id="main_agent",
                available_tools=["time"],
                tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_usage", builtin_tools=["time"]),
            )
        )

        self.assertEqual(reply.tool_name, "time")
        self.assertIsNotNone(reply.usage)
        assert reply.usage is not None
        self.assertEqual(reply.usage.input_tokens, 88)
        self.assertEqual(reply.usage.output_tokens, 12)
        self.assertEqual(reply.usage.total_tokens, 100)

    def test_openai_client_handles_missing_usage_payload(self) -> None:
        def fake_transport(url: str, headers: dict[str, str], body: dict) -> dict:
            del url, headers, body
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=fake_transport,
        )

        reply = client.complete(
            LLMRequest(
                session_id="sess_usage_missing",
                trace_id="trace_usage_missing",
                message="hello",
                agent_id="main",
                app_id="main_agent",
            )
        )

        self.assertEqual(reply.final_text, "ok")
        self.assertIsNone(reply.usage)


if __name__ == "__main__":
    unittest.main()
