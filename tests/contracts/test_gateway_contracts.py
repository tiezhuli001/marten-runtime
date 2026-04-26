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
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.self_improve.models import LessonCandidate, SystemLesson
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.self_improve.service import SelfImproveService, make_default_judge
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.session.compaction import compact_context
from marten_runtime.skills.service import SkillRuntimeView, SkillService
from marten_runtime.skills.snapshot import SkillSnapshot
from tests.http_app_support import build_test_app
from tests.support.scripted_llm import AuthFailingLLMClient, FailingLLMClient, OverloadedLLMClient


class GatewayContractTests(unittest.TestCase):
    FAMILY_TOOLS = [
        "automation",
        "cancel_subagent",
        "mcp",
        "memory",
        "runtime",
        "self_improve",
        "session",
        "skill",
        "spawn_subagent",
        "time",
    ]

    def _assert_http_turn_keeps_family_tool_surface(
        self,
        *,
        conversation_id: str,
        message_id: str,
        body: str,
        final_text: str = "ok",
    ) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        llm = ScriptedLLMClient([LLMReply(final_text=final_text)])
        runtime.runtime_loop.llm = llm

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "body": body,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(llm.requests[0].available_tools, self.FAMILY_TOOLS)

    def _assert_http_provider_auth_error_for_message(
        self,
        *,
        conversation_id: str,
        message_id: str,
        body: str,
    ) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = AuthFailingLLMClient()
        runtime.llm_client_factory.cache_client("openai_gpt5", runtime.runtime_loop.llm)
        runtime.llm_client_factory.cache_client("minimax_m25", runtime.runtime_loop.llm)
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
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "body": body,
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
        self.assertIn("active_session_id", message)
        self.assertEqual(message["active_session_id"], message["session_id"])
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
        runtime.llm_client_factory.cache_client("openai_gpt5", llm)
        runtime.llm_client_factory.cache_client("minimax_m25", llm)

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
        self.assertIn("当前会话下一次请求预计带入", final_text)
        self.assertEqual(len(llm.requests), 1)
        run_id = response.json()["events"][-1]["run_id"]
        tool_result = runtime.run_history.get(run_id).tool_calls[0]["tool_result"]
        self.assertTrue(tool_result["ok"])
        self.assertEqual(tool_result["action"], "context_status")
        self.assertEqual(tool_result["model_profile"], "openai_gpt5")
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

    def test_http_turns_keep_only_family_tool_surface(self) -> None:
        cases = [
            {
                "conversation_id": "plain-chat",
                "message_id": "plain-1",
                "body": "你好啊",
                "final_text": "你好",
            },
            {
                "conversation_id": "github-schedule",
                "message_id": "github-1",
                "body": "每天晚上11点25给我推送github热榜",
            },
            {
                "conversation_id": "search-turn",
                "message_id": "search-1",
                "body": "search release notes",
            },
        ]

        for case in cases:
            with self.subTest(body=case["body"]):
                self._assert_http_turn_keeps_family_tool_surface(**case)

    def test_http_messages_return_provider_specific_error_event_instead_of_500_when_llm_fails(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = FailingLLMClient()
        runtime.llm_client_factory.cache_client("openai_gpt5", runtime.runtime_loop.llm)
        runtime.llm_client_factory.cache_client("kimi_k2", runtime.runtime_loop.llm)
        runtime.llm_client_factory.cache_client("minimax_m25", runtime.runtime_loop.llm)

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

    def test_http_messages_return_busy_text_when_provider_is_overloaded(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = OverloadedLLMClient()
        runtime.llm_client_factory.cache_client("openai_gpt5", runtime.runtime_loop.llm)
        runtime.llm_client_factory.cache_client("kimi_k2", runtime.runtime_loop.llm)
        runtime.llm_client_factory.cache_client("minimax_m25", runtime.runtime_loop.llm)

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "compat-overloaded",
                    "message_id": "overloaded-1",
                    "body": "hello",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["events"][-1]["event_type"], "error")
        self.assertEqual(body["events"][-1]["payload"]["code"], "PROVIDER_UPSTREAM_UNAVAILABLE")
        self.assertEqual(body["events"][-1]["payload"]["text"], "当前模型服务繁忙，请稍后重试。")

    def test_http_messages_return_provider_auth_error_when_provider_auth_fails(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = AuthFailingLLMClient()
        runtime.llm_client_factory.cache_client("openai_gpt5", runtime.runtime_loop.llm)
        runtime.llm_client_factory.cache_client("minimax_m25", runtime.runtime_loop.llm)

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
                    "agents: [main]\n"
                    "channels: [http]\n"
                    "---\n"
                    "Use the time tool when the user asks for the current time.\n"
                ),
                encoding="utf-8",
            )
            app = build_test_app()
            runtime = app.state.runtime
            runtime.runtime_loop.llm = AuthFailingLLMClient()
            runtime.llm_client_factory.cache_client("openai_gpt5", runtime.runtime_loop.llm)
            runtime.llm_client_factory.cache_client("minimax_m25", runtime.runtime_loop.llm)
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

    def test_http_messages_return_provider_auth_error_for_explicit_github_commit_queries(self) -> None:
        cases = [
            {
                "conversation_id": "compat-auth-fail-commit",
                "message_id": "auth-fail-commit-1",
                "body": "GitHub - CloudWide851/easy-agent 这个github仓库最近一次提交是什么时候",
            },
            {
                "conversation_id": "compat-auth-fail-commit-en",
                "message_id": "auth-fail-commit-en-1",
                "body": "latest commit of CloudWide851/easy-agent",
            },
        ]

        for case in cases:
            with self.subTest(body=case["body"]):
                self._assert_http_provider_auth_error_for_message(**case)

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
                app_id="main_agent",
                agent_id="main",
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
                app_id="main_agent",
                agent_id="main",
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

    def test_manual_automation_trigger_preserves_durable_text_and_card_for_feishu_delivery(
        self,
    ) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        delivered: list[dict[str, object]] = []

        class _RecordingDeliveryClient:
            def deliver(self, payload):
                delivered.append(payload.model_dump(mode="json"))
                return {"ok": True, "action": "send", "message_id": "om_structured"}

        runtime.feishu_delivery = _RecordingDeliveryClient()
        runtime.automation_store.save(
            AutomationJob(
                automation_id="daily_structured",
                name="daily_structured",
                app_id="main_agent",
                agent_id="main",
                prompt_template="hello from structured automation",
                schedule_kind="daily",
                schedule_expr="09:30",
                timezone="Asia/Shanghai",
                session_target="isolated",
                delivery_channel="feishu",
                delivery_target="oc_structured_chat",
                skill_id="github_trending_digest",
            )
        )

        def fake_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_structured_automation",
                    event_id="evt_structured_automation_progress",
                    event_type="progress",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "running"},
                    created_at=datetime.now(timezone.utc),
                ),
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_structured_automation",
                    event_id="evt_structured_automation_final",
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

        runtime.runtime_loop.run = fake_run  # type: ignore[method-assign]

        with TestClient(app) as client:
            response = client.post("/automations/daily_structured/trigger")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        final_event = body["events"][-1]
        expected_durable_text = "检查完成。\n\n共 2 项\n\n- builtin 正常\n- mcp 正常"
        self.assertEqual(final_event["payload"]["text"], expected_durable_text)
        self.assertEqual(final_event["payload"]["card"]["header"]["title"]["content"], "检查结果")
        self.assertEqual(delivered[-1]["text"], expected_durable_text)
        self.assertEqual(delivered[-1]["card"]["header"]["title"]["content"], "检查结果")

    def test_manual_automation_trigger_without_skill_id_does_not_500(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.automation_store.save(
            AutomationJob(
                automation_id="plain_delivery",
                name="plain_delivery",
                app_id="main_agent",
                agent_id="main",
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

    def test_manual_automation_trigger_for_canonical_github_digest_does_not_require_skill_file(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        runtime.automation_store.save(
            AutomationJob(
                automation_id="legacy_hot",
                name="legacy_hot",
                app_id="main_agent",
                agent_id="main",
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
                    app_id="main_agent",
                    agent_id="main",
                ),
            )
            runtime.self_improve_store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_1",
                    agent_id="main",
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
                    agent_id="main",
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
                        tool_payload={"action": "list_candidates", "agent_id": "main"},
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
            self.assertEqual(runtime.self_improve_store.list_candidates(agent_id="main", limit=10), [])
            lessons = runtime.self_improve_store.list_active_lessons(agent_id="main")
            self.assertEqual(len(lessons), 1)
            self.assertEqual(lessons[0].lesson_id, "lesson_1")

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
