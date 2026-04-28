import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from marten_runtime.interfaces.http.bootstrap import build_http_runtime
from marten_runtime.interfaces.http.app import create_app
from marten_runtime.mcp.models import MCPServerSpec, MCPToolSpec
from marten_runtime.observability.langfuse import build_langfuse_observer
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.tools.builtins.mcp_tool import run_mcp_tool
from tests.http_app_support import build_test_app


def _write_test_app(
    root: Path,
    app_id: str,
    *,
    prompt_mode: str,
    marker: str,
    default_agent: str = "main",
) -> None:
    app_root = root / "apps" / app_id
    app_root.mkdir(parents=True, exist_ok=True)
    (app_root / "app.toml").write_text(
        (
            f'app_id = "{app_id}"\n'
            'app_version = "0.1.0"\n'
            f'default_agent = "{default_agent}"\n'
            f'prompt_mode = "{prompt_mode}"\n'
            'delegation_policy = "isolated_session_only"\n\n'
            '[bootstrap]\n'
            f'root = "apps/{app_id}"\n'
            'agents = "AGENTS.md"\n'
            'identity = "SOUL.md"\n'
            'tools = "TOOLS.md"\n'
            'bootstrap = "BOOTSTRAP.md"\n\n'
            '[skills]\nrequired = []\n\n'
            '[mcp]\nrequired_servers = []\n'
        ),
        encoding="utf-8",
    )
    (app_root / "BOOTSTRAP.md").write_text(f"{marker} bootstrap", encoding="utf-8")
    (app_root / "SOUL.md").write_text(f"{marker} soul", encoding="utf-8")
    (app_root / "AGENTS.md").write_text(f"{marker} agents", encoding="utf-8")
    (app_root / "TOOLS.md").write_text(f"{marker} tools", encoding="utf-8")


def _write_test_repo(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "config" / "agents.toml").write_text(
        (
            '[agents.main]\n'
            'role = "general_assistant"\n'
            'app_id = "main_agent"\n'
            'allowed_tools = ["automation", "mcp", "runtime", "self_improve", "skill", "time", "spawn_subagent", "cancel_subagent"]\n'
            'prompt_mode = "full"\n'
            'model_profile = "minimax_m25"\n\n'
            '[agents.coding]\n'
            'role = "coding_agent"\n'
            'app_id = "code_assistant"\n'
            'allowed_tools = ["runtime", "skill", "time"]\n'
            'prompt_mode = "child"\n'
            'model_profile = "openai_gpt5"\n'
        ),
        encoding="utf-8",
    )
    (root / "config" / "models.toml").write_text(
        (
            'default_profile = "openai_gpt5"\n\n'
            '[profiles.openai_gpt5]\n'
            'provider_ref = "openai"\n'
            'model = "gpt-5.4"\n'
            'fallback_profiles = ["kimi_k2", "minimax_m25"]\n\n'
            '[profiles.kimi_k2]\n'
            'provider_ref = "kimi"\n'
            'model = "kimi-k2"\n\n'
            '[profiles.minimax_m25]\n'
            'provider_ref = "minimax"\n'
            'model = "MiniMax-M2.5"\n'
        ),
        encoding="utf-8",
    )
    (root / "config" / "providers.toml").write_text(
        (
            '[providers.openai]\n'
            'adapter = "openai_compat"\n'
            'base_url = "https://api.openai.com/v1"\n'
            'api_key_env = "OPENAI_API_KEY"\n'
            'supports_responses_api = true\n'
            'supports_responses_streaming = true\n'
            'supports_chat_completions = true\n\n'
            '[providers.minimax]\n'
            'adapter = "openai_compat"\n'
            'base_url = "https://api.minimaxi.com/v1"\n'
            'api_key_env = "MINIMAX_API_KEY"\n'
            'supports_responses_api = false\n'
            'supports_responses_streaming = false\n'
            'supports_chat_completions = true\n\n'
            '[providers.kimi]\n'
            'adapter = "openai_compat"\n'
            'base_url = "https://api.moonshot.cn/v1"\n'
            'api_key_env = "KIMI_API_KEY"\n'
            'supports_responses_api = false\n'
            'supports_responses_streaming = false\n'
            'supports_chat_completions = true\n'
        ),
        encoding="utf-8",
    )
    (root / "config" / "bindings.toml").write_text(
        (
            '[[bindings]]\n'
            'agent_id = "main"\n'
            'channel_id = "http"\n'
            'default = true\n'
        ),
        encoding="utf-8",
    )
    _write_test_app(root, "main_agent", prompt_mode="full", marker="DEFAULT APP", default_agent="main")
    _write_test_app(root, "code_assistant", prompt_mode="child", marker="CODE APP", default_agent="coding")


