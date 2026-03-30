import threading
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from marten_runtime.automation.models import AutomationJob
from marten_runtime.channels.dead_letter import InMemoryDeadLetterQueue
from marten_runtime.channels.delivery_retry import DeliveryRetryPolicy
from marten_runtime.channels.feishu.delivery import FeishuDeliveryClient, FeishuDeliveryPayload
from marten_runtime.channels.feishu.delivery_session import InMemoryFeishuDeliverySessionStore
from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.session.compaction import compact_context
from tests.http_app_support import build_test_app


class FailingLLMClient:
    provider_name = "failing"
    model_name = "failing-local"

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("provider_transport_error:connection reset")


class ContractCompatibilityTests(unittest.TestCase):
    def test_runtime_bootstrap_registers_automation_tool(self) -> None:
        app = build_test_app()

        self.assertIn("register_automation", app.state.runtime.tool_registry.list())
        self.assertIn("list_automations", app.state.runtime.tool_registry.list())
        self.assertIn("update_automation", app.state.runtime.tool_registry.list())
        self.assertIn("delete_automation", app.state.runtime.tool_registry.list())
        self.assertIn("pause_automation", app.state.runtime.tool_registry.list())
        self.assertIn("resume_automation", app.state.runtime.tool_registry.list())

    def test_default_assistant_agent_can_use_register_automation(self) -> None:
        app = build_test_app()

        assistant = app.state.runtime.default_agent

        self.assertIn("register_automation", assistant.allowed_tools)
        self.assertIn("list_automations", assistant.allowed_tools)
        self.assertIn("update_automation", assistant.allowed_tools)
        self.assertIn("delete_automation", assistant.allowed_tools)
        self.assertIn("pause_automation", assistant.allowed_tools)
        self.assertIn("resume_automation", assistant.allowed_tools)

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
            created_at=compact_context("sess_1", "goal", 10).model_fields["snapshot_id"].default if False else __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )

        self.assertIn("session_id", message)
        self.assertIn("events", message)
        self.assertEqual(event.trace_id, "trace_1")
        snapshot = compact_context("sess_1", "goal", 10)
        self.assertEqual(snapshot.session_id, "sess_1")
        self.assertTrue(hasattr(snapshot, "manifest_id"))

    def test_feishu_inbound_registration_resolves_current_target_and_daily_schedule(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="register_automation",
                    tool_payload={
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
                        "skill_id": "github_hot_repos_digest",
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
        self.assertIn("lanes", runtime_diag.json())
        self.assertIn("provider_retry_policy", runtime_diag.json())
        self.assertIn("websocket", runtime_diag.json()["channels"]["feishu"])
        self.assertIn("mcp_servers", runtime_diag.json())
        mock_search = next(
            item for item in runtime_diag.json()["mcp_servers"] if item["server_id"] == "mock-search"
        )
        self.assertIn("source_layers", mock_search)
        self.assertTrue(
            any(layer in {"config/mcp.toml", "config/mcp.example.toml"} for layer in mock_search["source_layers"])
        )

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
                skill_id="github_hot_repos_digest",
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
                skill_id="github_hot_repos_digest",
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
        self.assertEqual([item["event_type"] for item in delivered], ["progress", "final"])
        self.assertEqual(delivered[-1]["chat_id"], "oc_test_chat")
        self.assertEqual(delivered[-1]["dedupe_key"], "feishu:oc_test_chat:2026-03-30")

    def test_run_diagnostics_expose_tool_calls_for_registration(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="register_automation",
                    tool_payload={
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
                        "skill_id": "github_hot_repos_digest",
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
        self.assertEqual(body["tool_calls"][0]["tool_name"], "register_automation")

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
        self.assertIsNone(feishu["websocket"]["last_session_id"])
        self.assertIsNone(feishu["websocket"]["last_run_id"])

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


if __name__ == "__main__":
    unittest.main()
