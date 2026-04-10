import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from marten_runtime.interfaces.http.bootstrap import build_http_runtime
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from tests.http_app_support import build_test_app


def _write_test_app(root: Path, app_id: str, *, prompt_mode: str, marker: str, default_agent: str = "assistant") -> None:
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
        encoding='utf-8',
    )
    (app_root / 'BOOTSTRAP.md').write_text(f'{marker} bootstrap', encoding='utf-8')
    (app_root / 'SOUL.md').write_text(f'{marker} soul', encoding='utf-8')
    (app_root / 'AGENTS.md').write_text(f'{marker} agents', encoding='utf-8')
    (app_root / 'TOOLS.md').write_text(f'{marker} tools', encoding='utf-8')


def _write_test_repo(root: Path) -> None:
    (root / 'config').mkdir(parents=True, exist_ok=True)
    (root / 'skills').mkdir(parents=True, exist_ok=True)
    (root / 'data').mkdir(parents=True, exist_ok=True)
    (root / 'config' / 'agents.toml').write_text(
        (
            '[agents.assistant]\n'
            'role = "general_assistant"\n'
            'app_id = "example_assistant"\n'
            'allowed_tools = ["automation", "mcp", "runtime", "self_improve", "skill", "time"]\n'
            'prompt_mode = "full"\n'
            'model_profile = "minimax_coding"\n\n'
            '[agents.coding]\n'
            'role = "coding_agent"\n'
            'app_id = "code_assistant"\n'
            'allowed_tools = ["runtime", "skill", "time"]\n'
            'prompt_mode = "child"\n'
            'model_profile = "default"\n'
        ),
        encoding='utf-8',
    )
    (root / 'config' / 'bindings.toml').write_text(
        (
            '[[bindings]]\n'
            'agent_id = "assistant"\n'
            'channel_id = "http"\n'
            'default = true\n'
        ),
        encoding='utf-8',
    )
    _write_test_app(root, 'example_assistant', prompt_mode='full', marker='DEFAULT APP', default_agent='assistant')
    _write_test_app(root, 'code_assistant', prompt_mode='child', marker='CODE APP', default_agent='coding')




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
    def test_repo_default_channel_template_keeps_feishu_disabled(self) -> None:
        runtime = build_http_runtime(
            env={"MINIMAX_API_KEY": "test-key"},
            load_env_file=False,
            use_compat_json=False,
        )

        self.assertFalse(runtime.channels_config.feishu.enabled)
        self.assertFalse(runtime.channels_config.feishu.auto_start)

    def test_http_runtime_bootstrap_fails_closed_without_provider_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing_llm_api_key:MINIMAX_API_KEY"):
            build_http_runtime(env={}, load_env_file=False, use_compat_json=False)

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

    def test_http_messages_persists_tool_outcome_summary_after_tool_turn(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        scripted = ScriptedLLMClient(
            [
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(final_text="先给你看了上下文状态"),
            ]
        )
        runtime.llm_client_factory.cache_client("minimax_coding", scripted)
        runtime.runtime_loop.llm = scripted

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-tool-summary",
                    "message_id": "1",
                    "body": "当前上下文窗口多大？",
                },
            )

            session = client.app.state.runtime.session_store.get(response.json()["session_id"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.recent_tool_outcome_summaries, [])

    def test_followup_turn_reinjects_recent_tool_outcome_summary_without_replaying_raw_tool_messages(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        first_llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
                LLMReply(final_text="先给你看了上下文状态"),
            ]
        )
        second_llm = ScriptedLLMClient([LLMReply(final_text="followup-ok")])
        runtime.llm_client_factory.cache_client("minimax_coding", first_llm)
        runtime.runtime_loop.llm = first_llm

        with TestClient(app) as client:
            first = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-tool-summary-followup",
                    "message_id": "1",
                    "body": "当前上下文窗口多大？",
                },
            )
            runtime.llm_client_factory.cache_client("minimax_coding", second_llm)
            runtime.runtime_loop.llm = second_llm
            second = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-tool-summary-followup",
                    "message_id": "2",
                    "body": "刚才峰值为什么高？",
                },
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second_llm.requests[0].tool_outcome_summary_text)
        self.assertTrue(all(item.role in {"user", "assistant"} for item in second_llm.requests[0].conversation_messages))

    def test_http_runtime_switches_llm_client_by_selected_agent_model_profile(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)

            from marten_runtime.interfaces.http.app import create_app
            test_app = create_app(
                repo_root=repo_root,
                env={"MINIMAX_API_KEY": "minimax-test", "OPENAI_API_KEY": "openai-test"},
                load_env_file=False,
                use_compat_json=False,
            )
            assistant_llm = ScriptedLLMClient([LLMReply(final_text="assistant profile")])
            coding_llm = ScriptedLLMClient([LLMReply(final_text="coding profile")])
            test_app.state.runtime.llm_client_factory.cache_client("minimax_coding", assistant_llm)
            test_app.state.runtime.llm_client_factory.cache_client("default", coding_llm)
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
        self.assertEqual(assistant_llm.requests[0].agent_id, "assistant")

    def test_http_runtime_switches_app_manifest_and_bootstrap_prompt_by_selected_agent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_test_repo(repo_root)
            coding_llm = ScriptedLLMClient([LLMReply(final_text="coding profile")])
            assistant_llm = ScriptedLLMClient([LLMReply(final_text="assistant profile")])

            from marten_runtime.interfaces.http.app import create_app
            test_app = create_app(
                repo_root=repo_root,
                env={"MINIMAX_API_KEY": "minimax-test", "OPENAI_API_KEY": "openai-test"},
                load_env_file=False,
                use_compat_json=False,
            )
            test_app.state.runtime.llm_client_factory.cache_client("minimax_coding", assistant_llm)
            test_app.state.runtime.llm_client_factory.cache_client("default", coding_llm)
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

            from marten_runtime.interfaces.http.app import create_app
            test_app = create_app(
                repo_root=repo_root,
                env={"MINIMAX_API_KEY": "minimax-test", "OPENAI_API_KEY": "openai-test"},
                load_env_file=False,
                use_compat_json=False,
            )
            seed_llm = ScriptedLLMClient([LLMReply(final_text="seed-1"), LLMReply(final_text="seed-2")])
            test_app.state.runtime.llm_client_factory.cache_client("minimax_coding", seed_llm)
            test_app.state.runtime.runtime_loop.llm = seed_llm
            test_app.state.runtime.models_config.profiles["minimax_coding"] = test_app.state.runtime.models_config.profiles[
                "minimax_coding"
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
                compacting_llm = ScriptedLLMClient(
                    [
                        LLMReply(final_text="当前进展：较早历史已压缩。\n关键决策：保留最近原始尾部。"),
                        LLMReply(final_text="proactive compact final"),
                    ]
                )
                test_app.state.runtime.llm_client_factory.cache_client("minimax_coding", compacting_llm)
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

            from marten_runtime.interfaces.http.app import create_app
            test_app = create_app(
                repo_root=repo_root,
                env={"MINIMAX_API_KEY": "minimax-test", "OPENAI_API_KEY": "openai-test"},
                load_env_file=False,
                use_compat_json=False,
            )
            seed_llm = ScriptedLLMClient([LLMReply(final_text="seed-1"), LLMReply(final_text="seed-2")])
            test_app.state.runtime.llm_client_factory.cache_client("minimax_coding", seed_llm)
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
                llm = PromptTooLongThenCompactThenFinalLLMClient()
                test_app.state.runtime.llm_client_factory.cache_client("minimax_coding", llm)
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