def _write_session_enabled_coding_repo(root: Path) -> None:
    _write_test_repo(root)
    (root / "config" / "agents.toml").write_text(
        (
            '[agents.main]\n'
            'role = "general_assistant"\n'
            'app_id = "main_agent"\n'
            'allowed_tools = ["automation", "mcp", "runtime", "self_improve", "session", "skill", "time", "spawn_subagent", "cancel_subagent"]\n'
            'prompt_mode = "full"\n'
            'model_profile = "minimax_m25"\n\n'
            '[agents.coding]\n'
            'role = "coding_agent"\n'
            'app_id = "code_assistant"\n'
            'allowed_tools = ["session", "runtime", "skill", "time"]\n'
            'prompt_mode = "child"\n'
            'model_profile = "openai_gpt5"\n'
        ),
        encoding="utf-8",
    )
    (root / "config" / "bindings.toml").write_text("", encoding="utf-8")


def _build_repo_backed_test_app(root: Path):
    return create_app(
        repo_root=root,
        env={"MINIMAX_API_KEY": "minimax-test", "OPENAI_API_KEY": "openai-test"},
        load_env_file=False,
    )


class _AcceptanceFakeLangfuseClient:
    def __init__(self) -> None:
        self.traces: list[dict] = []
        self.generations: list[dict] = []
        self.tool_spans: list[dict] = []
        self.finalizations: list[dict] = []

    def create_trace(self, payload: dict) -> dict:
        self.traces.append(payload)
        trace_id = str(payload.get("trace_id") or "lf-generated")
        return {
            "trace_id": trace_id,
            "url": f"https://langfuse.example/trace/{trace_id}",
        }

    def record_generation(self, payload: dict) -> None:
        self.generations.append(payload)

    def record_tool_span(self, payload: dict) -> None:
        self.tool_spans.append(payload)

    def finalize_trace(self, payload: dict) -> None:
        self.finalizations.append(payload)

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass




class PromptTooLongThenCompactThenFinalLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def __init__(self) -> None:
        self.requests = []
        self._calls = 0

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("provider_http_error:400:prompt too long")
        if request.agent_id == "compaction":
            return LLMReply(final_text="当前进展：旧历史已经压缩。\n明确下一步：继续回答用户问题。")
        return LLMReply(final_text="reactive compact final")


