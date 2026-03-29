import asyncio
import json
import tempfile
import unittest
from collections.abc import Mapping

from lark_oapi.ws.const import (
    HEADER_MESSAGE_ID,
    HEADER_SEQ,
    HEADER_SUM,
    HEADER_TRACE_ID,
    HEADER_TYPE,
)
from lark_oapi.ws.enum import FrameType, MessageType
from lark_oapi.ws.pb.pbbp2_pb2 import Frame

from marten_runtime.agents.bindings import AgentBinding, AgentBindingRegistry
from marten_runtime.agents.registry import AgentRegistry
from marten_runtime.agents.router import AgentRouter
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.channels.dead_letter import InMemoryDeadLetterQueue
from marten_runtime.channels.delivery_retry import DeliveryRetryPolicy
from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.channels.feishu.delivery_session import InMemoryFeishuDeliverySessionStore
from marten_runtime.channels.feishu.delivery import FeishuDeliveryClient, FeishuDeliveryPayload
from marten_runtime.channels.feishu.inbound import parse_feishu_callback, to_inbound_envelope
from marten_runtime.channels.feishu.models import FeishuInboundEvent
from marten_runtime.channels.feishu.service import FeishuWebsocketService


class _FakeDeliveryClient:
    def __init__(self) -> None:
        self.payloads: list[FeishuDeliveryPayload] = []

    def deliver(self, payload: FeishuDeliveryPayload) -> dict[str, object]:
        self.payloads.append(payload)
        return {
            "ok": True,
            "message_id": f"om_{len(self.payloads)}",
            "event_id": payload.event_id,
            "event_type": payload.event_type,
            "run_id": payload.run_id,
            "trace_id": payload.trace_id,
            "sequence": payload.sequence,
        }


class _RecordingDeliveryTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, str], dict]] = []
        self.updated: list[tuple[str, dict[str, str], dict]] = []

    def post(self, url: str, headers: dict[str, str], body: dict) -> dict:
        if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
            return {
                "code": 0,
                "tenant_access_token": "tenant-token",
                "expire": 7200,
            }
        self.sent.append((url, headers, body))
        return {
            "code": 0,
            "data": {
                "message_id": f"om_message_{len(self.sent)}",
            },
        }

    def put(self, url: str, headers: dict[str, str], body: dict) -> dict:
        self.updated.append((url, headers, body))
        return {
            "code": 0,
            "data": {
                "message_id": url.rsplit("/", 1)[-1],
            },
        }


class _FlakyDeliveryTransport:
    def __init__(self, failures_by_event_type: dict[str, int]) -> None:
        self.failures_by_event_type = dict(failures_by_event_type)
        self.attempts: dict[str, int] = {}

    def post(self, url: str, headers: dict[str, str], body: dict) -> dict:
        if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
            return {
                "code": 0,
                "tenant_access_token": "tenant-token",
                "expire": 7200,
            }
        if body.get("msg_type") == "interactive":
            event_type = "final"
        else:
            text = json.loads(body["content"])["text"]
            if text == "failed":
                event_type = "error"
            else:
                event_type = "progress"
        attempt = self.attempts.get(event_type, 0) + 1
        self.attempts[event_type] = attempt
        if attempt <= self.failures_by_event_type.get(event_type, 0):
            raise RuntimeError(f"boom:{event_type}:{attempt}")
        return {
            "code": 0,
            "data": {
                "message_id": f"om_retry_{event_type}_{attempt}",
            },
        }


