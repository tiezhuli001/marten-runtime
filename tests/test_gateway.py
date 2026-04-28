import threading
import time
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from marten_runtime.gateway.dedupe import build_dedupe_key
from marten_runtime.gateway.ingress import ingest_message
from marten_runtime.gateway.models import InboundEnvelope
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.session.models import SessionMessage
from tests.http_app_support import build_test_app


class GatewayTests(unittest.TestCase):
    def test_build_dedupe_key_is_stable(self) -> None:
        key_a = build_dedupe_key(
            channel_id="http",
            conversation_id="conv-1",
            user_id="user-1",
            message_id="msg-1",
        )
        key_b = build_dedupe_key(
            channel_id="http",
            conversation_id="conv-1",
            user_id="user-1",
            message_id="msg-1",
        )

        self.assertEqual(key_a, key_b)
        self.assertGreaterEqual(len(key_a), 8)

    def test_ingest_message_generates_trace_and_envelope(self) -> None:
        envelope = ingest_message(
            {
                "channel_id": "http",
                "user_id": "demo",
                "conversation_id": "conv-1",
                "message_id": "msg-1",
                "body": "hello",
            }
        )

        self.assertIsInstance(envelope, InboundEnvelope)
        self.assertEqual(envelope.channel_id, "http")
        self.assertEqual(envelope.body, "hello")
        self.assertTrue(envelope.trace_id.startswith("trace_"))
        self.assertGreaterEqual(len(envelope.dedupe_key), 8)

    def test_inbound_envelope_requires_trace_and_dedupe(self) -> None:
        envelope = InboundEnvelope(
            channel_id="http",
            user_id="demo",
            conversation_id="conv-1",
            message_id="msg-1",
            body="hello",
            received_at=datetime.now(timezone.utc),
            dedupe_key="dedupe_1",
            trace_id="trace_1",
        )

        self.assertEqual(envelope.trace_id, "trace_1")
        self.assertEqual(envelope.dedupe_key, "dedupe_1")

    def test_http_sessions_endpoint_returns_session_id(self) -> None:
        with TestClient(build_test_app()) as client:
            response = client.post("/sessions", json={})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("session_id", payload)
        self.assertTrue(payload["session_id"].startswith("sess_"))

    def test_http_messages_endpoint_returns_progress_and_final_events(self) -> None:
        with TestClient(build_test_app()) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-http",
                    "message_id": "msg-http-1",
                    "body": "hello",
                },
            )
            run_id = response.json()["events"][-1]["run_id"]
            run_diag = client.get(f"/diagnostics/run/{run_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(run_diag.status_code, 200)
        payload = response.json()
        run_payload = run_diag.json()
        self.assertIn("session_id", payload)
        self.assertEqual(len(payload["events"]), 2)
        self.assertEqual(payload["events"][0]["event_type"], "progress")
        self.assertEqual(payload["events"][1]["event_type"], "final")
        self.assertEqual(payload["events"][0]["run_id"], payload["events"][1]["run_id"])
        self.assertEqual(payload["events"][0]["trace_id"], payload["events"][1]["trace_id"])
        self.assertEqual(payload["result"], payload["events"][1]["payload"]["text"])
        self.assertEqual(payload["final_text"], payload["events"][1]["payload"]["text"])
        self.assertEqual(payload["text"], payload["events"][1]["payload"]["text"])
        self.assertIsNone(payload["card"])
        self.assertIsNone(payload["error_code"])
        self.assertEqual(run_payload["attempted_profiles"], ["openai_gpt5"])
        self.assertEqual(run_payload["attempted_providers"], ["test-demo"])
        self.assertEqual(run_payload["provider_ref"], "test-demo")
        self.assertEqual(run_payload["final_provider_ref"], "test-demo")
        self.assertEqual(run_payload["finalization"]["assessment"], "accepted")
        self.assertEqual(run_payload["finalization"]["request_kind"], "interactive")
        self.assertEqual(run_payload["finalization"]["required_evidence_count"], 0)
        self.assertFalse(run_payload["finalization"]["retry_triggered"])

    def test_http_messages_endpoint_isolates_same_conversation_by_user(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        scripted = ScriptedLLMClient(
            [
                LLMReply(final_text="alice answer"),
                LLMReply(final_text="bob answer"),
            ]
        )
        runtime.runtime_loop.llm = scripted
        runtime.llm_client_factory.cache_client("openai_gpt5", scripted)
        runtime.llm_client_factory.cache_client("minimax_m25", scripted)
        runtime.llm_client_factory.cache_client("kimi_k2", scripted)

        with TestClient(app) as client:
            alice = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "alice",
                    "conversation_id": "shared-conv",
                    "message_id": "msg-shared-alice",
                    "body": "alice secret",
                },
            )
            bob = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "bob",
                    "conversation_id": "shared-conv",
                    "message_id": "msg-shared-bob",
                    "body": "bob asks",
                },
            )

        self.assertEqual(alice.status_code, 200)
        self.assertEqual(bob.status_code, 200)
        self.assertEqual(len(scripted.requests), 2)
        bob_history = [
            item.content for item in scripted.requests[1].conversation_messages
        ]
        self.assertNotIn("alice secret", bob_history)
        self.assertNotIn("alice answer", bob_history)
        alice_session = runtime.session_store.get(alice.json()["session_id"])
        bob_session = runtime.session_store.get(bob.json()["session_id"])
        self.assertNotEqual(alice_session.session_id, bob_session.session_id)
        self.assertEqual(alice_session.user_id, "alice")
        self.assertEqual(bob_session.user_id, "bob")

    def test_http_messages_endpoint_keeps_single_tool_direct_render_finalization_state(
        self,
    ) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        scripted = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="time",
                    tool_payload={"timezone": "UTC", "finalize_response": True},
                )
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
                    "conversation_id": "conv-http-direct-render",
                    "message_id": "msg-http-direct-render-1",
                    "body": "告诉我 UTC 时间",
                },
            )
            run_id = response.json()["events"][-1]["run_id"]
            run_diag = client.get(f"/diagnostics/run/{run_id}").json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("现在是UTC", response.json()["events"][-1]["payload"]["text"])
        self.assertEqual(run_diag["llm_request_count"], 1)
        self.assertEqual(run_diag["finalization"]["assessment"], "accepted")
        self.assertEqual(run_diag["finalization"]["request_kind"], "interactive")
        self.assertEqual(run_diag["finalization"]["required_evidence_count"], 1)

    def test_http_messages_endpoint_passes_current_user_message_in_sqlite_history_to_runtime(
        self,
    ) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        captured_session_messages: list[SessionMessage] = []

        def fake_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            captured_session_messages.extend(kwargs.get("session_messages") or [])
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_history_current_turn",
                    event_id="evt_history_current_turn_progress",
                    event_type="progress",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "running"},
                    created_at=datetime.now(timezone.utc),
                ),
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_history_current_turn",
                    event_id="evt_history_current_turn_final",
                    event_type="final",
                    sequence=2,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "ok"},
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        runtime.runtime_loop.run = fake_run  # type: ignore[method-assign]

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-history-current-turn",
                    "message_id": "msg-history-current-turn",
                    "body": "当前这轮用户消息",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item.content for item in captured_session_messages if item.role == "user"],
            ["当前这轮用户消息"],
        )

    def test_feishu_session_history_preserves_ingress_and_enqueue_timestamps_for_queued_turns(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        first_started = threading.Event()
        release_first = threading.Event()

        def blocking_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            if message == "first":
                first_started.set()
                release_first.wait(timeout=2)
            run_id = f"run_{message}"
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
        responses = {}

        with TestClient(app) as client:
            def send(name: str, body: str) -> None:
                responses[name] = client.post(
                    "/messages",
                    json={
                        "channel_id": "feishu",
                        "user_id": "demo",
                        "conversation_id": "conv-feishu-history",
                        "message_id": f"msg-{name}",
                        "body": body,
                    },
                )

            first_thread = threading.Thread(target=send, args=("first", "first"))
            second_thread = threading.Thread(target=send, args=("second", "second"))
            first_thread.start()
            self.assertTrue(first_started.wait(timeout=2))
            second_thread.start()
            time.sleep(0.05)
            release_first.set()
            first_thread.join(timeout=2)
            second_thread.join(timeout=2)

            session_id = responses["second"].json()["session_id"]
            session_response = client.get(f"/diagnostics/session/{session_id}")

        self.assertEqual(session_response.status_code, 200)
        history = session_response.json()["history"]
        first_user = next(item for item in history if item["role"] == "user" and item["content"] == "first")
        second_user = next(item for item in history if item["role"] == "user" and item["content"] == "second")
        self.assertIn("received_at", first_user)
        self.assertIn("received_at", second_user)
        self.assertIn("enqueued_at", first_user)
        self.assertIn("enqueued_at", second_user)
        self.assertIn("started_at", first_user)
        self.assertIn("started_at", second_user)
        self.assertLessEqual(first_user["received_at"], first_user["enqueued_at"])
        self.assertLessEqual(second_user["received_at"], second_user["enqueued_at"])
        self.assertLessEqual(first_user["started_at"], second_user["started_at"])
        self.assertLessEqual(first_user["enqueued_at"], first_user["started_at"])
        self.assertLessEqual(second_user["enqueued_at"], second_user["started_at"])
        self.assertLessEqual(second_user["received_at"], second_user["started_at"])

    def test_http_messages_endpoint_queues_same_conversation_overlap(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        first_started = threading.Event()
        release_first = threading.Event()
        entered: list[str] = []

        def blocking_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            entered.append(trace_id or "")
            if len(entered) == 1:
                first_started.set()
                release_first.wait(timeout=2)
            run_id = f"run_{len(entered)}"
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
                        "conversation_id": "conv-busy",
                        "message_id": f"msg-{name}",
                        "body": body,
                    },
                )

            first_thread = threading.Thread(target=send, args=("first", "hello-1"))
            second_thread = threading.Thread(target=send, args=("second", "hello-2"))
            first_thread.start()
            self.assertTrue(first_started.wait(timeout=2))
            second_thread.start()
            payload = None
            for _ in range(20):
                queue_diag = client.get("/diagnostics/queue")
                self.assertEqual(queue_diag.status_code, 200)
                payload = queue_diag.json()
                if payload["queued_lane_count"] == 1:
                    break
                time.sleep(0.02)
            assert payload is not None
            self.assertEqual(payload["active_lane_count"], 1)
            self.assertEqual(payload["queued_lane_count"], 1)
            self.assertEqual(payload["queued_items_total"], 1)
            release_first.set()
            first_thread.join(timeout=2)
            second_thread.join(timeout=2)

        first_response = responses["first"]
        second_response = responses["second"]
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.json()["events"][-1]["payload"]["text"], "hello-1")
        self.assertEqual(second_response.json()["events"][-1]["payload"]["text"], "hello-2")
        self.assertEqual(entered, [first_response.json()["trace_id"], second_response.json()["trace_id"]])

    def test_feishu_messages_endpoint_returns_rendered_card_in_final_event_payload(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime

        def fake_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_card",
                    event_id="evt_feishu_card_progress",
                    event_type="progress",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "running"},
                    created_at=datetime.now(timezone.utc),
                ),
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_card",
                    event_id="evt_feishu_card_final",
                    event_type="final",
                    sequence=2,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "main"},
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        runtime.runtime_loop.run = fake_run  # type: ignore[method-assign]

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "conv-feishu-card",
                    "message_id": "msg-feishu-card-1",
                    "body": "hello",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        final_event = payload["events"][-1]
        self.assertEqual(final_event["payload"]["text"], "main")
        self.assertIn("card", final_event["payload"])
        self.assertEqual(final_event["payload"]["card"]["schema"], "2.0")
        self.assertEqual(final_event["payload"]["card"]["header"]["title"]["content"], "处理结果")
        self.assertEqual(payload["card"], final_event["payload"]["card"])

    def test_feishu_messages_can_write_and_reuse_thin_memory(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        scripted = ScriptedLLMClient(
            [
                LLMReply(
                    tool_name="memory",
                    tool_payload={
                        "action": "append",
                        "section": "preferences",
                        "content": "Always answer in Chinese.",
                    },
                ),
                LLMReply(final_text="已记住。"),
                LLMReply(final_text="继续处理中。"),
            ]
        )
        runtime.runtime_loop.llm = scripted
        runtime.llm_client_factory.cache_client("default", scripted)
        runtime.llm_client_factory.cache_client("minimax_coding", scripted)

        with TestClient(app) as client:
            first = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "conv-feishu-memory",
                    "message_id": "msg-feishu-memory-1",
                    "body": "记住：以后始终用中文回复",
                },
            )
            second = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "conv-feishu-memory",
                    "message_id": "msg-feishu-memory-2",
                    "body": "继续当前任务",
                },
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertIn("Always answer in Chinese.", runtime.memory_service.load("demo").text)
        self.assertIn("User memory:", scripted.requests[-1].memory_text or "")
        self.assertIn("Always answer in Chinese.", scripted.requests[-1].memory_text or "")

    def test_http_session_resume_detaches_old_conversation_from_target_session(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime

        seed_old = ScriptedLLMClient([LLMReply(final_text="seed old")])
        runtime.runtime_loop.llm = seed_old
        runtime.llm_client_factory.cache_client("openai_gpt5", seed_old)
        runtime.llm_client_factory.cache_client("minimax_m25", seed_old)
        runtime.llm_client_factory.cache_client("kimi_k2", seed_old)

        with TestClient(app) as client:
            old_first = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-old",
                    "message_id": "msg-old-1",
                    "body": "seed old",
                },
            )
            old_session_id = old_first.json()["session_id"]

            seed_current = ScriptedLLMClient([LLMReply(final_text="seed current")])
            runtime.runtime_loop.llm = seed_current
            runtime.llm_client_factory.cache_client("openai_gpt5", seed_current)
            current_first = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-current",
                    "message_id": "msg-current-1",
                    "body": "seed current",
                },
            )
            current_session_id = current_first.json()["session_id"]

            resume_llm = ScriptedLLMClient(
                [
                    LLMReply(
                        tool_name="session",
                        tool_payload={"action": "resume", "session_id": old_session_id},
                    )
                ]
            )
            runtime.runtime_loop.llm = resume_llm
            runtime.llm_client_factory.cache_client("openai_gpt5", resume_llm)
            resumed = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-current",
                    "message_id": "msg-current-2",
                    "body": f"切换到会话 {old_session_id}",
                },
            )

            followup_llm = ScriptedLLMClient(
                [
                    LLMReply(final_text="from old"),
                    LLMReply(final_text="from current"),
                ]
            )
            runtime.runtime_loop.llm = followup_llm
            runtime.llm_client_factory.cache_client("openai_gpt5", followup_llm)
            old_followup = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-old",
                    "message_id": "msg-old-2",
                    "body": "from old",
                },
            )
            current_followup = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-current",
                    "message_id": "msg-current-3",
                    "body": "from current",
                },
            )

        self.assertEqual(old_first.status_code, 200)
        self.assertEqual(current_first.status_code, 200)
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(old_followup.status_code, 200)
        self.assertEqual(current_followup.status_code, 200)
        self.assertNotEqual(current_session_id, old_session_id)
        self.assertEqual(resumed.json()["session_id"], current_session_id)
        self.assertEqual(resumed.json()["active_session_id"], old_session_id)
        self.assertNotEqual(old_followup.json()["session_id"], old_session_id)
        self.assertEqual(current_followup.json()["session_id"], old_session_id)
        self.assertEqual(current_followup.json()["active_session_id"], old_session_id)
        self.assertNotEqual(current_followup.json()["session_id"], old_followup.json()["session_id"])

    def test_http_session_new_strips_switch_control_message_from_source_history_with_sqlite_store(
        self,
    ) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        source = runtime.session_store.create(
            session_id="sess_memory_switch",
            conversation_id="conv-memory-switch",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        runtime.session_store.set_catalog_metadata(
            source.session_id,
            user_id="demo",
            agent_id="main",
            session_title="memory switch",
            session_preview="memory switch preview",
        )
        previous_user = SessionMessage.user("历史任务")
        previous_assistant = SessionMessage.assistant("历史结果")
        runtime.session_store.append_message(source.session_id, previous_user)
        runtime.session_store.append_message(source.session_id, previous_assistant)
        switch_llm = ScriptedLLMClient(
            [LLMReply(tool_name="session", tool_payload={"action": "new"})]
        )
        runtime.runtime_loop.llm = switch_llm
        runtime.llm_client_factory.cache_client("openai_gpt5", switch_llm)
        runtime.llm_client_factory.cache_client("minimax_m25", switch_llm)
        runtime.llm_client_factory.cache_client("kimi_k2", switch_llm)

        with TestClient(app) as client:
            switched = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": source.conversation_id,
                    "message_id": "msg-memory-switch-1",
                    "body": "切换到新会话",
                },
            )

        self.assertEqual(switched.status_code, 200)
        reloaded_source = runtime.session_store.get(source.session_id)
        self.assertNotIn(
            "切换到新会话",
            [item.content for item in reloaded_source.history if item.role == "user"],
        )
        self.assertEqual(reloaded_source.history[-1].content, previous_assistant.content)

    def test_feishu_messages_endpoint_strips_trailing_followup_offer_from_payload_and_history(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime

        def fake_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_followup_strip",
                    event_id="evt_feishu_followup_strip_progress",
                    event_type="progress",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "running"},
                    created_at=datetime.now(timezone.utc),
                ),
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_followup_strip",
                    event_id="evt_feishu_followup_strip_final",
                    event_type="final",
                    sequence=2,
                    trace_id=trace_id or "trace_missing",
                    payload={
                        "text": (
                            "最近一次提交时间是：`2026-04-17T09:55:00Z`\n\n"
                            "如果你需要，我也可以继续帮你换算成北京时间。"
                        )
                    },
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        runtime.runtime_loop.run = fake_run  # type: ignore[method-assign]

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "conv-feishu-followup-strip",
                    "message_id": "msg-feishu-followup-strip-1",
                    "body": "hello",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        final_event = payload["events"][-1]
        self.assertEqual(final_event["payload"]["text"], "最近一次提交时间是：`2026-04-17T09:55:00Z`")
        self.assertIn("card", final_event["payload"])
        session = app.state.runtime.session_store.get(payload["session_id"])
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.history[-1].content, "最近一次提交时间是：`2026-04-17T09:55:00Z`")

    def test_feishu_terminal_durable_text_stays_aligned_across_response_event_and_history(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime

        def fake_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_terminal_visible_text",
                    event_id="evt_feishu_terminal_visible_text_progress",
                    event_type="progress",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "running"},
                    created_at=datetime.now(timezone.utc),
                ),
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_terminal_visible_text",
                    event_id="evt_feishu_terminal_visible_text_final",
                    event_type="final",
                    sequence=2,
                    trace_id=trace_id or "trace_missing",
                    payload={
                        "text": (
                            "该仓库最近一次提交是 main。\n\n"
                            "```feishu_card\n"
                            '{"title":"处理结果","summary":"1 条结果","sections":[{"items":["main"]}]}\n'
                            "```"
                        )
                    },
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        runtime.runtime_loop.run = fake_run  # type: ignore[method-assign]

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "conv-feishu-visible-text-align",
                    "message_id": "msg-feishu-visible-text-align-1",
                    "body": "hello",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        final_event = payload["events"][-1]
        expected_durable_text = "该仓库最近一次提交是 main。\n\n1 条结果\n\n- main"
        self.assertEqual(payload["result"], expected_durable_text)
        self.assertEqual(payload["final_text"], expected_durable_text)
        self.assertEqual(payload["text"], expected_durable_text)
        self.assertEqual(final_event["payload"]["text"], expected_durable_text)
        session = app.state.runtime.session_store.get(payload["session_id"])
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.history[-1].content, expected_durable_text)
        self.assertEqual(
            final_event["payload"]["card"]["header"]["title"]["content"],
            "处理结果",
        )

    def test_feishu_messages_endpoint_keeps_plain_xml_like_trailing_line_in_response_payload_and_history(
        self,
    ) -> None:
        app = build_test_app()
        runtime = app.state.runtime

        def fake_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_plain_xml_tail",
                    event_id="evt_feishu_plain_xml_tail_progress",
                    event_type="progress",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "running"},
                    created_at=datetime.now(timezone.utc),
                ),
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_plain_xml_tail",
                    event_id="evt_feishu_plain_xml_tail_final",
                    event_type="final",
                    sequence=2,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "XML 示例：\n</invoke>"},
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        runtime.runtime_loop.run = fake_run  # type: ignore[method-assign]

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "conv-feishu-plain-xml-tail",
                    "message_id": "msg-feishu-plain-xml-tail-1",
                    "body": "hello",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        final_event = payload["events"][-1]
        expected_visible_text = "XML 示例：\n</invoke>"
        self.assertEqual(payload["result"], expected_visible_text)
        self.assertEqual(payload["final_text"], expected_visible_text)
        self.assertEqual(payload["text"], expected_visible_text)
        self.assertEqual(final_event["payload"]["text"], expected_visible_text)
        session = app.state.runtime.session_store.get(payload["session_id"])
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.history[-1].content, expected_visible_text)

    def test_feishu_error_terminal_durable_text_stays_aligned_across_response_event_and_history(
        self,
    ) -> None:
        app = build_test_app()
        runtime = app.state.runtime

        def fake_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_error_visible_text",
                    event_id="evt_feishu_error_visible_text_error",
                    event_type="error",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={
                        "code": "provider_error",
                        "text": (
                            "处理失败。\n\n"
                            "```feishu_card\n"
                            '{"title":"失败详情","summary":"1 条错误","sections":[{"items":["provider_error"]}]}\n'
                            "```"
                        ),
                    },
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        runtime.runtime_loop.run = fake_run  # type: ignore[method-assign]

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "conv-feishu-error-visible-text",
                    "message_id": "msg-feishu-error-visible-text-1",
                    "body": "hello",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        final_event = payload["events"][-1]
        expected_durable_text = "处理失败。\n\n1 条错误\n\n- provider_error"
        self.assertEqual(payload["result"], expected_durable_text)
        self.assertEqual(payload["final_text"], expected_durable_text)
        self.assertEqual(payload["text"], expected_durable_text)
        self.assertEqual(final_event["payload"]["text"], expected_durable_text)
        self.assertEqual(payload["error_code"], "provider_error")
        self.assertEqual(final_event["payload"]["card"]["header"]["title"]["content"], "失败详情")
        session = app.state.runtime.session_store.get(payload["session_id"])
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.history[-1].content, expected_durable_text)

    def test_feishu_messages_endpoint_strips_malformed_feishu_card_block_before_persisting_history(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime

        def fake_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_history_strip_malformed",
                    event_id="evt_feishu_history_strip_malformed_progress",
                    event_type="progress",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "running"},
                    created_at=datetime.now(timezone.utc),
                ),
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_history_strip_malformed",
                    event_id="evt_feishu_history_strip_malformed_final",
                    event_type="final",
                    sequence=2,
                    trace_id=trace_id or "trace_missing",
                    payload={
                        "text": (
                            "最近一次提交是 **2026-04-05 13:48:45 UTC**。\n\n"
                            "```feishu_card\n"
                            '{"title":"llt22/talkio 最近提交","summary":"1 条","sections":[{"items":["2026-04-05 13:48:45 UTC｜release: v2.7.2"]}]}]\n'
                            "```"
                        )
                    },
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        runtime.runtime_loop.run = fake_run  # type: ignore[method-assign]

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "conv-feishu-history-strip-malformed",
                    "message_id": "msg-feishu-history-strip-malformed-1",
                    "body": "hello",
                },
            )

        self.assertEqual(response.status_code, 200)
        session = app.state.runtime.session_store.get(response.json()["session_id"])
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.history[-1].role, "assistant")
        self.assertEqual(session.history[-1].content, "最近一次提交是 **2026-04-05 13:48:45 UTC**。")
        self.assertNotIn("```feishu_card", session.history[-1].content)

    def test_feishu_messages_endpoint_strips_unclosed_feishu_card_block_before_persisting_history(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime

        def fake_run(session_id, message, trace_id=None, **kwargs):  # noqa: ANN001
            return [
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_history_strip_unclosed",
                    event_id="evt_feishu_history_strip_unclosed_progress",
                    event_type="progress",
                    sequence=1,
                    trace_id=trace_id or "trace_missing",
                    payload={"text": "running"},
                    created_at=datetime.now(timezone.utc),
                ),
                OutboundEvent(
                    session_id=session_id,
                    run_id="run_feishu_history_strip_unclosed",
                    event_id="evt_feishu_history_strip_unclosed_final",
                    event_type="final",
                    sequence=2,
                    trace_id=trace_id or "trace_missing",
                    payload={
                        "text": (
                            "最近一次提交是 **2026-04-05 13:48:45 UTC**。\n\n"
                            "```feishu_card\n"
                            '{"title":"llt22/talkio 最近提交","summary":"1 条"'
                        )
                    },
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        runtime.runtime_loop.run = fake_run  # type: ignore[method-assign]

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "feishu",
                    "user_id": "demo",
                    "conversation_id": "conv-feishu-history-strip-unclosed",
                    "message_id": "msg-feishu-history-strip-unclosed-1",
                    "body": "hello",
                },
            )

        self.assertEqual(response.status_code, 200)
        session = app.state.runtime.session_store.get(response.json()["session_id"])
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.history[-1].content, "最近一次提交是 **2026-04-05 13:48:45 UTC**。")
        self.assertNotIn("```feishu_card", session.history[-1].content)

    def test_http_messages_endpoint_still_runs_for_different_conversation(self) -> None:
        app = build_test_app()
        with TestClient(app) as client:
            left = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-left",
                    "message_id": "msg-http-left",
                    "body": "hello-left",
                },
            )
            right = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-right",
                    "message_id": "msg-http-right",
                    "body": "hello-right",
                },
            )

        self.assertEqual(left.status_code, 200)
        self.assertEqual(right.status_code, 200)
        self.assertEqual(left.json()["events"][-1]["event_type"], "final")
        self.assertEqual(right.json()["events"][-1]["event_type"], "final")


    def test_ingest_message_preserves_requested_agent_id(self) -> None:
        envelope = ingest_message(
            {
                "channel_id": "http",
                "user_id": "demo",
                "conversation_id": "conv-req",
                "message_id": "msg-req",
                "body": "hello",
                "requested_agent_id": "coding",
            }
        )

        self.assertEqual(envelope.requested_agent_id, "coding")

    def test_ingest_message_canonicalizes_legacy_assistant_requested_agent_id(self) -> None:
        envelope = ingest_message(
            {
                "channel_id": "http",
                "user_id": "demo",
                "conversation_id": "conv-legacy-agent",
                "message_id": "msg-legacy-agent",
                "body": "hello",
                "requested_agent_id": "assistant",
            }
        )

        self.assertEqual(envelope.requested_agent_id, "main")

    def test_http_messages_endpoint_falls_back_when_requested_agent_is_disabled(self) -> None:
        with TestClient(build_test_app()) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-disabled-agent",
                    "message_id": "msg-disabled-agent-1",
                    "body": "hello",
                    "requested_agent_id": "ops",
                },
            )
            self.assertEqual(response.status_code, 200)
            session_id = response.json()["session_id"]
            session_response = client.get(f"/diagnostics/session/{session_id}")

        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.json()["active_agent_id"], "main")

    def test_http_messages_endpoint_routes_requested_agent_id_from_request(self) -> None:
        with TestClient(build_test_app()) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "conv-requested-agent",
                    "message_id": "msg-requested-agent-1",
                    "body": "hello",
                    "requested_agent_id": "coding",
                },
            )
            self.assertEqual(response.status_code, 200)
            session_id = response.json()["session_id"]
            session_response = client.get(f"/diagnostics/session/{session_id}")

        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.json()["active_agent_id"], "coding")


if __name__ == "__main__":
    unittest.main()