class AcceptanceTests(unittest.TestCase):
    def test_feishu_second_turn_reuses_durable_detail_from_previous_structured_reply(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        captured_second_turn_history: list[SessionMessage] = []

        def fake_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            if message == "先给我检查结果":
                return [
                    OutboundEvent(
                        session_id=session_id,
                        run_id="run_acceptance_feishu_durable_1",
                        event_id="evt_acceptance_feishu_durable_progress_1",
                        event_type="progress",
                        sequence=1,
                        trace_id=trace_id or "trace_missing",
                        payload={"text": "running"},
                        created_at=datetime.now(timezone.utc),
                    ),
                    OutboundEvent(
                        session_id=session_id,
                        run_id="run_acceptance_feishu_durable_1",
                        event_id="evt_acceptance_feishu_durable_final_1",
                        event_type="final",
                        sequence=2,
                        trace_id=trace_id or "trace_missing",
                        payload={
                            "text": (
                                "检查完成。\n\n"
                                "```feishu_card\n"
                                '{"title":"检查结果","summary":"共 2 项","sections":[{"items":["builtin 正常","mcp 正常"]}]}\n'
                                "```"
                            )
                        },
                        created_at=datetime.now(timezone.utc),
                    ),
                ]
            captured_second_turn_history.extend(kwargs.get("session_messages") or [])
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_acceptance_feishu_durable_2",
                    event_id="evt_acceptance_feishu_durable_progress_2",
                    event_type="progress",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "running"},
                    created_at=datetime.now(timezone.utc),
                ),
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_acceptance_feishu_durable_2",
                    event_id="evt_acceptance_feishu_durable_final_2",
                    event_type="final",
                    sequence=2,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "第二轮已读取到 mcp 正常"},
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        runtime.runtime_loop.run = fake_run  # type: ignore[method-assign]

        with TestClient(app) as client:
            first = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "acceptance-feishu-durable",
                    "message_id": "1",
                    "body": "先给我检查结果",
                },
            )
            second = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "acceptance-feishu-durable",
                    "message_id": "2",
                    "body": "刚才 mcp 的结果是什么？",
                },
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(
            any(
                item.role == "assistant"
                and item.content == "检查完成。\n\n共 2 项\n\n- builtin 正常\n- mcp 正常"
                for item in captured_second_turn_history
            )
        )
        self.assertEqual(second.json()["events"][-1]["payload"]["text"], "第二轮已读取到 mcp 正常")

    def test_langfuse_full_chain_covers_plain_builtin_and_mcp_turns(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        fake_langfuse = _AcceptanceFakeLangfuseClient()
        observer = build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=fake_langfuse,
        )
        runtime.langfuse_observer = observer
        runtime.runtime_loop.langfuse_observer = observer

        class AcceptanceRecoveringClient:
            def list_tools(self, server_id: str):
                del server_id
                return [
                    MCPToolSpec(
                        name="search_repositories",
                        description="Search repositories.",
                    )
                ]

            def call_tool(self, server_id: str, tool_name: str, payload: dict) -> dict:
                return {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "result_text": "repo_count=42",
                    "ok": True,
                    "is_error": False,
                }

        runtime.mcp_client = AcceptanceRecoveringClient()  # type: ignore[assignment]
        runtime.mcp_servers = [
            MCPServerSpec(
                server_id="github",
                transport="stdio",
                backend_id="github",
                tools=[
                    MCPToolSpec(
                        name="search_repositories",
                        description="Search repositories.",
                    )
                ],
            )
        ]
        runtime.mcp_discovery = {
            "github": {"state": "discovered", "tool_count": 1, "error": None}
        }
        runtime.tool_registry.register(
            "mcp",
            lambda payload, runtime_state=runtime: run_mcp_tool(
                payload,
                runtime_state.mcp_servers,
                runtime_state.mcp_client,
                runtime_state.mcp_discovery,
            ),
            description=runtime.tool_registry._descriptors["mcp"].description,  # type: ignore[attr-defined]
            source_kind="mcp",
            server_id="github",
        )

        plain_llm = ScriptedLLMClient([LLMReply(final_text="plain-ok")])
        builtin_llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(final_text="runtime-ok"),
            ]
        )
        mcp_llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "search_repositories",
                        "arguments": {"query": "release notes"},
                    },
                ),
                LLMReply(final_text="mcp-ok"),
            ]
        )

        with TestClient(app) as client:
            runtime.runtime_loop.llm = plain_llm
            runtime.llm_client_factory.cache_client("openai_gpt5", plain_llm)
            runtime.llm_client_factory.cache_client("minimax_m25", plain_llm)
            plain = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-langfuse-plain",
                    "message_id": "1",
                    "body": "hello",
                },
            ).json()
            plain_run_diag = client.get(
                f"/diagnostics/run/{plain['events'][-1]['run_id']}"
            ).json()
            plain_trace_diag = client.get(
                f"/diagnostics/trace/{plain['trace_id']}"
            ).json()

            runtime.runtime_loop.llm = builtin_llm
            runtime.llm_client_factory.cache_client("openai_gpt5", builtin_llm)
            runtime.llm_client_factory.cache_client("minimax_m25", builtin_llm)
            builtin = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-langfuse-builtin",
                    "message_id": "2",
                    "body": "当前上下文窗口多大？",
                },
            ).json()
            builtin_run_diag = client.get(
                f"/diagnostics/run/{builtin['events'][-1]['run_id']}"
            ).json()
            builtin_trace_diag = client.get(
                f"/diagnostics/trace/{builtin['trace_id']}"
            ).json()

            runtime.runtime_loop.llm = mcp_llm
            runtime.llm_client_factory.cache_client("openai_gpt5", mcp_llm)
            runtime.llm_client_factory.cache_client("minimax_m25", mcp_llm)
            mcp = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-langfuse-mcp",
                    "message_id": "3",
                    "body": "search release notes",
                },
            ).json()
            mcp_run_diag = client.get(
                f"/diagnostics/run/{mcp['events'][-1]['run_id']}"
            ).json()
            mcp_trace_diag = client.get(
                f"/diagnostics/trace/{mcp['trace_id']}"
            ).json()

        exercised_trace_ids = {
            plain["trace_id"],
            builtin["trace_id"],
            mcp["trace_id"],
        }
        trace_ids = {item["trace_id"] for item in fake_langfuse.traces}
        finalization_by_trace = {
            item["trace_id"]: item for item in fake_langfuse.finalizations
        }
        generation_counts: dict[str, int] = {}
        for item in fake_langfuse.generations:
            generation_counts[item["trace_id"]] = generation_counts.get(
                item["trace_id"], 0
            ) + 1
        tool_spans_by_trace: dict[str, list[dict]] = {}
        for item in fake_langfuse.tool_spans:
            tool_spans_by_trace.setdefault(item["trace_id"], []).append(item)

        self.assertTrue(exercised_trace_ids.issubset(trace_ids))
        self.assertEqual(finalization_by_trace[plain["trace_id"]]["status"], "succeeded")
        self.assertEqual(
            finalization_by_trace[builtin["trace_id"]]["status"], "succeeded"
        )
        self.assertEqual(finalization_by_trace[mcp["trace_id"]]["status"], "succeeded")
        self.assertGreaterEqual(generation_counts[plain["trace_id"]], 1)
        self.assertGreaterEqual(generation_counts[builtin["trace_id"]], 1)
        self.assertGreaterEqual(generation_counts[mcp["trace_id"]], 1)
        self.assertEqual(
            [item["tool_name"] for item in tool_spans_by_trace[builtin["trace_id"]]],
            ["runtime"],
        )
        self.assertEqual(
            [item["tool_name"] for item in tool_spans_by_trace[mcp["trace_id"]]],
            ["mcp"],
        )
        self.assertEqual(
            tool_spans_by_trace[mcp["trace_id"]][0]["metadata"]["source_kind"], "mcp"
        )

        for response, run_diag, trace_diag in (
            (plain, plain_run_diag, plain_trace_diag),
            (builtin, builtin_run_diag, builtin_trace_diag),
            (mcp, mcp_run_diag, mcp_trace_diag),
        ):
            self.assertEqual(
                run_diag["external_observability"]["langfuse_trace_id"],
                response["trace_id"],
            )
            self.assertEqual(
                trace_diag["external_refs"]["langfuse_trace_id"],
                response["trace_id"],
            )
            self.assertEqual(
                trace_diag["external_refs"]["langfuse_url"],
                f"https://langfuse.example/trace/{response['trace_id']}",
            )

    def test_repo_default_channel_template_keeps_feishu_disabled(self) -> None:
        runtime = build_http_runtime(
            env={"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            load_env_file=False,
        )

        self.assertFalse(runtime.channels_config.feishu.enabled)
        self.assertFalse(runtime.channels_config.feishu.auto_start)

    def test_http_runtime_bootstrap_fails_closed_without_provider_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing_llm_api_key:OPENAI_API_KEY"):
            build_http_runtime(env={}, load_env_file=False)

    def test_feishu_websocket_service_starts_with_app_when_channel_enabled(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        enabled_channels_config = runtime.channels_config.model_copy(
            update={
                "feishu": runtime.channels_config.feishu.model_copy(
                    update={"enabled": True, "connection_mode": "websocket", "auto_start": True}
                )
            }
        )

        runtime.channels_config = enabled_channels_config
        with patch.object(runtime.feishu_socket_service, "start_background", new=AsyncMock()) as start_mock:
            with patch.object(runtime.feishu_socket_service, "stop_background", new=AsyncMock()) as stop_mock:
                with TestClient(app) as client:
                    response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        start_mock.assert_awaited_once()
        stop_mock.assert_awaited_once()

    def test_http_messages_cover_plain_chat_mcp_and_generic_repo_request_paths(self) -> None:
        with TestClient(build_test_app()) as client:
            chat = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-chat",
                    "message_id": "1",
                    "body": "hello",
                },
            )
            mcp = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-mcp",
                    "message_id": "2",
                    "body": "search release notes",
                },
            )
            coding = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-coding",
                    "message_id": "3",
                    "body": "please fix bug in repo",
                },
            )

        self.assertEqual(chat.status_code, 200)
        self.assertEqual(mcp.status_code, 200)
        self.assertEqual(coding.status_code, 200)
        self.assertEqual(chat.json()["events"][-1]["event_type"], "final")
        self.assertEqual(mcp.json()["events"][-1]["event_type"], "final")
        self.assertEqual(mcp.json()["events"][-1]["payload"]["text"], "search release notes")
        self.assertNotIn("mock_search", mcp.json()["events"][-1]["payload"]["text"])
        self.assertEqual(coding.json()["events"][0]["event_type"], "progress")

    def test_http_messages_retryable_thin_summary_recovers_and_exposes_finalization_diagnostics(
        self,
    ) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        scripted = ScriptedLLMClient(
            [
                LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"}),
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(tool_name="mcp", tool_payload={"action": "list"}),
                LLMReply(
                    final_text="当前可用 MCP 服务共 1 个。\n- 1. github（38 个工具，状态 discovered）"
                ),
                LLMReply(final_text="工具执行失败，请重试。"),
            ]
        )
        runtime.runtime_loop.llm = scripted
        runtime.llm_client_factory.cache_client("openai_gpt5", scripted)
        runtime.llm_client_factory.cache_client("minimax_m25", scripted)

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-finalization-recovery",
                    "message_id": "1",
                    "body": (
                        "请严格按顺序先调用 time 获取当前时间，"
                        "再调用 runtime 查看当前 run 的 context_status，"
                        "再调用 mcp 列出 github server 的可用工具。"
                    ),
                },
            )
            run_id = response.json()["events"][-1]["run_id"]
            run_diag = client.get(f"/diagnostics/run/{run_id}").json()

        self.assertEqual(response.status_code, 200)
        final_text = response.json()["events"][-1]["payload"]["text"]
        self.assertIn("现在是北京时间", final_text)
        self.assertIn("当前上下文使用详情", final_text)
        self.assertIn("当前可用 MCP 服务共", final_text)
        self.assertEqual(run_diag["finalization"]["assessment"], "retryable_degraded")
        self.assertEqual(run_diag["finalization"]["request_kind"], "finalization_retry")
        self.assertEqual(run_diag["finalization"]["required_evidence_count"], 3)
        self.assertTrue(run_diag["finalization"]["retry_triggered"])
        self.assertTrue(run_diag["finalization"]["recovered_from_fragments"])
        self.assertEqual(len(run_diag["finalization"]["missing_evidence_items"]), 3)
        self.assertEqual(run_diag["finalization"]["invalid_final_text"], "工具执行失败，请重试。")

    def test_http_runtime_switches_llm_client_by_selected_agent_model_profile(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)
            test_app = _build_repo_backed_test_app(repo_root)
            assistant_llm = ScriptedLLMClient([LLMReply(final_text="assistant profile")])
            coding_llm = ScriptedLLMClient([LLMReply(final_text="coding profile")])
            test_app.state.runtime.llm_client_factory.cache_client("minimax_m25", assistant_llm)
            test_app.state.runtime.llm_client_factory.cache_client("openai_gpt5", coding_llm)
            test_app.state.runtime.runtime_loop.llm = assistant_llm

            with TestClient(test_app) as client:
                coding = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "profile-coding",
                        "message_id": "1",
                        "body": "hello coding",
                        "requested_agent_id": "coding",
                    },
                )
                assistant = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "profile-assistant",
                        "message_id": "2",
                        "body": "hello assistant",
                    },
                )

        self.assertEqual(coding.status_code, 200)
        self.assertEqual(assistant.status_code, 200)
        self.assertEqual(coding.json()["events"][-1]["payload"]["text"], "coding profile")
        self.assertEqual(assistant.json()["events"][-1]["payload"]["text"], "assistant profile")
        self.assertEqual(coding_llm.requests[0].agent_id, "coding")
        self.assertEqual(assistant_llm.requests[0].agent_id, "main")

    def test_http_session_new_keeps_next_turn_routed_to_current_active_agent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_session_enabled_coding_repo(repo_root)
            test_app = _build_repo_backed_test_app(repo_root)
            main_llm = ScriptedLLMClient([LLMReply(final_text="main route")])
            coding_llm = ScriptedLLMClient(
                [
                    LLMReply(
                        tool_name="session",
                        tool_payload={"action": "new", "finalize_response": True},
                    ),
                    LLMReply(final_text="coding route retained"),
                ]
            )
            test_app.state.runtime.llm_client_factory.cache_client("minimax_m25", main_llm)
            test_app.state.runtime.llm_client_factory.cache_client("openai_gpt5", coding_llm)
            test_app.state.runtime.runtime_loop.llm = main_llm

            with TestClient(test_app) as client:
                first = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "session-new-routing",
                        "message_id": "1",
                        "body": "切换到新会话",
                        "requested_agent_id": "coding",
                    },
                )
                second = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "session-new-routing",
                        "message_id": "2",
                        "body": "继续",
                    },
                )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["active_session_id"], first.json()["session_id"])
        self.assertEqual(second.json()["active_session_id"], second.json()["session_id"])
        self.assertEqual(second.json()["events"][-1]["payload"]["text"], "coding route retained")
        self.assertEqual(coding_llm.requests[0].agent_id, "coding")
        self.assertEqual(coding_llm.requests[1].agent_id, "coding")

    def test_http_session_resume_switches_immediately_and_completes_source_compaction_in_background(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_session_enabled_coding_repo(repo_root)
            test_app = _build_repo_backed_test_app(repo_root)
            runtime = test_app.state.runtime
            runtime.compaction_worker.stop()
            current = runtime.session_store.create(
                session_id="sess_current",
                conversation_id="resume-async-current",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="http",
            )
            target = runtime.session_store.create(
                session_id="sess_target",
                conversation_id="resume-async-target",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="http",
            )
            runtime.session_store.set_catalog_metadata(
                current.session_id,
                user_id="demo",
                agent_id="coding",
                session_title="current",
                session_preview="current preview",
            )
            runtime.session_store.set_catalog_metadata(
                target.session_id,
                user_id="demo",
                agent_id="coding",
                session_title="target",
                session_preview="target preview",
            )
            for turn in range(1, 11):
                runtime.session_store.append_message(current.session_id, SessionMessage.user(f"历史 {turn}"))
                runtime.session_store.append_message(current.session_id, SessionMessage.assistant(f"完成 {turn}"))
            runtime.session_store.append_message(current.session_id, SessionMessage.user("恢复旧会话"))
            resume_llm = ScriptedLLMClient(
                [
                    LLMReply(
                        tool_name="session",
                        tool_payload={"action": "resume", "session_id": target.session_id},
                    ),
                    LLMReply(final_text=f"已切换到会话 `{target.session_id}`。"),
                ]
            )
            compaction_llm = ScriptedLLMClient([LLMReply(final_text="当前进展：source 已压缩。")])
            runtime.llm_client_factory.cache_client("openai_gpt5", resume_llm)
            runtime.runtime_loop.llm = resume_llm
            runtime.llm_client_factory.create_isolated = lambda profile_name: compaction_llm

            with TestClient(test_app) as client:
                resumed = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "resume-async-current",
                        "message_id": "resume",
                        "body": f"恢复到 {target.session_id}",
                        "requested_agent_id": "coding",
                    },
                )
                drained = runtime.compaction_worker.run_once()
                source_after = runtime.session_store.get(current.session_id)
                rebound_session_id = runtime.session_store.resolve_session_for_conversation(
                    channel_id="http",
                    conversation_id="resume-async-current",
                    user_id="demo",
                )

        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(rebound_session_id, target.session_id)
        self.assertTrue(drained)
        self.assertIsNotNone(source_after.latest_compacted_context)
        self.assertIn("当前进展", source_after.latest_compacted_context.summary_text)

    def test_http_same_session_resume_short_circuits_without_persisting_control_messages(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_session_enabled_coding_repo(repo_root)
            test_app = _build_repo_backed_test_app(repo_root)
            runtime = test_app.state.runtime
            current = runtime.session_store.create(
                session_id="sess_same_current",
                conversation_id="same-session-resume",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="http",
            )
            runtime.session_store.set_catalog_metadata(
                current.session_id,
                user_id="demo",
                agent_id="coding",
                session_title="current",
                session_preview="current preview",
            )
            runtime.session_store.append_message(
                current.session_id,
                SessionMessage.user("seed current"),
            )
            before = runtime.session_store.get(current.session_id)
            before_history = [(item.role, item.content) for item in before.history]
            resume_llm = ScriptedLLMClient(
                [
                    LLMReply(
                        tool_name="session",
                        tool_payload={
                            "action": "resume",
                            "session_id": current.session_id,
                            "finalize_response": True,
                        },
                    )
                ]
            )
            test_app.state.runtime.llm_client_factory.cache_client("openai_gpt5", resume_llm)
            test_app.state.runtime.runtime_loop.llm = resume_llm

            with TestClient(test_app) as client:
                resumed = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": current.conversation_id,
                        "message_id": "resume-same",
                        "body": f"恢复会话 {current.session_id}",
                        "requested_agent_id": "coding",
                    },
                )

            reloaded_current = test_app.state.runtime.session_store.get(current.session_id)

        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(
            [(item.role, item.content) for item in reloaded_current.history],
            before_history,
        )
        self.assertEqual(reloaded_current.last_run_id, resumed.json()["events"][-1]["run_id"])

    def test_http_runtime_switches_app_manifest_and_bootstrap_prompt_by_selected_agent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)
            coding_llm = ScriptedLLMClient([LLMReply(final_text="coding profile")])
            assistant_llm = ScriptedLLMClient([LLMReply(final_text="assistant profile")])
            test_app = _build_repo_backed_test_app(repo_root)
            test_app.state.runtime.llm_client_factory.cache_client("minimax_m25", assistant_llm)
            test_app.state.runtime.llm_client_factory.cache_client("openai_gpt5", coding_llm)
            test_app.state.runtime.runtime_loop.llm = assistant_llm

            with TestClient(test_app) as client:
                response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "app-coding",
                        "message_id": "1",
                        "body": "hello coding",
                        "requested_agent_id": "coding",
                    },
                )
                run_id = response.json()["events"][-1]["run_id"]
                run_diag = client.get(f"/diagnostics/run/{run_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(run_diag.status_code, 200)
        self.assertIn("CODE APP bootstrap", coding_llm.requests[0].system_prompt)
        self.assertIn("你是 `code_assistant`", coding_llm.requests[0].system_prompt)
        self.assertEqual(run_diag.json()["bootstrap_manifest_id"], "boot_code_assistant_child")

    def test_http_messages_proactively_compact_long_history_and_persist_checkpoint(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)
            test_app = _build_repo_backed_test_app(repo_root)
            seed_llm = ScriptedLLMClient([LLMReply(final_text="seed-1"), LLMReply(final_text="seed-2")])
            test_app.state.runtime.llm_client_factory.cache_client("minimax_m25", seed_llm)
            test_app.state.runtime.runtime_loop.llm = seed_llm
            test_app.state.runtime.models_config.profiles["minimax_m25"] = test_app.state.runtime.models_config.profiles[
                "minimax_m25"
            ].model_copy(update={"context_window_tokens": 80, "reserve_output_tokens": 0, "compact_trigger_ratio": 0.2})

            with TestClient(test_app) as client:
                first = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "compact-proactive",
                        "message_id": "1",
                        "body": "这是一个很长的历史起点" * 10,
                    },
                )
                second = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "compact-proactive",
                        "message_id": "2",
                        "body": "补充第二轮上下文，方便后续压缩" * 10,
                    },
                )
                test_app.state.runtime.platform_config.runtime.session_replay_user_turns = 1
                compacting_llm = ScriptedLLMClient(
                    [
                        LLMReply(final_text="当前进展：较早历史已压缩。\n关键决策：保留最近原始尾部。"),
                        LLMReply(final_text="proactive compact final"),
                    ]
                )
                test_app.state.runtime.llm_client_factory.cache_client("minimax_m25", compacting_llm)
                test_app.state.runtime.runtime_loop.llm = compacting_llm
                third = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "compact-proactive",
                        "message_id": "3",
                        "body": "继续执行当前任务，并基于前文给出下一步" * 10,
                    },
                )

            session_id = third.json()["session_id"]
            session = test_app.state.runtime.session_store.get(session_id)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 200)
        self.assertEqual(third.json()["events"][-1]["payload"]["text"], "proactive compact final")
        self.assertIsNotNone(session.latest_compacted_context)
        self.assertIn("当前进展", session.latest_compacted_context.summary_text)
        self.assertGreaterEqual(len(compacting_llm.requests), 2)
        self.assertEqual(compacting_llm.requests[0].agent_id, "compaction")
        self.assertIn("当前进展", compacting_llm.requests[-1].compact_summary_text or "")

    def test_http_messages_reactively_compact_after_prompt_too_long_and_retry(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)
            test_app = _build_repo_backed_test_app(repo_root)
            seed_llm = ScriptedLLMClient([LLMReply(final_text="seed-1"), LLMReply(final_text="seed-2")])
            test_app.state.runtime.llm_client_factory.cache_client("minimax_m25", seed_llm)
            test_app.state.runtime.runtime_loop.llm = seed_llm

            with TestClient(test_app) as client:
                first = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "compact-reactive",
                        "message_id": "1",
                        "body": "第一轮历史内容" * 10,
                    },
                )
                second = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "compact-reactive",
                        "message_id": "2",
                        "body": "第二轮历史内容" * 10,
                    },
                )
                test_app.state.runtime.platform_config.runtime.session_replay_user_turns = 1
                llm = PromptTooLongThenCompactThenFinalLLMClient()
                test_app.state.runtime.llm_client_factory.cache_client("minimax_m25", llm)
                test_app.state.runtime.runtime_loop.llm = llm
                response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "compact-reactive",
                        "message_id": "3",
                        "body": "继续执行超长线程任务" * 20,
                    },
                )

            session = test_app.state.runtime.session_store.get(response.json()["session_id"])

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][-1]["payload"]["text"], "reactive compact final")
        self.assertEqual(len(llm.requests), 3)
        self.assertEqual(llm.requests[1].agent_id, "compaction")
        self.assertIn("当前进展", llm.requests[-1].compact_summary_text or "")
        self.assertIsNotNone(session.latest_compacted_context)
        self.assertIn("当前进展", session.latest_compacted_context.summary_text)


if __name__ == "__main__":
    unittest.main()