class FeishuTests(unittest.TestCase):
    def test_receipt_store_claims_feishu_dedupe_key_once(self) -> None:
        store = InMemoryReceiptStore()

        first = store.claim(
            channel_id="feishu",
            dedupe_key="dedupe_1",
            trace_id="trace_1",
            conversation_id="chat_1",
            message_id="evt_feishu_1",
        )
        second = store.claim(
            channel_id="feishu",
            dedupe_key="dedupe_1",
            trace_id="trace_2",
            conversation_id="chat_1",
            message_id="evt_feishu_1",
        )

        self.assertTrue(first.claimed)
        self.assertFalse(second.claimed)
        self.assertTrue(store.already_seen("dedupe_1"))
        self.assertEqual(second.record.trace_id, "trace_1")
        self.assertEqual(store.stats()["duplicate_total"], 1)

    def test_inbound_event_normalizes_to_inbound_envelope(self) -> None:
        event = FeishuInboundEvent(
            event_id="evt_feishu_1",
            message_id="msg_feishu_1",
            chat_id="chat_1",
            user_id="user_1",
            sender_type="user",
            chat_type="p2p",
            message_type="text",
            mentions=[],
            text="hello from feishu",
        )

        envelope = to_inbound_envelope(event)

        self.assertEqual(envelope.channel_id, "feishu")
        self.assertEqual(envelope.conversation_id, "chat_1")
        self.assertEqual(envelope.message_id, "msg_feishu_1")
        self.assertTrue(envelope.trace_id.startswith("trace_"))

    def test_websocket_payload_can_be_normalized(self) -> None:
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_ws_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_1",
                    }
                },
                "message": {
                    "message_id": "msg_ws_1",
                    "chat_id": "chat_1",
                    "chat_type": "group",
                    "message_type": "text",
                    "content": json.dumps({"text": "hello from feishu"}),
                    "mentions": [{"name": "bot", "key": "@_user_1"}],
                },
            },
        }

        event = parse_feishu_callback(payload)
        envelope = to_inbound_envelope(event)

        self.assertEqual(event.chat_id, "chat_1")
        self.assertEqual(event.user_id, "user_1")
        self.assertEqual(event.event_id, "evt_ws_1")
        self.assertEqual(event.message_id, "msg_ws_1")
        self.assertEqual(event.sender_type, "user")
        self.assertEqual(event.chat_type, "group")
        self.assertEqual(event.message_type, "text")
        self.assertEqual(event.mentions, ["bot"])
        self.assertEqual(event.text, "hello from feishu")
        self.assertEqual(envelope.channel_id, "feishu")
        self.assertEqual(envelope.message_id, "msg_ws_1")

    def test_feishu_envelope_routes_to_bound_agent_when_mention_required_is_met(self) -> None:
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_ws_route_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_route_1",
                    }
                },
                "message": {
                    "message_id": "msg_ws_route_1",
                    "chat_id": "chat_route_1",
                    "chat_type": "group",
                    "content": json.dumps({"text": "@bot hello from feishu"}),
                    "mentions": [{"name": "bot", "key": "@_user_1"}],
                },
            },
        }
        event = parse_feishu_callback(payload)
        envelope = to_inbound_envelope(event)
        registry = AgentRegistry()
        registry.register(AgentSpec(agent_id="assistant", role="general_assistant", app_id="example_assistant"))
        registry.register(AgentSpec(agent_id="ops", role="ops_agent", app_id="example_assistant"))
        router = AgentRouter(
            registry,
            default_agent_id="assistant",
            bindings=AgentBindingRegistry(
                [
                    AgentBinding(
                        agent_id="ops",
                        channel_id="feishu",
                        conversation_id="chat_route_1",
                        mention_required=True,
                    )
                ]
            ),
        )

        routed = router.route(envelope)

        self.assertEqual(routed.agent_id, "ops")

    def test_final_delivery_payload_renders_interactive_card_without_internal_ids(self) -> None:
        captured: list[tuple[str, dict[str, str], dict]] = []

        def fake_post(url: str, headers: dict[str, str], body: dict) -> dict:
            captured.append((url, headers, body))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "data": {
                    "message_id": "om_message_1",
                },
            }

        client = FeishuDeliveryClient(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            transport=fake_post,
        )
        payload = FeishuDeliveryPayload(
            chat_id="chat_1",
            event_type="final",
            event_id="evt_1",
            run_id="run_1",
            trace_id="trace_1",
            sequence=2,
            text="Your GitHub login is **tiezhuli001**.",
        )

        result = client.send(payload)

        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], "run_1")
        self.assertEqual(result["trace_id"], "trace_1")
        self.assertTrue(captured[0][0].endswith("/open-apis/auth/v3/tenant_access_token/internal"))
        self.assertTrue(captured[1][0].endswith("/open-apis/im/v1/messages?receive_id_type=chat_id"))
        self.assertEqual(captured[1][1]["Authorization"], "Bearer tenant-token")
        self.assertEqual(captured[1][2]["msg_type"], "interactive")
        card = json.loads(captured[1][2]["content"])
        card_text = card["elements"][0]["text"]["content"]
        self.assertEqual(card_text, "Your GitHub login is **tiezhuli001**.")
        self.assertNotIn("run_id=", card_text)
        self.assertNotIn("trace_id=", card_text)
        self.assertNotIn("event_id=", card_text)

    def test_websocket_service_uses_app_credentials_to_get_endpoint(self) -> None:
        captured: list[tuple[str, dict[str, str], dict[str, str]]] = []

        def endpoint_transport(url: str, headers: dict[str, str], body: dict[str, str]) -> dict[str, object]:
            captured.append((url, headers, body))
            return {
                "code": 0,
                "msg": "ok",
                "data": {
                    "URL": "wss://open.feishu.cn/ws?service_id=1&device_id=device-1",
                    "ClientConfig": {
                        "ReconnectCount": -1,
                        "ReconnectInterval": 15,
                        "ReconnectNonce": 30,
                        "PingInterval": 60,
                    },
                },
            }

        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
                "FEISHU_BASE_URL": "https://open.feishu.cn",
            },
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=lambda envelope: {"status": "accepted", "events": []},
            delivery_client=_FakeDeliveryClient(),
            endpoint_transport=endpoint_transport,
        )

        endpoint = service.fetch_endpoint()

        self.assertEqual(endpoint.url, "wss://open.feishu.cn/ws?service_id=1&device_id=device-1")
        self.assertEqual(endpoint.client_config.reconnect_interval_s, 15)
        self.assertTrue(captured[0][0].endswith("/callback/ws/endpoint"))
        self.assertEqual(captured[0][2]["AppID"], "app-id")
        self.assertEqual(captured[0][2]["AppSecret"], "app-secret")

    def test_websocket_service_prevents_second_process_from_starting_with_same_lock(self) -> None:
        async def exercise() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                lock_path = f"{tmp}/feishu.lock"
                first = FeishuWebsocketService(
                    env={
                        "FEISHU_APP_ID": "app-id",
                        "FEISHU_APP_SECRET": "app-secret",
                        "FEISHU_WEBSOCKET_LOCK_PATH": lock_path,
                    },
                    receipt_store=InMemoryReceiptStore(),
                    runtime_handler=lambda envelope: {"status": "accepted", "events": []},
                    delivery_client=_FakeDeliveryClient(),
                )
                second = FeishuWebsocketService(
                    env={
                        "FEISHU_APP_ID": "app-id",
                        "FEISHU_APP_SECRET": "app-secret",
                        "FEISHU_WEBSOCKET_LOCK_PATH": lock_path,
                    },
                    receipt_store=InMemoryReceiptStore(),
                    runtime_handler=lambda envelope: {"status": "accepted", "events": []},
                    delivery_client=_FakeDeliveryClient(),
                )

                self.assertTrue(first._acquire_singleton_lock())
                await second.start_background()

                self.assertFalse(second.state.lock_acquired)
                self.assertEqual(second.state.connected, False)
                self.assertIn("FEISHU_WEBSOCKET_LOCKED", second.state.last_error or "")

                await second.stop_background()
                first._release_singleton_lock()

        asyncio.run(exercise())

    def test_websocket_service_processes_message_event_and_suppresses_duplicate(self) -> None:
        delivery = _FakeDeliveryClient()
        store = InMemoryReceiptStore()
        handled_traces: list[str] = []

        def runtime_handler(envelope: object) -> dict[str, object]:
            handled_traces.append(envelope.trace_id)
            return {
                "status": "accepted",
                "trace_id": envelope.trace_id,
                "session_id": "sess_1",
                "events": [
                    {
                        "event_type": "progress",
                        "event_id": "evt_progress_1",
                        "run_id": "run_1",
                        "trace_id": envelope.trace_id,
                        "sequence": 1,
                        "payload": {"text": "running"},
                    },
                    {
                        "event_type": "final",
                        "event_id": "evt_final_1",
                        "run_id": "run_1",
                        "trace_id": envelope.trace_id,
                        "sequence": 2,
                        "payload": {"text": "done"},
                    },
                ],
            }

        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=store,
            runtime_handler=runtime_handler,
            delivery_client=delivery,
        )
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_service_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_service_1",
                    }
                },
                "message": {
                    "message_id": "msg_service_1",
                    "chat_id": "chat_service_1",
                    "content": json.dumps({"text": "hello from service"}),
                },
            },
        }

        first = service.handle_event_payload(payload)
        second = service.handle_event_payload(payload)

        self.assertEqual(first.status, "accepted")
        self.assertEqual(second.status, "ignored")
        self.assertEqual(second.body["reason"], "duplicate")
        self.assertEqual(handled_traces, [first.body["trace_id"]])
        self.assertEqual(len(delivery.payloads), 2)

    def test_websocket_service_suppresses_duplicate_message_id_across_event_replays(self) -> None:
        delivery = _FakeDeliveryClient()
        store = InMemoryReceiptStore()
        handled_message_ids: list[str] = []

        def runtime_handler(envelope: object) -> dict[str, object]:
            handled_message_ids.append(envelope.message_id)
            return {
                "status": "accepted",
                "trace_id": envelope.trace_id,
                "session_id": "sess_replay",
                "events": [
                    {
                        "event_type": "final",
                        "event_id": "evt_final_replay",
                        "run_id": "run_replay",
                        "trace_id": envelope.trace_id,
                        "sequence": 1,
                        "payload": {"text": "done"},
                    }
                ],
            }

        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=store,
            runtime_handler=runtime_handler,
            delivery_client=delivery,
        )
        first_payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_replay_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_replay_1",
                    }
                },
                "message": {
                    "message_id": "msg_replay_1",
                    "chat_id": "chat_replay_1",
                    "content": json.dumps({"text": "hello replay"}),
                },
            },
        }
        second_payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_replay_2",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_replay_1",
                    }
                },
                "message": {
                    "message_id": "msg_replay_1",
                    "chat_id": "chat_replay_1",
                    "content": json.dumps({"text": "hello replay"}),
                },
            },
        }

        first = service.handle_event_payload(first_payload)
        second = service.handle_event_payload(second_payload)

        self.assertEqual(first.status, "accepted")
        self.assertEqual(second.status, "ignored")
        self.assertEqual(second.body["reason"], "duplicate")
        self.assertEqual(handled_message_ids, ["msg_replay_1"])
        self.assertEqual(len(delivery.payloads), 1)

    def test_websocket_service_ignores_app_originated_messages(self) -> None:
        delivery = _FakeDeliveryClient()
        store = InMemoryReceiptStore()
        handled = False

        def runtime_handler(envelope: object) -> dict[str, object]:
            nonlocal handled
            handled = True
            return {"status": "accepted", "trace_id": envelope.trace_id, "session_id": "sess_self", "events": []}

        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=store,
            runtime_handler=runtime_handler,
            delivery_client=delivery,
        )
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_self_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "app",
                    "sender_id": {
                        "open_id": "ou_bot_self",
                    }
                },
                "message": {
                    "message_id": "msg_self_1",
                    "chat_id": "chat_self_1",
                    "content": json.dumps({"text": "bot echo"}),
                },
            },
        }

        result = service.handle_event_payload(payload)

        self.assertEqual(result.status, "ignored")
        self.assertEqual(result.body["reason"], "self_message")
        self.assertFalse(handled)
        self.assertEqual(len(delivery.payloads), 0)
        self.assertEqual(store.stats()["claimed_total"], 0)

    def test_websocket_service_can_restrict_processing_to_private_chats(self) -> None:
        delivery = _FakeDeliveryClient()
        store = InMemoryReceiptStore()
        handled = False

        def runtime_handler(envelope: object) -> dict[str, object]:
            nonlocal handled
            handled = True
            return {"status": "accepted", "trace_id": envelope.trace_id, "session_id": "sess_private", "events": []}

        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=store,
            runtime_handler=runtime_handler,
            delivery_client=delivery,
            allowed_chat_types=["p2p"],
        )
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_group_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_group_1",
                    }
                },
                "message": {
                    "message_id": "msg_group_1",
                    "chat_id": "chat_group_1",
                    "chat_type": "group",
                    "content": json.dumps({"text": "hello group"}),
                },
            },
        }

        result = service.handle_event_payload(payload)

        self.assertEqual(result.status, "ignored")
        self.assertEqual(result.body["reason"], "chat_not_allowed")
        self.assertEqual(result.body["chat_type"], "group")
        self.assertFalse(handled)
        self.assertEqual(len(delivery.payloads), 0)
        self.assertEqual(store.stats()["claimed_total"], 0)

    def test_websocket_service_builds_ack_frame_for_event(self) -> None:
        delivery = _FakeDeliveryClient()
        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=lambda envelope: {
                "status": "accepted",
                "trace_id": envelope.trace_id,
                "session_id": "sess_frame",
                "events": [
                    {
                        "event_type": "final",
                        "event_id": "evt_final_frame",
                        "run_id": "run_frame",
                        "trace_id": envelope.trace_id,
                        "sequence": 1,
                        "payload": {"text": "done"},
                    }
                ],
            },
            delivery_client=delivery,
        )
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_frame_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_frame_1",
                    }
                },
                "message": {
                    "message_id": "msg_frame_1",
                    "chat_id": "chat_frame_1",
                    "content": json.dumps({"text": "hello"}),
                },
            },
        }
        frame_bytes = self._build_event_frame(payload)

        ack_bytes = asyncio.run(service.handle_frame_bytes(frame_bytes))

        ack = Frame()
        ack.ParseFromString(ack_bytes)
        self.assertEqual(json.loads(ack.payload.decode("utf-8"))["code"], 200)
        self.assertEqual(len(delivery.payloads), 1)

    def test_websocket_service_updates_state_from_pong_frame(self) -> None:
        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=lambda envelope: {"status": "accepted", "events": []},
            delivery_client=_FakeDeliveryClient(),
        )
        frame = Frame()
        header = frame.headers.add()
        header.key = HEADER_TYPE
        header.value = MessageType.PONG.value
        frame.service = 1
        frame.method = FrameType.CONTROL.value
        frame.SeqID = 0
        frame.LogID = 0
        frame.payload = json.dumps(
            {
                "ReconnectCount": 9,
                "ReconnectInterval": 7,
                "ReconnectNonce": 3,
                "PingInterval": 55,
            }
        ).encode("utf-8")

        asyncio.run(service.handle_frame_bytes(frame.SerializeToString()))

        self.assertEqual(service.client_config.reconnect_count, 9)
        self.assertEqual(service.client_config.reconnect_interval_s, 7)
        self.assertEqual(service.client_config.ping_interval_s, 55)

    def test_progress_is_hidden_and_final_sends_one_card(self) -> None:
        transport = _RecordingDeliveryTransport()
        sessions = InMemoryFeishuDeliverySessionStore()
        client = FeishuDeliveryClient(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            transport=transport.post,
            update_transport=transport.put,
            session_store=sessions,
            enable_message_update=True,
        )

        first_progress = client.deliver(
            FeishuDeliveryPayload(
                chat_id="chat_waiting_1",
                event_type="progress",
                event_id="evt_wait_1",
                run_id="run_wait_1",
                trace_id="trace_wait_1",
                sequence=1,
                text="running",
            )
        )
        second_progress = client.deliver(
            FeishuDeliveryPayload(
                chat_id="chat_waiting_1",
                event_type="progress",
                event_id="evt_wait_2",
                run_id="run_wait_1",
                trace_id="trace_wait_1",
                sequence=2,
                text="still running",
            )
        )
        final_result = client.deliver(
            FeishuDeliveryPayload(
                chat_id="chat_waiting_1",
                event_type="final",
                event_id="evt_wait_3",
                run_id="run_wait_1",
                trace_id="trace_wait_1",
                sequence=3,
                text="done",
            )
        )

        self.assertEqual(first_progress["action"], "skip")
        self.assertEqual(second_progress["action"], "skip")
        self.assertEqual(final_result["action"], "send")
        self.assertEqual(len(transport.sent), 1)
        self.assertEqual(len(transport.updated), 0)
        self.assertEqual(transport.sent[0][2]["msg_type"], "interactive")
        self.assertEqual(sessions.active_count(), 0)

    def test_hidden_progress_does_not_block_error_send_when_update_unavailable(self) -> None:
        transport = _RecordingDeliveryTransport()
        sessions = InMemoryFeishuDeliverySessionStore()
        client = FeishuDeliveryClient(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            transport=transport.post,
            session_store=sessions,
            enable_message_update=False,
        )

        first_progress = client.deliver(
            FeishuDeliveryPayload(
                chat_id="chat_waiting_2",
                event_type="progress",
                event_id="evt_wait_4",
                run_id="run_wait_2",
                trace_id="trace_wait_2",
                sequence=1,
                text="running",
            )
        )
        second_progress = client.deliver(
            FeishuDeliveryPayload(
                chat_id="chat_waiting_2",
                event_type="progress",
                event_id="evt_wait_5",
                run_id="run_wait_2",
                trace_id="trace_wait_2",
                sequence=2,
                text="still running",
            )
        )
        error_result = client.deliver(
            FeishuDeliveryPayload(
                chat_id="chat_waiting_2",
                event_type="error",
                event_id="evt_wait_6",
                run_id="run_wait_2",
                trace_id="trace_wait_2",
                sequence=3,
                text="failed",
            )
        )

        self.assertEqual(first_progress["action"], "skip")
        self.assertEqual(second_progress["action"], "skip")
        self.assertEqual(error_result["action"], "send")
        self.assertEqual(len(transport.sent), 1)
        self.assertEqual(len(transport.updated), 0)
        self.assertEqual(sessions.active_count(), 0)

    def test_hidden_progress_does_not_hit_transport_or_dead_letter(self) -> None:
        transport = _FlakyDeliveryTransport({"progress": 3, "final": 4})
        dead_letters = InMemoryDeadLetterQueue()
        sleeps: list[float] = []
        client = FeishuDeliveryClient(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            transport=transport.post,
            session_store=InMemoryFeishuDeliverySessionStore(),
            enable_message_update=False,
            retry_policy=DeliveryRetryPolicy(
                progress_max_retries=2,
                final_max_retries=5,
                error_max_retries=5,
                base_backoff_seconds=0.01,
                max_backoff_seconds=0.02,
            ),
            dead_letter_queue=dead_letters,
            sleeper=sleeps.append,
        )

        progress_result = client.deliver(
            FeishuDeliveryPayload(
                chat_id="chat_retry_1",
                event_type="progress",
                event_id="evt_retry_progress",
                run_id="run_retry",
                trace_id="trace_retry",
                sequence=1,
                text="running",
            )
        )
        final_result = client.deliver(
            FeishuDeliveryPayload(
                chat_id="chat_retry_1",
                event_type="final",
                event_id="evt_retry_final",
                run_id="run_retry",
                trace_id="trace_retry",
                sequence=2,
                text="done",
            )
        )

        self.assertTrue(progress_result["ok"])
        self.assertEqual(progress_result["action"], "skip")
        self.assertEqual(progress_result["retry_count"], 0)
        self.assertTrue(final_result["ok"])
        self.assertEqual(final_result["retry_count"], 4)
        self.assertEqual(dead_letters.count(), 0)
        self.assertGreaterEqual(len(sleeps), 4)

    def test_terminal_delivery_failure_records_dead_letter_with_trace_metadata(self) -> None:
        transport = _FlakyDeliveryTransport({"final": 6})
        dead_letters = InMemoryDeadLetterQueue()
        client = FeishuDeliveryClient(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            transport=transport.post,
            session_store=InMemoryFeishuDeliverySessionStore(),
            enable_message_update=False,
            retry_policy=DeliveryRetryPolicy(
                progress_max_retries=2,
                final_max_retries=5,
                error_max_retries=5,
                base_backoff_seconds=0.01,
                max_backoff_seconds=0.02,
            ),
            dead_letter_queue=dead_letters,
            sleeper=lambda _: None,
        )

        result = client.deliver(
            FeishuDeliveryPayload(
                chat_id="chat_retry_2",
                event_type="final",
                event_id="evt_retry_dead",
                run_id="run_retry_dead",
                trace_id="trace_retry_dead",
                sequence=9,
                text="done",
            )
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["retry_count"], 5)
        self.assertEqual(dead_letters.count(), 1)
        item = dead_letters.list_items()[0]
        self.assertEqual(item.run_id, "run_retry_dead")
        self.assertEqual(item.trace_id, "trace_retry_dead")
        self.assertEqual(item.event_id, "evt_retry_dead")
        self.assertEqual(item.sequence, 9)

    def test_delivery_logs_internal_ids_without_exposing_them_to_user(self) -> None:
        transport = _RecordingDeliveryTransport()
        client = FeishuDeliveryClient(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            transport=transport.post,
            session_store=InMemoryFeishuDeliverySessionStore(),
            enable_message_update=False,
        )

        with self.assertLogs("marten_runtime.channels.feishu.delivery", level="INFO") as captured:
            result = client.deliver(
                FeishuDeliveryPayload(
                    chat_id="chat_log_1",
                    event_type="final",
                    event_id="evt_log_1",
                    run_id="run_log_1",
                    trace_id="trace_log_1",
                    sequence=2,
                    text="hello",
                )
            )

        self.assertTrue(result["ok"])
        self.assertIn("run_id=run_log_1", captured.output[-1])
        self.assertIn("trace_id=trace_log_1", captured.output[-1])
        self.assertIn("event_id=evt_log_1", captured.output[-1])

    def _build_event_frame(self, payload: dict[str, object]) -> bytes:
        frame = Frame()
        frame.service = 1
        frame.method = FrameType.DATA.value
        frame.SeqID = 0
        frame.LogID = 0
        frame.payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        for key, value in {
            HEADER_TYPE: MessageType.EVENT.value,
            HEADER_MESSAGE_ID: "msg_1",
            HEADER_TRACE_ID: "trace_1",
            HEADER_SUM: "1",
            HEADER_SEQ: "0",
        }.items():
            header = frame.headers.add()
            header.key = key
            header.value = value
        return frame.SerializeToString()


if __name__ == "__main__":
    unittest.main()
