import asyncio
import json
import tempfile
import threading
import time
import unittest

from lark_oapi.ws.const import HEADER_MESSAGE_ID, HEADER_SEQ, HEADER_SUM, HEADER_TRACE_ID, HEADER_TYPE
from lark_oapi.ws.enum import FrameType, MessageType
from lark_oapi.ws.pb.pbbp2_pb2 import Frame

from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.channels.feishu.inbound import parse_feishu_callback, to_inbound_envelope
from marten_runtime.channels.feishu.models import (
    FeishuInboundEvent,
    FeishuWebsocketClientConfig,
    FeishuWebsocketEndpoint,
)
from marten_runtime.channels.feishu.service import FeishuWebsocketService
from marten_runtime.gateway.dedupe import build_dedupe_key
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.lanes import ConversationLaneManager
from tests.support.feishu_builders import BlockingDeliveryClient, FakeDeliveryClient, build_event_frame



class FeishuWebsocketServiceTests(unittest.TestCase):
    def test_feishu_same_chat_overlap_is_queued_without_busy_reply(self) -> None:
        delivery = FakeDeliveryClient()
        calls: list[str] = []
        lane_manager = ConversationLaneManager()
        run_history = InMemoryRunHistory()
        first_started = threading.Event()
        release_first = threading.Event()

        def runtime_handler(envelope: object) -> dict[str, object]:
            calls.append(envelope.message_id)
            if len(calls) == 1:
                first_started.set()
                release_first.wait(timeout=2)
            record = run_history.start(
                session_id="sess_busy",
                trace_id=envelope.trace_id,
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            original_run_id = record.run_id
            record.run_id = f"run_{len(calls)}"
            run_history._items[record.run_id] = run_history._items.pop(original_run_id)
            return {
                "status": "accepted",
                "session_id": "sess_busy",
                "trace_id": envelope.trace_id,
                "events": [
                    {
                        "event_type": "final",
                        "event_id": "evt_final_busy",
                        "run_id": record.run_id,
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
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=runtime_handler,
            delivery_client=delivery,
            lane_manager=lane_manager,
            run_history=run_history,
        )
        results: dict[str, object] = {}

        def handle(name: str, payload: dict[str, object]) -> None:
            results[name] = service.handle_event_payload(payload)

        first_payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_busy_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"user_id": "user_busy"},
                },
                "message": {
                    "message_id": "msg_busy_1",
                    "chat_id": "chat_busy",
                    "content": json.dumps({"text": "hello busy 1"}),
                },
            },
        }
        second_payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_busy_2",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"user_id": "user_busy"},
                },
                "message": {
                    "message_id": "msg_busy_2",
                    "chat_id": "chat_busy",
                    "content": json.dumps({"text": "hello busy 2"}),
                },
            },
        }
        first_thread = threading.Thread(target=handle, args=("first", first_payload))
        second_thread = threading.Thread(target=handle, args=("second", second_payload))
        first_thread.start()
        self.assertTrue(first_started.wait(timeout=2))
        second_thread.start()

        deadline = time.time() + 2
        stats = service.stats()
        while stats["queued_lane_count"] != 1 and time.time() < deadline:
            time.sleep(0.01)
            stats = service.stats()
        self.assertEqual(stats["queued_lane_count"], 1)
        self.assertEqual(stats["queued_items_total"], 1)

        release_first.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)

        self.assertEqual(results["first"].status, "accepted")
        self.assertEqual(results["second"].status, "accepted")
        self.assertEqual(calls, ["msg_busy_1", "msg_busy_2"])
        self.assertEqual(len(delivery.payloads), 2)
        second_run = run_history.get("run_2")
        self.assertEqual(second_run.queue.queue_depth_at_enqueue, 2)
        self.assertTrue(second_run.queue.waited_in_lane)

    def test_feishu_same_chat_serializes_delivery_until_prior_turn_is_sent(self) -> None:
        delivery = BlockingDeliveryClient()
        lane_manager = ConversationLaneManager()
        results: dict[str, object] = {}
        finished: dict[str, threading.Event] = {
            "first": threading.Event(),
            "second": threading.Event(),
        }
        call_count = 0

        def runtime_handler(envelope: object) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            return {
                "status": "accepted",
                "session_id": "sess_delivery_order",
                "trace_id": envelope.trace_id,
                "events": [
                    {
                        "event_type": "final",
                        "event_id": f"evt_final_{call_count}",
                        "run_id": f"run_{call_count}",
                        "trace_id": envelope.trace_id,
                        "sequence": 1,
                        "payload": {"text": f"done_{call_count}"},
                    }
                ],
            }

        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=runtime_handler,
            delivery_client=delivery,
            lane_manager=lane_manager,
        )

        first_payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_delivery_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"user_id": "user_delivery"},
                },
                "message": {
                    "message_id": "msg_delivery_1",
                    "chat_id": "chat_delivery",
                    "content": json.dumps({"text": "hello delivery 1"}),
                },
            },
        }
        second_payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_delivery_2",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"user_id": "user_delivery"},
                },
                "message": {
                    "message_id": "msg_delivery_2",
                    "chat_id": "chat_delivery",
                    "content": json.dumps({"text": "hello delivery 2"}),
                },
            },
        }

        def handle(name: str, payload: dict[str, object]) -> None:
            results[name] = service.handle_event_payload(payload)
            finished[name].set()

        first_thread = threading.Thread(target=handle, args=("first", first_payload))
        second_thread = threading.Thread(target=handle, args=("second", second_payload))
        first_thread.start()
        self.assertTrue(delivery.first_delivery_started.wait(timeout=2))

        second_thread.start()
        self.assertFalse(
            delivery.second_delivery_started.wait(timeout=0.2),
            "second same-chat turn must not start delivery before prior delivery completes",
        )
        self.assertFalse(
            finished["second"].wait(timeout=0.2),
            "second same-chat turn must stay blocked until prior delivery is released",
        )

        delivery.release_first_delivery.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)

        self.assertEqual([payload.run_id for payload in delivery.payloads], ["run_1", "run_2"])
        self.assertEqual(results["first"].status, "accepted")
        self.assertEqual(results["second"].status, "accepted")

    def test_feishu_different_chat_still_runs_when_another_lane_is_busy(self) -> None:
        delivery = FakeDeliveryClient()
        calls: list[str] = []
        lane_manager = ConversationLaneManager()
        release_both = threading.Event()
        first_started = threading.Event()
        second_started = threading.Event()

        def runtime_handler(envelope: object) -> dict[str, object]:
            calls.append(envelope.conversation_id)
            if envelope.conversation_id == "chat_busy":
                first_started.set()
                release_both.wait(timeout=2)
            if envelope.conversation_id == "chat_open":
                second_started.set()
                release_both.wait(timeout=2)
            return {
                "status": "accepted",
                "session_id": "sess_open",
                "trace_id": envelope.trace_id,
                "events": [
                    {
                        "event_type": "final",
                        "event_id": "evt_final_open",
                        "run_id": "run_open",
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
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=runtime_handler,
            delivery_client=delivery,
            lane_manager=lane_manager,
        )
        results: dict[str, object] = {}

        def handle(name: str, chat_id: str) -> None:
            results[name] = service.handle_event_payload(
                {
                    "schema": "2.0",
                    "header": {
                        "event_id": f"evt_{name}_1",
                        "event_type": "im.message.receive_v1",
                    },
                    "event": {
                        "sender": {
                            "sender_type": "user",
                            "sender_id": {"user_id": f"user_{name}"},
                        },
                        "message": {
                            "message_id": f"msg_{name}_1",
                            "chat_id": chat_id,
                            "content": json.dumps({"text": f"hello {name}"}),
                        },
                    },
                }
            )

        busy_thread = threading.Thread(target=handle, args=("busy", "chat_busy"))
        open_thread = threading.Thread(target=handle, args=("open", "chat_open"))
        busy_thread.start()
        self.assertTrue(first_started.wait(timeout=2))
        open_thread.start()
        self.assertTrue(second_started.wait(timeout=2))
        release_both.set()
        busy_thread.join(timeout=2)
        open_thread.join(timeout=2)

        self.assertEqual(results["busy"].status, "accepted")
        self.assertEqual(results["open"].status, "accepted")
        self.assertEqual(set(calls), {"chat_busy", "chat_open"})
        self.assertEqual(len(delivery.payloads), 2)

    def test_websocket_service_offloads_blocking_runtime_handler_from_event_loop(self) -> None:
        async def exercise() -> None:
            delivery = FakeDeliveryClient()

            def runtime_handler(envelope: object) -> dict[str, object]:
                time.sleep(0.2)
                return {
                    "status": "accepted",
                    "trace_id": envelope.trace_id,
                    "session_id": "sess_async",
                    "events": [
                        {
                            "event_type": "final",
                            "event_id": "evt_final_async",
                            "run_id": "run_async",
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
                receipt_store=InMemoryReceiptStore(),
                runtime_handler=runtime_handler,
                delivery_client=delivery,
            )
            frame = Frame()
            header = frame.headers.add()
            header.key = HEADER_TYPE
            header.value = MessageType.EVENT.value
            message_id = frame.headers.add()
            message_id.key = HEADER_MESSAGE_ID
            message_id.value = "msg_async_1"
            trace_id = frame.headers.add()
            trace_id.key = HEADER_TRACE_ID
            trace_id.value = "trace_async_1"
            frame.method = FrameType.DATA.value
            frame.SeqID = 0
            frame.LogID = 0
            frame.service = 1
            frame.payload = json.dumps(
                {
                    "schema": "2.0",
                    "header": {
                        "event_id": "evt_async_1",
                        "event_type": "im.message.receive_v1",
                    },
                    "event": {
                        "sender": {
                            "sender_type": "user",
                            "sender_id": {"user_id": "user_async_1"},
                        },
                        "message": {
                            "message_id": "msg_async_1",
                            "chat_id": "chat_async_1",
                            "content": json.dumps({"text": "hello async"}),
                        },
                    },
                }
            ).encode("utf-8")

            ticks = 0

            async def ticker() -> None:
                nonlocal ticks
                start = time.perf_counter()
                while time.perf_counter() - start < 0.15:
                    ticks += 1
                    await asyncio.sleep(0.01)

            await asyncio.gather(service.handle_frame_bytes(frame.SerializeToString()), ticker())

            self.assertGreaterEqual(ticks, 4)

        asyncio.run(exercise())

    def test_websocket_service_offloads_blocking_endpoint_fetch_from_event_loop(self) -> None:
        async def exercise() -> None:
            service = FeishuWebsocketService(
                env={
                    "FEISHU_APP_ID": "app-id",
                    "FEISHU_APP_SECRET": "app-secret",
                },
                receipt_store=InMemoryReceiptStore(),
                runtime_handler=lambda envelope: {"status": "accepted", "events": []},
                delivery_client=FakeDeliveryClient(),
                client_config=FeishuWebsocketClientConfig(auto_reconnect=False),
            )

            def slow_fetch() -> FeishuWebsocketEndpoint:
                time.sleep(0.2)
                raise RuntimeError("boom")

            service.fetch_endpoint = slow_fetch  # type: ignore[method-assign]
            service._stop_event = asyncio.Event()

            ticks = 0

            async def ticker() -> None:
                nonlocal ticks
                start = time.perf_counter()
                while time.perf_counter() - start < 0.15:
                    ticks += 1
                    await asyncio.sleep(0.01)

            await asyncio.gather(service.run_forever(), ticker())

            self.assertGreaterEqual(ticks, 4)

        asyncio.run(exercise())

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

    def test_websocket_post_payload_extracts_visible_text_and_mentions(self) -> None:
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_ws_post_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_post_1",
                    }
                },
                "message": {
                    "message_id": "msg_ws_post_1",
                    "chat_id": "chat_post_1",
                    "chat_type": "group",
                    "message_type": "post",
                    "content": json.dumps(
                        {
                            "zh_cn": {
                                "title": "",
                                "content": [
                                    [
                                        {"tag": "at", "user_id": "bot_open_id", "user_name": "铁锤4916"},
                                        {"tag": "text", "text": " 现在几点？请直接回答。"},
                                    ]
                                ],
                            }
                        },
                        ensure_ascii=False,
                    ),
                    "mentions": [{"name": "铁锤4916", "key": "@_user_1"}],
                },
            },
        }

        event = parse_feishu_callback(payload)

        self.assertEqual(event.message_type, "post")
        self.assertEqual(event.mentions, ["铁锤4916"])
        self.assertEqual(event.text, "@铁锤4916 现在几点？请直接回答。")

    def test_websocket_post_payload_without_locale_wrapper_extracts_visible_text(self) -> None:
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_ws_post_2",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_post_2",
                    }
                },
                "message": {
                    "message_id": "msg_ws_post_2",
                    "chat_id": "chat_post_2",
                    "chat_type": "group",
                    "message_type": "post",
                    "content": json.dumps(
                        {
                            "title": "",
                            "content": [
                                [
                                    {"tag": "at", "user_id": "bot_open_id", "user_name": "铁锤4916"},
                                    {"tag": "text", "text": " 现在几点？请直接回答。"},
                                ]
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    "mentions": [{"name": "铁锤4916", "key": "@_user_1"}],
                },
            },
        }

        event = parse_feishu_callback(payload)

        self.assertEqual(event.message_type, "post")
        self.assertEqual(event.text, "@铁锤4916 现在几点？请直接回答。")

    def test_websocket_post_payload_with_null_text_falls_back_to_rich_text(self) -> None:
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_ws_post_null_text_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_post_null_text_1",
                    }
                },
                "message": {
                    "message_id": "msg_ws_post_null_text_1",
                    "chat_id": "chat_post_null_text_1",
                    "chat_type": "group",
                    "message_type": "post",
                    "content": json.dumps(
                        {
                            "text": None,
                            "zh_cn": {
                                "title": "",
                                "content": [
                                    [
                                        {"tag": "at", "user_id": "bot_open_id", "user_name": "铁锤4916"},
                                        {"tag": "text", "text": "现在几点？"},
                                    ]
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            },
        }

        event = parse_feishu_callback(payload)

        self.assertEqual(event.message_type, "post")
        self.assertEqual(event.text, "@铁锤4916现在几点？")

    def test_callback_payload_with_null_text_dict_falls_back_to_rich_text(self) -> None:
        payload = {
            "event_id": "evt_simple_null_text_1",
            "message_id": "msg_simple_null_text_1",
            "chat_id": "chat_simple_null_text_1",
            "user_id": "user_simple_null_text_1",
            "message_type": "post",
            "text": {
                "text": None,
                "content": [
                    [
                        {"tag": "text", "text": "hello"},
                        {"tag": "unknown", "value": "ignored"},
                        {"tag": "at", "user_name": "bot"},
                    ]
                ],
            },
        }

        event = parse_feishu_callback(payload)

        self.assertEqual(event.message_type, "post")
        self.assertEqual(event.text, "hello@bot")

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
            delivery_client=FakeDeliveryClient(),
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
                    delivery_client=FakeDeliveryClient(),
                )
                second = FeishuWebsocketService(
                    env={
                        "FEISHU_APP_ID": "app-id",
                        "FEISHU_APP_SECRET": "app-secret",
                        "FEISHU_WEBSOCKET_LOCK_PATH": lock_path,
                    },
                    receipt_store=InMemoryReceiptStore(),
                    runtime_handler=lambda envelope: {"status": "accepted", "events": []},
                    delivery_client=FakeDeliveryClient(),
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
        delivery = FakeDeliveryClient()
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

    def test_websocket_duplicate_frame_does_not_clobber_last_accepted_status(self) -> None:
        delivery = FakeDeliveryClient()
        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=lambda envelope: {
                "status": "accepted",
                "trace_id": envelope.trace_id,
                "session_id": "sess_frame_dup",
                "events": [
                    {
                        "event_type": "final",
                        "event_id": "evt_final_frame_dup",
                        "run_id": "run_frame_dup",
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
                "event_id": "evt_frame_dup_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"user_id": "user_frame_dup"},
                },
                "message": {
                    "message_id": "msg_frame_dup_1",
                    "chat_id": "chat_frame_dup_1",
                    "content": json.dumps({"text": "hello frame dup"}),
                },
            },
        }
        frame_bytes = build_event_frame(payload)

        asyncio.run(service.handle_frame_bytes(frame_bytes))
        self.assertEqual(service.state.last_status, "accepted")
        self.assertEqual(service.state.last_run_id, "run_frame_dup")
        self.assertEqual(service.state.last_session_id, "sess_frame_dup")

        asyncio.run(service.handle_frame_bytes(frame_bytes))

        self.assertEqual(service.state.last_status, "accepted")
        self.assertEqual(service.state.last_run_id, "run_frame_dup")
        self.assertEqual(service.state.last_session_id, "sess_frame_dup")
        self.assertEqual(len(delivery.payloads), 1)

    def test_websocket_service_suppresses_duplicate_message_id_across_event_replays(self) -> None:
        delivery = FakeDeliveryClient()
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

    def test_websocket_service_suppresses_same_text_replay_in_short_window(self) -> None:
        delivery = FakeDeliveryClient()
        store = InMemoryReceiptStore()
        handled_message_ids: list[str] = []

        def runtime_handler(envelope: object) -> dict[str, object]:
            handled_message_ids.append(envelope.message_id)
            return {
                "status": "accepted",
                "trace_id": envelope.trace_id,
                "session_id": "sess_semantic",
                "events": [
                    {
                        "event_type": "final",
                        "event_id": "evt_final_semantic",
                        "run_id": "run_semantic",
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
                "event_id": "evt_semantic_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_semantic_1",
                    }
                },
                "message": {
                    "message_id": "msg_semantic_1",
                    "chat_id": "chat_semantic_1",
                    "content": json.dumps({"text": "我现在有哪些自动任务？"}),
                },
            },
        }
        second_payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_semantic_2",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_semantic_1",
                    }
                },
                "message": {
                    "message_id": "msg_semantic_2",
                    "chat_id": "chat_semantic_1",
                    "content": json.dumps({"text": "我现在有哪些自动任务？"}),
                },
            },
        }

        first = service.handle_event_payload(first_payload)
        second = service.handle_event_payload(second_payload)

        self.assertEqual(first.status, "accepted")
        self.assertEqual(second.status, "ignored")
        self.assertEqual(second.body["reason"], "duplicate_semantic")
        self.assertEqual(handled_message_ids, ["msg_semantic_1"])
        self.assertEqual(len(delivery.payloads), 1)

    def test_websocket_service_stats_expose_last_runtime_session_and_run(self) -> None:
        delivery = FakeDeliveryClient()
        store = InMemoryReceiptStore()

        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=store,
            runtime_handler=lambda envelope: {
                "status": "accepted",
                "trace_id": envelope.trace_id,
                "session_id": "sess_last_runtime",
                "events": [
                    {
                        "event_type": "final",
                        "event_id": "evt_last_runtime",
                        "run_id": "run_last_runtime",
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
                "event_id": "evt_runtime_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_runtime_1",
                    }
                },
                "message": {
                    "message_id": "msg_runtime_1",
                    "chat_id": "chat_runtime_1",
                    "content": json.dumps({"text": "删掉 23:31 的那个任务"}),
                },
            },
        }

        result = service.handle_event_payload(payload)

        self.assertEqual(result.status, "accepted")
        stats = service.stats()
        self.assertIsNone(stats["last_trace_id"])
        self.assertEqual(stats["last_runtime_trace_id"], str(result.envelope.trace_id))
        self.assertEqual(stats["last_session_id"], "sess_last_runtime")
        self.assertEqual(stats["last_run_id"], "run_last_runtime")

    def test_websocket_service_converts_runtime_handler_exception_into_error_result(self) -> None:
        delivery = FakeDeliveryClient()
        store = InMemoryReceiptStore()

        def broken_runtime_handler(envelope: object) -> dict[str, object]:
            raise RuntimeError("boom")

        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=store,
            runtime_handler=broken_runtime_handler,
            delivery_client=delivery,
        )
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_runtime_error_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_runtime_error_1",
                    }
                },
                "message": {
                    "message_id": "msg_runtime_error_1",
                    "chat_id": "chat_runtime_error_1",
                    "content": json.dumps({"text": "查看现在有哪些自动任务"}),
                },
            },
        }

        result = service.handle_event_payload(payload)

        self.assertEqual(result.status, "error")
        self.assertEqual(result.body["error_code"], "RUNTIME_HANDLER_FAILED")
        self.assertEqual(result.body["message_id"], "msg_runtime_error_1")

    def test_websocket_service_ignores_blank_text_message(self) -> None:
        delivery = FakeDeliveryClient()
        store = InMemoryReceiptStore()
        handled = False

        def runtime_handler(envelope: object) -> dict[str, object]:
            nonlocal handled
            handled = True
            return {"status": "accepted", "events": []}

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
                "event_id": "evt_blank_1",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {
                        "user_id": "user_blank_1",
                    }
                },
                "message": {
                    "message_id": "msg_blank_1",
                    "chat_id": "chat_blank_1",
                    "content": json.dumps({"text": "   "}),
                },
            },
        }

        result = service.handle_event_payload(payload)

        self.assertEqual(result.status, "ignored")
        self.assertEqual(result.body["reason"], "blank_message")
        self.assertFalse(handled)

    def test_websocket_service_attaches_inbound_dedupe_key_to_final_delivery(self) -> None:
        delivery = FakeDeliveryClient()
        store = InMemoryReceiptStore()

        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=store,
            runtime_handler=lambda envelope: {
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
            },
            delivery_client=delivery,
        )
        payload = {
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

        service.handle_event_payload(payload)

        self.assertEqual(len(delivery.payloads), 1)
        self.assertEqual(
            delivery.payloads[0].dedupe_key,
            build_dedupe_key(
                channel_id="feishu",
                conversation_id="chat_replay_1",
                user_id="user_replay_1",
                message_id="msg_replay_1",
            ),
        )

    def test_websocket_service_ignores_app_originated_messages(self) -> None:
        delivery = FakeDeliveryClient()
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
        delivery = FakeDeliveryClient()
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
        delivery = FakeDeliveryClient()
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
        frame_bytes = build_event_frame(payload)

        ack_bytes = asyncio.run(service.handle_frame_bytes(frame_bytes))

        ack = Frame()
        ack.ParseFromString(ack_bytes)
        self.assertEqual(json.loads(ack.payload.decode("utf-8"))["code"], 200)
        self.assertEqual(len(delivery.payloads), 1)

    def test_running_websocket_service_acks_before_slow_runtime_completes(self) -> None:
        async def exercise() -> None:
            delivery = FakeDeliveryClient()
            started = threading.Event()
            release = threading.Event()

            def runtime_handler(envelope: object) -> dict[str, object]:
                started.set()
                release.wait(timeout=2)
                return {
                    "status": "accepted",
                    "trace_id": envelope.trace_id,
                    "session_id": "sess_ack_early",
                    "events": [
                        {
                            "event_type": "final",
                            "event_id": "evt_final_ack_early",
                            "run_id": "run_ack_early",
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
                receipt_store=InMemoryReceiptStore(),
                runtime_handler=runtime_handler,
                delivery_client=delivery,
            )
            service.state.running = True
            frame_bytes = build_event_frame(
                {
                    "schema": "2.0",
                    "header": {
                        "event_id": "evt_ack_early_1",
                        "event_type": "im.message.receive_v1",
                    },
                    "event": {
                        "sender": {
                            "sender_type": "user",
                            "sender_id": {
                                "user_id": "user_ack_early_1",
                            }
                        },
                        "message": {
                            "message_id": "msg_ack_early_1",
                            "chat_id": "chat_ack_early_1",
                            "content": json.dumps({"text": "hello"}),
                        },
                    },
                }
            )

            start = time.perf_counter()
            ack_bytes = await service.handle_frame_bytes(frame_bytes)
            elapsed = time.perf_counter() - start

            self.assertLess(elapsed, 0.1)
            ack = Frame()
            ack.ParseFromString(ack_bytes)
            self.assertEqual(json.loads(ack.payload.decode("utf-8"))["code"], 200)
            deadline = time.perf_counter() + 1
            while not started.is_set() and time.perf_counter() < deadline:
                await asyncio.sleep(0.01)
            self.assertTrue(started.is_set())
            self.assertEqual(len(delivery.payloads), 0)
            self.assertEqual(delivery.reactions, [("msg_ack_early_1", "OnIt")])

            release.set()
            await service.wait_for_idle()

            self.assertEqual(len(delivery.payloads), 1)
            self.assertEqual(service.state.last_status, "accepted")
            self.assertEqual(service.state.last_run_id, "run_ack_early")
            self.assertEqual(service.state.last_session_id, "sess_ack_early")

        asyncio.run(exercise())

    def test_websocket_service_updates_state_from_pong_frame(self) -> None:
        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=lambda envelope: {"status": "accepted", "events": []},
            delivery_client=FakeDeliveryClient(),
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

    def test_websocket_service_reports_controlled_error_when_endpoint_data_missing(self) -> None:
        service = FeishuWebsocketService(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=lambda envelope: {"status": "accepted", "events": []},
            delivery_client=FakeDeliveryClient(),
            endpoint_transport=lambda url, headers, body: {"code": 0, "msg": "ok", "data": None},
        )

        with self.assertRaisesRegex(RuntimeError, "FEISHU_WS_ENDPOINT_INVALID"):
            service.fetch_endpoint()




if __name__ == "__main__":
    unittest.main()
