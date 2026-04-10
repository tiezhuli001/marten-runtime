import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from marten_runtime.automation.models import AutomationJob
from marten_runtime.channels.dead_letter import InMemoryDeadLetterQueue
from marten_runtime.channels.delivery_retry import DeliveryRetryPolicy
from marten_runtime.channels.feishu.delivery import FeishuDeliveryClient, FeishuDeliveryPayload
from marten_runtime.channels.feishu.delivery_session import InMemoryFeishuDeliverySessionStore
from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.mcp.loader import load_mcp_servers
from marten_runtime.mcp.models import MCPServerSpec, MCPToolSpec
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.self_improve.models import FailureEvent, LessonCandidate, SystemLesson
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.self_improve.service import SelfImproveService, make_default_judge
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.session.compaction import compact_context
from marten_runtime.skills.service import SkillService
from marten_runtime.skills.service import SkillRuntimeView
from marten_runtime.skills.snapshot import SkillSnapshot
from tests.http_app_support import build_test_app


class FailingLLMClient:
    provider_name = "failing"
    model_name = "failing-local"

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("provider_transport_error:connection reset")


class AuthFailingLLMClient:
    provider_name = "auth-failing"
    model_name = "auth-failing-local"

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("provider_http_error:401:unauthorized")


class ContractCompatibilityTests(unittest.TestCase):
    def test_runtime_bootstrap_registers_automation_tool(self) -> None:
        app = build_test_app()

        self.assertIn("skill", app.state.runtime.tool_registry.list())
        self.assertIn("runtime", app.state.runtime.tool_registry.list())
        self.assertIn("mcp", app.state.runtime.tool_registry.list())
        self.assertNotIn("mock_search", app.state.runtime.tool_registry.list())
        self.assertIn("automation", app.state.runtime.tool_registry.list())
        self.assertIn("self_improve", app.state.runtime.tool_registry.list())
        self.assertNotIn("register_automation", app.state.runtime.tool_registry.list())
        self.assertNotIn("list_lesson_candidates", app.state.runtime.tool_registry.list())

    def test_default_assistant_agent_keeps_family_tool_contract(self) -> None:
        app = build_test_app()

        assistant = app.state.runtime.default_agent

        self.assertIn("skill", assistant.allowed_tools)
        self.assertIn("mcp", assistant.allowed_tools)
        self.assertIn("automation", assistant.allowed_tools)
        self.assertIn("self_improve", assistant.allowed_tools)
        self.assertIn("runtime", assistant.allowed_tools)
        self.assertIn("time", assistant.allowed_tools)
        self.assertNotIn("register_automation", assistant.allowed_tools)
        self.assertNotIn("list_lesson_candidates", assistant.allowed_tools)
        self.assertEqual(
            assistant.allowed_tools,
            ["automation", "mcp", "runtime", "self_improve", "skill", "time"],
        )

    def test_mcp_family_tool_is_the_only_model_visible_mcp_entrypoint(self) -> None:
        app = build_test_app()

        tool_names = app.state.runtime.tool_registry.list()

        self.assertIn("mcp", tool_names)
        self.assertFalse(any(name.startswith("mock_") for name in tool_names))

    def test_runtime_bootstrap_uses_capability_catalog_and_descriptions(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        snapshot = runtime.tool_registry.build_snapshot(["automation", "mcp", "runtime", "self_improve", "skill", "time"])
        automation_description = snapshot.tool_metadata["automation"]["description"]
        mcp_description = snapshot.tool_metadata["mcp"]["description"]
        runtime_description = snapshot.tool_metadata["runtime"]["description"]

        self.assertIn("Capability catalog:", runtime.capability_catalog_text or "")
        self.assertIn("automation", runtime.capability_catalog_text or "")
        self.assertIn("mcp", runtime.capability_catalog_text or "")
        self.assertIn("runtime", runtime.capability_catalog_text or "")
        self.assertNotIn("mock_search", runtime.capability_catalog_text or "")
        self.assertNotIn("search_repositories", runtime.capability_catalog_text or "")
        self.assertTrue(automation_description)
        self.assertTrue(mcp_description)
        self.assertTrue(runtime_description)
        self.assertIn("automation", automation_description.lower())
        self.assertIn("github", mcp_description.lower())
        self.assertNotIn("search_repositories", mcp_description)
        self.assertNotIn("list_commits", mcp_description)
        self.assertTrue(
            "runtime" in runtime_description.lower() or "上下文" in runtime_description
        )

    def test_internal_self_improve_automation_is_not_exposed_in_operator_listing(self) -> None:
        app = build_test_app()

        with TestClient(app) as client:
            response = client.get("/automations")

        self.assertEqual(response.status_code, 200)
        automation_ids = {item["automation_id"] for item in response.json()["items"]}
        self.assertNotIn("self_improve_internal", automation_ids)

    def test_internal_self_improve_automation_trigger_accepts_candidate_and_exports_lessons(self) -> None:
        with TemporaryDirectory() as tmpdir:
            app = build_test_app()
            runtime = app.state.runtime
            isolated_store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            runtime.self_improve_store = isolated_store
            runtime.runtime_loop.self_improve_recorder = SelfImproveRecorder(isolated_store)
            runtime.self_improve_service = SelfImproveService(
                isolated_store,
                lessons_path=Path(tmpdir) / "SYSTEM_LESSONS.md",
                judge=make_default_judge(
                    runtime.runtime_loop.llm,
                    app_id="example_assistant",
                    agent_id="assistant",
                ),
            )
            runtime.automation_store.save(
                AutomationJob(
                    automation_id="self_improve_internal",
                    name="Internal Self Improve",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="Summarize repeated failures and later recoveries.",
                    schedule_kind="daily",
                    schedule_expr="03:00",
                    timezone="UTC",
                    session_target="isolated",
                    delivery_channel="http",
                    delivery_target="internal",
                    skill_id="self_improve",
                    enabled=True,
                    internal=True,
                )
            )
            runtime.self_improve_store.record_failure(
                FailureEvent(
                    failure_id="failure_1",
                    agent_id="assistant",
                    run_id="run_1",
                    trace_id="trace_1",
                    session_id="session_1",
                    error_code="PROVIDER_TIMEOUT",
                    error_stage="llm",
                    summary="provider timed out",
                    fingerprint="assistant|hello",
                )
            )
            runtime.self_improve_store.record_failure(
                FailureEvent(
                    failure_id="failure_2",
                    agent_id="assistant",
                    run_id="run_2",
                    trace_id="trace_2",
                    session_id="session_2",
                    error_code="PROVIDER_TIMEOUT",
                    error_stage="llm",
                    summary="provider timed out",
                    fingerprint="assistant|hello",
                )
            )
            runtime.runtime_loop.llm = ScriptedLLMClient(
                [
                    LLMReply(
                        tool_name="self_improve",
                        tool_payload={
                            "action": "save_candidate",
                            "candidate_id": "cand_1",
                            "agent_id": "assistant",
                            "source_fingerprints": ["assistant|hello", "assistant|hello"],
                            "candidate_text": "遇到重复 provider timeout 时先减少无关工具面。",
                            "rationale": "repeated failures with later recovery evidence",
                            "score": 0.95,
                        },
                    ),
                    LLMReply(final_text="self improve ok"),
                    LLMReply(
                        final_text=(
                            '{"accept": true, "reason": "stable repeated recovery pattern", '
                            '"normalized_lesson_text": "遇到重复 provider timeout 时先减少无关工具面。", '
                            '"topic_key": "provider_timeout"}'
                        )
                    ),
                ]
            )
            runtime.self_improve_service.judge = make_default_judge(
                runtime.runtime_loop.llm,
                app_id="example_assistant",
                agent_id="assistant",
            )

            with TestClient(app) as client:
                response = client.post("/automations/self_improve_internal/trigger")

            self.assertEqual(response.status_code, 200)
            lessons = runtime.self_improve_store.list_active_lessons(agent_id="assistant")
            self.assertEqual(len(lessons), 1)
            exported = (Path(tmpdir) / "SYSTEM_LESSONS.md").read_text(encoding="utf-8")
            self.assertIn("遇到重复 provider timeout 时先减少无关工具面。", exported)

    def test_http_and_event_contracts_keep_required_fields(self) -> None:
        with TestClient(build_test_app()) as client:
            message = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "compat",
                    "message_id": "1",
                    "body": "hello",
                },
            ).json()
        event = OutboundEvent(
            session_id="sess_1",
            run_id="run_1",
            event_id="evt_1",
            event_type="final",
            sequence=2,
            trace_id="trace_1",
            payload={"text": "ok"},
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )

        self.assertIn("session_id", message)
        self.assertIn("events", message)
        self.assertEqual(event.trace_id, "trace_1")
        snapshot = compact_context("sess_1", "goal")
        self.assertEqual(snapshot.session_id, "sess_1")
        self.assertEqual(snapshot.continuation_hint, "goal")

    def test_recent_runs_endpoint_lists_latest_runs(self) -> None:
        with TestClient(build_test_app()) as client:
            client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "runs-1",
                    "message_id": "1",
                    "body": "hello",
                },
            )
            client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "runs-2",
                    "message_id": "2",
                    "body": "hello again",
                },
            )
            response = client.get("/diagnostics/runs?limit=2")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(len(body["items"]), 2)
        self.assertIn("run_id", body["items"][0])
        self.assertIn("status", body["items"][0])
        self.assertIn("timings", body["items"][0])
        self.assertIn("total_ms", body["items"][0]["timings"])

    def test_http_messages_can_query_runtime_context_status_through_family_tool(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="runtime", tool_payload={"action": "context_status"}),
            ]
        )
        runtime.runtime_loop.llm = llm
        runtime.llm_client_factory.cache_client("default", llm)
        runtime.llm_client_factory.cache_client("minimax_coding", llm)

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "runtime-status",
                    "message_id": "runtime-1",
                    "body": "当前上下文窗口多大？",
                },
            )

        self.assertEqual(response.status_code, 200)
        final_text = response.json()["events"][-1]["payload"]["text"]
        self.assertIn("当前上下文使用详情", final_text)
        self.assertIn("下一次请求预计输入", final_text)
        self.assertEqual(len(llm.requests), 1)
        run_id = response.json()["events"][-1]["run_id"]
        tool_result = runtime.run_history.get(run_id).tool_calls[0]["tool_result"]
        self.assertTrue(tool_result["ok"])
        self.assertEqual(tool_result["action"], "context_status")
        self.assertEqual(tool_result["model_profile"], "minimax_coding")
        self.assertIn("summary", tool_result)
        self.assertIn("usage_percent", tool_result)
        self.assertIn("effective_window", tool_result)
        self.assertIn("estimate_source", tool_result)
        self.assertIn("next_request_estimate", tool_result)
        self.assertIn("last_actual_usage", tool_result)
        self.assertEqual(
            tool_result["next_request_estimate"]["input_tokens_estimate"],
            tool_result["estimated_usage"],
        )

    def test_plain_chat_turn_does_not_expose_full_tool_surface(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        llm = ScriptedLLMClient([LLMReply(final_text="你好")])
        runtime.runtime_loop.llm = llm

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "plain-chat",
                    "message_id": "plain-1",
                    "body": "你好啊",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(llm.requests[0].available_tools, ["automation", "mcp", "runtime", "self_improve", "skill", "time"])

    def test_github_schedule_turn_keeps_family_tool_surface(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        llm = ScriptedLLMClient([LLMReply(final_text="ok")])
        runtime.runtime_loop.llm = llm

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "github-schedule",
                    "message_id": "github-1",
                    "body": "每天晚上11点25给我推送github热榜",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(llm.requests[0].available_tools, ["automation", "mcp", "runtime", "self_improve", "skill", "time"])

    def test_search_turn_keeps_mcp_family_tool_without_restoring_full_surface(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        llm = ScriptedLLMClient([LLMReply(final_text="ok")])
        runtime.runtime_loop.llm = llm

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "search-turn",
                    "message_id": "search-1",
                    "body": "search release notes",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(llm.requests[0].available_tools, ["automation", "mcp", "runtime", "self_improve", "skill", "time"])
        self.assertNotIn("mock_search", llm.requests[0].available_tools)

    def test_feishu_inbound_registration_resolves_current_target_and_daily_schedule(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="automation",
                    tool_payload={
                        "action": "register",
                        "automation_id": "github_digest_daily",
                        "name": "github_digest_daily",
                        "app_id": "default_app",
                        "agent_id": "default_agent",
                        "prompt_template": "",
                        "schedule_kind": "cron",
                        "schedule_expr": "30 23 * * *",
                        "timezone": "Asia/Shanghai",
                        "session_target": "isolated",
                        "delivery_channel": "feishu",
                        "delivery_target": "current_channel",
                        "skill_id": "github_trending_digest",
                    },
                ),
                LLMReply(final_text="ok"),
            ]
        )

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "ou_demo",
                    "conversation_id": "oc_current_chat",
                    "message_id": "om_user_1",
                    "body": "请每天 23:30 给我推送 GitHub 热门项目摘要。",
                },
            )

        self.assertEqual(response.status_code, 200)
        enabled = runtime.automation_store.list_enabled()
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].app_id, "example_assistant")
        self.assertEqual(enabled[0].agent_id, "assistant")
        self.assertEqual(enabled[0].schedule_kind, "daily")
        self.assertEqual(enabled[0].schedule_expr, "23:30")
        self.assertEqual(enabled[0].delivery_channel, "feishu")
        self.assertEqual(enabled[0].delivery_target, "oc_current_chat")

    def test_metrics_and_diagnostics_endpoints_exist(self) -> None:
        app = build_test_app()
        with TestClient(app) as client:
            message = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "compat-observe",
                    "message_id": "2",
                    "body": "hello",
                },
            ).json()
            session_id = message["session_id"]
            run_id = message["events"][-1]["run_id"]

            metrics = client.get("/metrics")
            session_diag = client.get(f"/diagnostics/session/{session_id}")
            run_diag = client.get(f"/diagnostics/run/{run_id}")
            queue_diag = client.get("/diagnostics/queue")
            runtime_diag = client.get("/diagnostics/runtime")
            automations = client.get("/automations")

        self.assertEqual(metrics.status_code, 200)
        self.assertIn("session_created_total", metrics.text)
        self.assertIn("provider_request_total", metrics.text)
        self.assertEqual(session_diag.status_code, 200)
        self.assertEqual(session_diag.json()["session_id"], session_id)
        self.assertEqual(run_diag.status_code, 200)
        self.assertEqual(run_diag.json()["run_id"], run_id)
        self.assertEqual(queue_diag.status_code, 200)
        self.assertEqual(queue_diag.json()["mode"], "conversation_lanes")
        self.assertIn("active_lane_count", queue_diag.json())
        self.assertIn("queued_lane_count", queue_diag.json())
        self.assertEqual(runtime_diag.status_code, 200)
        self.assertEqual(automations.status_code, 200)
        self.assertIn("items", automations.json())
        self.assertIn("default_agent_id", runtime_diag.json())
        self.assertIn("mcp_server_count", runtime_diag.json())
        self.assertIn("env_loaded", runtime_diag.json())
        self.assertIn("server", runtime_diag.json())
        self.assertIn("public_base_url", runtime_diag.json()["server"])
        self.assertIn("channels", runtime_diag.json())
        self.assertIn("self_improve", runtime_diag.json())
        self.assertIn("lanes", runtime_diag.json())
        self.assertIn("provider_retry_policy", runtime_diag.json())
        self.assertIn("active_lessons_count", runtime_diag.json()["self_improve"])
        self.assertIn("latest_candidate_status", runtime_diag.json()["self_improve"])
        self.assertIn("latest_accepted_lesson_summary", runtime_diag.json()["self_improve"])
        self.assertIn("latest_rejected_lesson_summary", runtime_diag.json()["self_improve"])
        self.assertIn("websocket", runtime_diag.json()["channels"]["feishu"])
        self.assertIn("mcp_servers", runtime_diag.json())
        self.assertGreaterEqual(len(runtime_diag.json()["mcp_servers"]), 1)
        configured_server = runtime_diag.json()["mcp_servers"][0]
        self.assertIn("server_id", configured_server)
        self.assertIn("source_layers", configured_server)

    def test_github_stdio_mcp_config_includes_required_stdio_subcommand(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        github_server = next(
            server
            for server in load_mcp_servers(str(repo_root / "config/mcp.toml"), str(repo_root / "mcps.json"))
            if server.server_id == "github"
        )

        self.assertEqual(github_server.transport, "stdio")
        self.assertGreaterEqual(len(github_server.args), 1)
        self.assertEqual(github_server.command, "docker")
        self.assertIn("stdio", github_server.args)
        self.assertEqual(github_server.args[-1], "stdio")
        self.assertTrue(
            any(layer in {"mcps.json"} for layer in github_server.source_layers)
        )

    def test_runtime_diagnostics_heal_stale_github_discovery_after_successful_call(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        server = MCPServerSpec(server_id="github", transport="stdio", backend_id="github", tools=[])
        runtime.mcp_servers = [server]
        runtime.mcp_discovery = {"github": {"state": "unavailable", "tool_count": 0, "error": "startup EOF"}}

        class RecoveringClient:
            def list_tools(self, server_id: str) -> list[MCPToolSpec]:
                return [MCPToolSpec(name="list_commits", description="List GitHub commits.")]

            def call_tool(self, server_id: str, tool_name: str, payload: dict) -> dict:
                return {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "result_text": (
                        '[{"sha":"0a1f49","html_url":"https://github.com/CloudWide851/easy-agent/commit/0a1f49",'
                        '"commit":{"message":"release ok","author":{"date":"2026-04-01T02:24:49Z"}}}]'
                    ),
                    "ok": True,
                    "is_error": False,
                }

        runtime.mcp_client = RecoveringClient()  # type: ignore[assignment]
        runtime.tool_registry.register(
            "mcp",
            lambda payload, runtime_state=runtime: __import__("marten_runtime.tools.builtins.mcp_tool", fromlist=["run_mcp_tool"]).run_mcp_tool(
                payload,
                runtime_state.mcp_servers,
                runtime_state.mcp_client,
                runtime_state.mcp_discovery,
            ),
            description=runtime.tool_registry._descriptors["mcp"].description,  # type: ignore[attr-defined]
        )
        runtime.runtime_loop.llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="mcp",
                    tool_payload={
                        "action": "call",
                        "server_id": "github",
                        "tool_name": "list_commits",
                        "arguments": {"owner": "CloudWide851", "repo": "easy-agent", "perPage": 1},
                    },
                ),
                LLMReply(final_text="最新提交已返回。"),
            ]
        )
        runtime.llm_client_factory.cache_client("default", runtime.runtime_loop.llm)
        runtime.llm_client_factory.cache_client("minimax_coding", runtime.runtime_loop.llm)

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "heal-stale-github-discovery",
                    "message_id": "heal-stale-github-discovery-1",
                    "body": "latest commit of CloudWide851/easy-agent",
                },
            )
            runtime_diag = client.get("/diagnostics/runtime")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][-1]["event_type"], "final")
        github_entry = next(item for item in runtime_diag.json()["mcp_servers"] if item["server_id"] == "github")
        self.assertEqual(github_entry["discovery"]["state"], "discovered")
        self.assertEqual(github_entry["discovery"]["tool_count"], 1)
        self.assertEqual(github_entry["discovery"]["error"], None)
        self.assertEqual(github_entry["tool_count"], 1)
        self.assertEqual(github_entry["tool_names"], ["list_commits"])

    def test_http_messages_return_provider_specific_error_event_instead_of_500_when_llm_fails(self) -> None:
        app = build_test_app()
        app.state.runtime.runtime_loop.llm = FailingLLMClient()

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "compat-llm-fail",
                    "message_id": "fail-1",
                    "body": "hello",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["events"][-1]["event_type"], "error")
        self.assertEqual(body["events"][-1]["payload"]["code"], "PROVIDER_TRANSPORT_ERROR")
        self.assertEqual(body["events"][-1]["payload"]["text"], "暂时没有生成可见回复，请重试。")

    def test_http_messages_return_provider_auth_error_when_provider_auth_fails(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = AuthFailingLLMClient()
        runtime.llm_client_factory.cache_client("default", runtime.runtime_loop.llm)
        runtime.llm_client_factory.cache_client("minimax_coding", runtime.runtime_loop.llm)

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "compat-auth-fail-plain",
                    "message_id": "auth-fail-plain-1",
                    "body": "hello",
                },
            )
            run_id = response.json()["events"][-1]["run_id"]
            run_diag = client.get(f"/diagnostics/run/{run_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][-1]["event_type"], "error")
        self.assertEqual(response.json()["events"][-1]["payload"]["code"], "PROVIDER_AUTH_ERROR")
        self.assertEqual(run_diag.status_code, 200)
        self.assertEqual(run_diag.json()["status"], "failed")
        self.assertEqual(run_diag.json()["llm_request_count"], 1)

    def test_http_messages_return_provider_auth_error_for_skill_load_when_provider_auth_fails(self) -> None:
        with TemporaryDirectory() as tmpdir:
            skills_root = Path(tmpdir) / "skills"
            skill_dir = skills_root / "example_time"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                (
                    "---\n"
                    "skill_id: example_time\n"
                    "name: Example Time\n"
                    "description: Return current time guidance\n"
                    "enabled: true\n"
                    "agents: [assistant]\n"
                    "channels: [http]\n"
                    "---\n"
                    "Use the time tool when the user asks for the current time.\n"
                ),
                encoding="utf-8",
            )
            app = build_test_app()
            runtime = app.state.runtime
            runtime.runtime_loop.llm = AuthFailingLLMClient()
            runtime.llm_client_factory.cache_client("default", runtime.runtime_loop.llm)
            runtime.llm_client_factory.cache_client("minimax_coding", runtime.runtime_loop.llm)
            runtime.skill_service = SkillService([str(skills_root)])

            with TestClient(app) as client:
                response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "compat-auth-fail-skill",
                        "message_id": "auth-fail-skill-1",
                        "body": "请读取 example_time 这个 skill 并简单概括它的用途",
                    },
                )
                run_id = response.json()["events"][-1]["run_id"]
                run_diag = client.get(f"/diagnostics/run/{run_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][-1]["event_type"], "error")
        self.assertEqual(response.json()["events"][-1]["payload"]["code"], "PROVIDER_AUTH_ERROR")
        self.assertEqual(run_diag.status_code, 200)
        self.assertEqual(run_diag.json()["status"], "failed")
        self.assertEqual(run_diag.json()["llm_request_count"], 1)

    def test_http_messages_return_provider_auth_error_for_explicit_github_commit_query_when_provider_auth_fails(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = AuthFailingLLMClient()
        runtime.llm_client_factory.cache_client("default", runtime.runtime_loop.llm)
        runtime.llm_client_factory.cache_client("minimax_coding", runtime.runtime_loop.llm)
        runtime.tool_registry.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"},"message":"chore(release): 发布0.3.3版本"}}]',
                "ok": True,
                "is_error": False,
            },
        )

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "compat-auth-fail-commit",
                    "message_id": "auth-fail-commit-1",
                    "body": "GitHub - CloudWide851/easy-agent 这个github仓库最近一次提交是什么时候",
                },
            )
            run_id = response.json()["events"][-1]["run_id"]
            run_diag = client.get(f"/diagnostics/run/{run_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][-1]["event_type"], "error")
        self.assertEqual(response.json()["events"][-1]["payload"]["code"], "PROVIDER_AUTH_ERROR")
        self.assertEqual(run_diag.status_code, 200)
        self.assertEqual(run_diag.json()["status"], "failed")
        self.assertEqual(run_diag.json()["llm_request_count"], 1)
        self.assertEqual(run_diag.json()["tool_calls"], [])

    def test_http_messages_return_provider_auth_error_for_english_explicit_github_commit_query_when_provider_auth_fails(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = AuthFailingLLMClient()
        runtime.llm_client_factory.cache_client("default", runtime.runtime_loop.llm)
        runtime.llm_client_factory.cache_client("minimax_coding", runtime.runtime_loop.llm)
        runtime.tool_registry.register(
            "mcp",
            lambda payload: {
                "action": "call",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "arguments": payload["arguments"],
                "result_text": '[{"sha":"abc","commit":{"author":{"date":"2026-04-01T02:24:49Z"},"message":"chore(release): 发布0.3.3版本"}}]',
                "ok": True,
                "is_error": False,
            },
        )

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "compat-auth-fail-commit-en",
                    "message_id": "auth-fail-commit-en-1",
                    "body": "latest commit of CloudWide851/easy-agent",
                },
            )
            run_id = response.json()["events"][-1]["run_id"]
            run_diag = client.get(f"/diagnostics/run/{run_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][-1]["event_type"], "error")
        self.assertEqual(response.json()["events"][-1]["payload"]["code"], "PROVIDER_AUTH_ERROR")
        self.assertEqual(run_diag.status_code, 200)
        self.assertEqual(run_diag.json()["status"], "failed")
        self.assertEqual(run_diag.json()["llm_request_count"], 1)
        self.assertEqual(run_diag.json()["tool_calls"], [])

    def test_http_overlap_is_queued_and_keeps_normal_response_contract(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        first_started = threading.Event()
        release_first = threading.Event()
        seen_messages: list[str] = []

        def blocking_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            seen_messages.append(message)
            if len(seen_messages) == 1:
                first_started.set()
                release_first.wait(timeout=2)
            run_id = f"run_{len(seen_messages)}"
            record = runtime.run_history.start(
                session_id=session_id,
                trace_id=trace_id or "trace_missing",
                config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
                bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
            )
            original_run_id = record.run_id
            record.run_id = run_id
            runtime.run_history._items[run_id] = runtime.run_history._items.pop(original_run_id)
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id=run_id,
                    event_id=f"evt_{run_id}_progress",
                    event_type="progress",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "running"},
                    created_at=datetime.now(timezone.utc),
                ),
                OutboundEvent(
                    session_id=session_id,
                    run_id=run_id,
                    event_id=f"evt_{run_id}_final",
                    event_type="final",
                    sequence=2,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": message},
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        runtime.runtime_loop.run = blocking_run  # type: ignore[method-assign]
        responses: dict[str, object] = {}

        with TestClient(app) as client:
            def send(name: str, body: str) -> None:
                responses[name] = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "compat-queue",
                        "message_id": f"{name}-1",
                        "body": body,
                    },
                )

            first_thread = threading.Thread(target=send, args=("first", "hello-1"))
            second_thread = threading.Thread(target=send, args=("second", "hello-2"))
            first_thread.start()
            self.assertTrue(first_started.wait(timeout=2))
            second_thread.start()
            deadline = time.time() + 2
            while runtime.lane_manager.stats()["queued_lane_count"] != 1 and time.time() < deadline:
                time.sleep(0.01)
            release_first.set()
            first_thread.join(timeout=2)
            second_thread.join(timeout=2)

        first = responses["first"]
        second = responses["second"]
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertIn("session_id", first.json())
        self.assertIn("session_id", second.json())
        self.assertEqual(seen_messages, ["hello-1", "hello-2"])
        self.assertEqual(first.json()["events"][-1]["payload"]["text"], "hello-1")
        self.assertEqual(second.json()["events"][-1]["payload"]["text"], "hello-2")
        second_run = runtime.run_history.get("run_2")
        self.assertEqual(second_run.queue.queue_depth_at_enqueue, 2)
        self.assertTrue(second_run.queue.waited_in_lane)

    def test_automations_endpoint_includes_paused_jobs(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.automation_store.save(
            AutomationJob(
                automation_id="paused_hot",
                name="Paused GitHub Hot Repos",
                app_id="example_assistant",
                agent_id="assistant",
                prompt_template="hello from paused automation",
                schedule_kind="daily",
                schedule_expr="21:00",
                timezone="Asia/Shanghai",
                session_target="isolated",
                delivery_channel="feishu",
                delivery_target="oc_test_chat",
                skill_id="github_trending_digest",
                enabled=False,
            )
        )

        with TestClient(app) as client:
            response = client.get("/automations")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertFalse(body["items"][0]["enabled"])

    def test_manual_automation_trigger_runs_through_runtime_path(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        delivered: list[dict[str, object]] = []
        expected_scheduled_for = (
            datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        )

        class _RecordingDeliveryClient:
            def deliver(self, payload):
                delivered.append(payload.model_dump())
                return {"ok": True, "action": "send", "message_id": "om_test"}

        runtime.feishu_delivery = _RecordingDeliveryClient()
        runtime.automation_store.save(
            AutomationJob(
                automation_id="daily_hot",
                name="Daily GitHub Hot Repos",
                app_id="example_assistant",
                agent_id="assistant",
                prompt_template="hello from automation",
                schedule_kind="daily",
                schedule_expr="09:30",
                timezone="Asia/Shanghai",
                session_target="isolated",
                delivery_channel="feishu",
                delivery_target="oc_test_chat",
                skill_id="github_trending_digest",
            )
        )

        with TestClient(app) as client:
            response = client.post("/automations/daily_hot/trigger")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(body["automation_id"], "daily_hot")
        self.assertEqual(body["delivery_target"], "oc_test_chat")
        self.assertEqual(body["events"][-1]["event_type"], "final")
        self.assertEqual(body["events"][-1]["payload"]["text"], "hello from automation")
        self.assertEqual(body["scheduled_for"], expected_scheduled_for)
        self.assertEqual([item["event_type"] for item in delivered], ["progress", "final"])
        self.assertEqual(delivered[-1]["chat_id"], "oc_test_chat")
        self.assertEqual(
            delivered[-1]["dedupe_key"],
            f"feishu:oc_test_chat:{expected_scheduled_for}",
        )

    def test_manual_automation_trigger_without_skill_id_does_not_500(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.automation_store.save(
            AutomationJob(
                automation_id="plain_delivery",
                name="plain_delivery",
                app_id="example_assistant",
                agent_id="assistant",
                prompt_template="请只回复：实时链路验证通过。",
                schedule_kind="daily",
                schedule_expr="23:59",
                timezone="Asia/Shanghai",
                session_target="isolated",
                delivery_channel="http",
                delivery_target="internal",
                skill_id="",
                enabled=True,
                internal=False,
            )
        )
        runtime.runtime_loop.llm = ScriptedLLMClient([LLMReply(final_text="实时链路验证通过。")])

        with TestClient(app) as client:
            response = client.post("/automations/plain_delivery/trigger")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][-1]["payload"]["text"], "实时链路验证通过。")

    def test_manual_automation_trigger_for_legacy_github_digest_does_not_require_skill_file(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.automation_store.save(
            AutomationJob(
                automation_id="legacy_hot",
                name="legacy_hot",
                app_id="example_assistant",
                agent_id="assistant",
                prompt_template="请只回复：兼容触发通过。",
                schedule_kind="daily",
                schedule_expr="23:59",
                timezone="Asia/Shanghai",
                session_target="isolated",
                delivery_channel="http",
                delivery_target="internal",
                skill_id="github_trending_digest",
                enabled=True,
                internal=False,
            )
        )
        runtime.runtime_loop.llm = ScriptedLLMClient([LLMReply(final_text="兼容触发通过。")])
        runtime.skill_service.build_runtime = lambda **_: SkillRuntimeView(  # type: ignore[method-assign]
            visible_skills=[],
            snapshot=SkillSnapshot(skill_snapshot_id="skill_empty"),
            skill_heads_text=None,
            always_on_text=None,
        )
        runtime.skill_service.load_skill = lambda skill_id: (_ for _ in ()).throw(KeyError(skill_id))  # type: ignore[method-assign]

        with TestClient(app) as client:
            response = client.post("/automations/legacy_hot/trigger")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][-1]["payload"]["text"], "兼容触发通过。")

    def test_http_messages_can_query_and_delete_self_improve_candidates_through_runtime_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            app = build_test_app()
            runtime = app.state.runtime
            isolated_store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            runtime.self_improve_store = isolated_store
            runtime.runtime_loop.self_improve_recorder = SelfImproveRecorder(isolated_store)
            runtime.self_improve_service = SelfImproveService(
                isolated_store,
                lessons_path=Path(tmpdir) / "SYSTEM_LESSONS.md",
                judge=make_default_judge(
                    runtime.runtime_loop.llm,
                    app_id="example_assistant",
                    agent_id="assistant",
                ),
            )
            runtime.self_improve_store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_1",
                    agent_id="assistant",
                    source_fingerprints=["fp_one", "fp_one"],
                    candidate_text="候选规则一",
                    rationale="candidate rationale",
                    status="pending",
                    score=0.9,
                )
            )
            runtime.self_improve_store.save_lesson(
                SystemLesson(
                    lesson_id="lesson_1",
                    agent_id="assistant",
                    topic_key="provider_timeout",
                    lesson_text="保留的 active lesson",
                    source_fingerprints=["fp_timeout"],
                    active=True,
                )
            )
            runtime.runtime_loop.llm = ScriptedLLMClient(
                [
                    LLMReply(
                        tool_name="self_improve",
                        tool_payload={"action": "list_candidates", "agent_id": "assistant"},
                    ),
                    LLMReply(final_text="当前有 1 条候选规则。"),
                    LLMReply(
                        tool_name="self_improve",
                        tool_payload={"action": "delete_candidate", "candidate_id": "cand_1"},
                    ),
                    LLMReply(final_text="已删除候选规则 cand_1。"),
                ]
            )

            with TestClient(app) as client:
                query_response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "self-improve-query",
                        "message_id": "msg_query",
                        "body": "帮我看看最近有哪些候选规则",
                    },
                )
                delete_response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "self-improve-delete",
                        "message_id": "msg_delete",
                        "body": "删除候选规则 cand_1",
                    },
                )

            self.assertEqual(query_response.status_code, 200)
            self.assertEqual(delete_response.status_code, 200)
            self.assertEqual(query_response.json()["events"][-1]["payload"]["text"], "当前有 1 条候选规则。")
            self.assertEqual(delete_response.json()["events"][-1]["payload"]["text"], "已删除候选规则 cand_1。")
            self.assertEqual(runtime.self_improve_store.list_candidates(agent_id="assistant", limit=10), [])
            lessons = runtime.self_improve_store.list_active_lessons(agent_id="assistant")
            self.assertEqual(len(lessons), 1)
            self.assertEqual(lessons[0].lesson_id, "lesson_1")

    def test_run_diagnostics_expose_tool_calls_for_registration(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="automation",
                    tool_payload={
                        "action": "register",
                        "automation_id": "daily_hot",
                        "name": "Daily GitHub Hot Repos",
                        "app_id": "example_assistant",
                        "agent_id": "assistant",
                        "prompt_template": "Summarize today's hot repositories.",
                        "schedule_kind": "daily",
                        "schedule_expr": "09:30",
                        "timezone": "Asia/Shanghai",
                        "session_target": "isolated",
                        "delivery_channel": "feishu",
                        "delivery_target": "oc_test_chat",
                        "skill_id": "github_trending_digest",
                    },
                ),
                LLMReply(final_text="ok"),
            ]
        )

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "register-audit",
                    "message_id": "tool-1",
                    "body": "请创建一个每日 GitHub 热门项目任务。",
                },
            )
            run_id = response.json()["events"][-1]["run_id"]
            run_diag = client.get(f"/diagnostics/run/{run_id}")

        self.assertEqual(run_diag.status_code, 200)
        body = run_diag.json()
        self.assertEqual(body["llm_request_count"], 2)
        self.assertEqual(len(body["tool_calls"]), 1)
        self.assertEqual(body["tool_calls"][0]["tool_name"], "automation")
        self.assertIn("timings", body)
        self.assertIn("llm_first_ms", body["timings"])
        self.assertIn("tool_ms", body["timings"])
        self.assertIn("llm_second_ms", body["timings"])
        self.assertIn("total_ms", body["timings"])

    def test_runtime_diagnostics_expose_feishu_channel_hardening_signals(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        receipts = InMemoryReceiptStore()
        receipts.claim(
            channel_id="feishu",
            dedupe_key="dedupe_diag",
            trace_id="trace_diag",
            conversation_id="chat_diag",
            message_id="evt_diag",
        )
        receipts.claim(
            channel_id="feishu",
            dedupe_key="dedupe_diag",
            trace_id="trace_diag_2",
            conversation_id="chat_diag",
            message_id="evt_diag",
        )
        sessions = InMemoryFeishuDeliverySessionStore()
        sessions.start_or_get(
            channel_id="feishu",
            conversation_id="chat_diag",
            run_id="run_diag",
            trace_id="trace_diag",
        )
        dead_letters = InMemoryDeadLetterQueue()
        dead_letters.record(
            channel_id="feishu",
            conversation_id="chat_diag",
            payload=FeishuDeliveryPayload(
                chat_id="chat_diag",
                event_type="error",
                event_id="evt_dead_diag",
                run_id="run_diag",
                trace_id="trace_diag",
                sequence=7,
                text="failed",
            ),
            attempts=3,
            error="boom",
        )
        delivery = FeishuDeliveryClient(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            session_store=sessions,
            retry_policy=DeliveryRetryPolicy(
                progress_max_retries=2,
                final_max_retries=5,
                error_max_retries=5,
                base_backoff_seconds=0.1,
                max_backoff_seconds=0.5,
            ),
            dead_letter_queue=dead_letters,
        )

        runtime.feishu_receipts = receipts
        runtime.feishu_delivery = delivery
        with TestClient(app) as client:
            runtime_diag = client.get("/diagnostics/runtime")

        self.assertEqual(runtime_diag.status_code, 200)
        feishu = runtime_diag.json()["channels"]["feishu"]
        self.assertEqual(feishu["connection_mode"], "websocket")
        self.assertIn("receipt_store", feishu)
        self.assertEqual(feishu["receipt_store"]["duplicate_total"], 1)
        self.assertEqual(feishu["receipt_store"]["last_duplicate"]["trace_id"], "trace_diag")
        self.assertIn("delivery_sessions", feishu)
        self.assertEqual(feishu["delivery_sessions"]["active_count"], 1)
        self.assertIn("dead_letter", feishu)
        self.assertEqual(feishu["dead_letter"]["count"], 1)
        self.assertIn("retry_policy", feishu)
        self.assertEqual(feishu["retry_policy"]["progress_max_retries"], 2)
        self.assertIn("websocket", feishu)
        self.assertIn("last_runtime_trace_id", feishu["websocket"])
        self.assertIsNone(feishu["websocket"]["last_runtime_trace_id"])
        self.assertIsNone(feishu["websocket"]["last_session_id"])
        self.assertIsNone(feishu["websocket"]["last_run_id"])

    def test_feishu_channel_messages_inject_feishu_always_on_skill_but_http_does_not(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = ScriptedLLMClient(
            [
                LLMReply(final_text="feishu ok"),
                LLMReply(final_text="http ok"),
            ]
        )

        with TestClient(app) as client:
            feishu_response = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "feishu-skill-check",
                    "message_id": "msg-feishu-skill",
                    "body": "请简短回复我",
                },
            )
            http_response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "http-skill-check",
                    "message_id": "msg-http-skill",
                    "body": "请简短回复我",
                },
            )

        self.assertEqual(feishu_response.status_code, 200)
        self.assertEqual(http_response.status_code, 200)
        self.assertEqual(runtime.runtime_loop.llm.requests[0].always_on_skill_text is not None, True)
        self.assertIn("Avoid Markdown tables", runtime.runtime_loop.llm.requests[0].always_on_skill_text or "")
        self.assertEqual(runtime.runtime_loop.llm.requests[1].always_on_skill_text, None)
        self.assertIn("feishu_card", runtime.runtime_loop.llm.requests[0].channel_protocol_instruction_text or "")
        self.assertIsNone(runtime.runtime_loop.llm.requests[1].channel_protocol_instruction_text)

    def test_runtime_diagnostics_redact_feishu_websocket_endpoint_secrets(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.feishu_socket_service.state.endpoint_url = (
            "wss://msg-frontier.feishu.cn/ws/v2"
            "?device_id=123"
            "&access_key=secret-access"
            "&service_id=456"
            "&ticket=secret-ticket"
        )
        runtime.feishu_socket_service.state.connection_id = "123"
        runtime.feishu_socket_service.state.service_id = "456"
        with TestClient(app) as client:
            runtime_diag = client.get("/diagnostics/runtime")

        self.assertEqual(runtime_diag.status_code, 200)
        websocket = runtime_diag.json()["channels"]["feishu"]["websocket"]
        self.assertEqual(
            websocket["endpoint_url"],
            "wss://msg-frontier.feishu.cn/ws/v2?device_id=123&access_key=REDACTED&service_id=456&ticket=REDACTED",
        )

    def test_runtime_diagnostics_reports_effective_request_server_surface(self) -> None:
        app = build_test_app()

        with TestClient(app, base_url="http://127.0.0.1:8001") as client:
            runtime_diag = client.get("/diagnostics/runtime")

        self.assertEqual(runtime_diag.status_code, 200)
        server = runtime_diag.json()["server"]
        self.assertEqual(server["host"], "127.0.0.1")
        self.assertEqual(server["port"], 8001)
        self.assertEqual(server["public_base_url"], "http://127.0.0.1:8001")
        self.assertEqual(server["configured_port"], 8000)
        self.assertEqual(server["configured_public_base_url"], "http://127.0.0.1:8000")


if __name__ == "__main__":
    unittest.main()
