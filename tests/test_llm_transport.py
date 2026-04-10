import unittest
from pathlib import Path
from unittest import mock

from marten_runtime.runtime.llm_client import (
    LLMRequest,
    OpenAIChatLLMClient,
    _default_transport,
)
from marten_runtime.runtime.provider_retry import ProviderTransportError
from marten_runtime.tools.registry import ToolSnapshot


class OpenAIChatClientTests(unittest.TestCase):
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
            agent_id="assistant",
            app_id="example_assistant",
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
                    agent_id="assistant",
                    app_id="example_assistant",
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
                    agent_id="assistant",
                    app_id="example_assistant",
                    request_kind="automation",
                )
            )

        self.assertEqual(len(captured), 3)
        self.assertTrue(all(item["timeout_seconds"] == 30 for item in captured))
        assert client.last_call_diagnostics is not None
        self.assertEqual(client.last_call_diagnostics.request_kind, "automation")
        self.assertEqual(client.last_call_diagnostics.timeout_seconds, 30)
        self.assertEqual(client.last_call_diagnostics.max_attempts, 3)

    def test_openai_client_keeps_standard_interactive_budget_for_explicit_github_commit_query(self) -> None:
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
                    message="@_user_1 [GitHub - jiji262/ai-agent-021: ai-agent-021：Build AI Agent from 0 to 1](https://github.com/jiji262/ai-agent-021) 这个项目最近一次提交是什么时候",
                    agent_id="assistant",
                    app_id="example_assistant",
                    request_kind="interactive",
                    available_tools=["mcp"],
                    tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_1", builtin_tools=["mcp"]),
                )
            )

        self.assertEqual(len(captured), 2)
        self.assertTrue(all(item["timeout_seconds"] == 20 for item in captured))
        assert client.last_call_diagnostics is not None
        self.assertEqual(client.last_call_diagnostics.timeout_seconds, 20)

    def test_openai_client_uses_moderate_budget_for_interactive_tool_followup(
        self,
    ) -> None:
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
                    message="总结这次工具结果",
                    agent_id="assistant",
                    app_id="example_assistant",
                    request_kind="interactive",
                    tool_result={"ok": True, "result_text": "done"},
                    requested_tool_name="mcp",
                    requested_tool_payload={"action": "call"},
                )
            )

        self.assertEqual(len(captured), 2)
        self.assertTrue(all(item["timeout_seconds"] == 20 for item in captured))
        assert client.last_call_diagnostics is not None
        self.assertEqual(client.last_call_diagnostics.timeout_seconds, 20)
        self.assertEqual(client.last_call_diagnostics.max_attempts, 2)

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
            agent_id="assistant",
            app_id="example_assistant",
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
            agent_id="assistant",
            app_id="example_assistant",
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
            agent_id="assistant",
            app_id="example_assistant",
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
            agent_id="assistant",
            app_id="example_assistant",
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
            agent_id="assistant",
            app_id="example_assistant",
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
            agent_id="assistant",
            app_id="example_assistant",
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
            agent_id="assistant",
            app_id="example_assistant",
            available_tools=["runtime", "mcp"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["runtime", "mcp"]
            ),
        )

        client.complete(request)

        joined = "\n".join(
            str(item.get("content", "")) for item in captured[0]["messages"]
        )
        self.assertIn("这是当前会话的实时上下文查询", joined)
        self.assertIn("请先读取当前 runtime 状态", joined)
        self.assertIn("不要直接复用上一轮记忆里的上下文数字", joined)

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
            agent_id="assistant",
            app_id="example_assistant",
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
            agent_id="assistant",
            app_id="example_assistant",
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

    def test_openai_client_adds_runtime_guard_for_context_detail_query(self) -> None:
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
            message="当前上下文的具体使用详情是什么？",
            agent_id="assistant",
            app_id="example_assistant",
            available_tools=["runtime"],
            tool_snapshot=ToolSnapshot(
                tool_snapshot_id="tool_1", builtin_tools=["runtime"]
            ),
        )

        client.complete(request)

        joined = "\n".join(
            str(item.get("content", "")) for item in captured[0]["messages"]
        )
        self.assertIn("实时", joined)
        self.assertTrue("runtime" in joined.lower() or "上下文" in joined)

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
            agent_id="assistant",
            app_id="example_assistant",
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
            "urllib.request.urlopen",
            side_effect=mock.Mock(read=lambda: b"{}", code=500),
        ):
            with self.assertRaises(Exception):
                _default_transport("https://example.com", {}, {})


if __name__ == "__main__":
    unittest.main()
