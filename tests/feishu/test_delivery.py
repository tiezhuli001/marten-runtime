import json
import unittest
from unittest.mock import patch

from marten_runtime.channels.dead_letter import InMemoryDeadLetterQueue
from marten_runtime.channels.delivery_retry import DeliveryRetryPolicy
from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.channels.feishu.delivery import FeishuDeliveryClient, FeishuDeliveryPayload
from marten_runtime.channels.feishu.delivery_session import InMemoryFeishuDeliverySessionStore
from marten_runtime.channels.feishu.inbound import to_inbound_envelope
from marten_runtime.channels.feishu.models import FeishuInboundEvent
from marten_runtime.channels.feishu.service import FeishuWebsocketService
from marten_runtime.runtime.history import InMemoryRunHistory
from tests.support.feishu_builders import (
    FakeDeliveryClient,
    FlakyDeliveryTransport,
    RecordingDeliveryTransport,
)



class FeishuDeliveryTests(unittest.TestCase):
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
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["title"]["content"], "处理结果")
        self.assertEqual(card["header"]["template"], "indigo")
        card_text = card["body"]["elements"][0]["content"]
        self.assertEqual(card_text, "Your GitHub login is **tiezhuli001**.")
        self.assertNotIn("run_id=", card_text)
        self.assertNotIn("trace_id=", card_text)
        self.assertNotIn("event_id=", card_text)

    def test_final_delivery_payload_renders_generic_card_protocol_when_present(self) -> None:
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
                    "message_id": "om_message_2",
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
            chat_id="chat_card_1",
            event_type="final",
            event_id="evt_card_1",
            run_id="run_card_1",
            trace_id="trace_card_1",
            sequence=1,
            text=(
                "当前有 2 个启用中的任务。\n\n"
                "```feishu_card\n"
                '{"title":"启用中的任务","summary":"共 2 项","sections":[{"title":"任务列表","items":["日报同步：每天 22:20","失败样本回看：每 6 小时"]}]}\n'
                "```"
            ),
        )

        result = client.send(payload)

        self.assertTrue(result["ok"])
        card = json.loads(captured[1][2]["content"])
        elements = card["body"]["elements"]
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["title"]["content"], "启用中的任务")
        self.assertEqual(card["header"]["template"], "indigo")
        self.assertEqual(elements[0]["content"], "当前有 2 个启用中的任务。")
        self.assertEqual(elements[2]["content"], "**📌 共 2 项**")
        self.assertEqual(elements[3]["content"], "**🗂️ 任务列表**")
        self.assertIn("日报同步：每天 22:20", elements[4]["content"])
        self.assertIn("失败样本回看：每 6 小时", elements[4]["content"])
        self.assertNotIn("```feishu_card", json.dumps(card, ensure_ascii=False))

    def test_final_delivery_payload_falls_back_when_card_protocol_is_invalid(self) -> None:
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
                    "message_id": "om_message_3",
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
            chat_id="chat_card_2",
            event_type="final",
            event_id="evt_card_2",
            run_id="run_card_2",
            trace_id="trace_card_2",
            sequence=1,
            text='检查结果如下。\n\n```feishu_card\n{"title":["bad type"]}\n```',
        )

        result = client.send(payload)

        self.assertTrue(result["ok"])
        card = json.loads(captured[1][2]["content"])
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["body"]["elements"][0]["content"], '检查结果如下。\n\n```feishu_card\n{"title":["bad type"]}\n```')

    def test_progress_is_hidden_and_final_sends_one_card(self) -> None:
        transport = RecordingDeliveryTransport()
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

    def test_websocket_service_records_outbound_timing_for_visible_delivery_only(self) -> None:
        history = InMemoryRunHistory()
        run = history.start(
            session_id="sess_outbound",
            trace_id="trace_outbound",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_example",
        )

        class _TimingAwareDeliveryClient:
            def deliver(self, payload: FeishuDeliveryPayload) -> dict[str, object]:
                if payload.event_type == "progress":
                    return {"ok": True, "action": "skip"}
                return {"ok": True, "action": "send"}

        service = FeishuWebsocketService(
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=lambda envelope: {"status": "accepted", "events": []},
            delivery_client=_TimingAwareDeliveryClient(),
            run_history=history,
        )
        event = FeishuInboundEvent(
            event_id="evt_outbound",
            message_id="msg_outbound",
            chat_id="chat_outbound",
            user_id="user_outbound",
            text="hello",
        )
        envelope = to_inbound_envelope(event)
        body = {
            "events": [
                {
                    "event_type": "progress",
                    "event_id": "evt_progress",
                    "run_id": run.run_id,
                    "trace_id": run.trace_id,
                    "sequence": 1,
                    "payload": {"text": "running"},
                },
                {
                    "event_type": "final",
                    "event_id": "evt_final",
                    "run_id": run.run_id,
                    "trace_id": run.trace_id,
                    "sequence": 2,
                    "payload": {"text": "done"},
                },
            ]
        }

        with patch(
            "marten_runtime.channels.feishu.service.time.perf_counter",
            side_effect=[10.0, 11.0, 11.2],
        ):
            _, delivery_results = service._deliver_runtime_events(
                event=event,
                envelope=envelope,
                body=body,
            )

        self.assertEqual(len(delivery_results), 2)
        self.assertEqual(history.get(run.run_id).timings.outbound_ms, 199)
        self.assertEqual(history.get(run.run_id).timings.total_ms, 199)

    def test_build_delivery_payload_uses_actual_peak_usage_summary(self) -> None:
        history = InMemoryRunHistory()
        run = history.start(
            session_id="sess_usage_actual",
            trace_id="trace_usage_actual",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        run.actual_peak_input_tokens = 3198
        run.actual_peak_output_tokens = 82
        run.actual_peak_total_tokens = 3280

        service = FeishuWebsocketService(
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=lambda envelope: {"status": "accepted", "events": []},
            delivery_client=FakeDeliveryClient(),
            run_history=history,
        )
        event = FeishuInboundEvent(
            event_id="evt_usage_actual",
            message_id="msg_usage_actual",
            chat_id="chat_usage_actual",
            user_id="user_usage_actual",
            text="hello",
        )
        envelope = to_inbound_envelope(event)

        payload = service._build_delivery_payload(
            event=event,
            envelope=envelope,
            event_payload={
                "event_type": "final",
                "event_id": "evt_final_usage_actual",
                "run_id": run.run_id,
                "trace_id": run.trace_id,
                "sequence": 1,
                "payload": {"text": "done"},
            },
        )

        self.assertEqual(
            payload.usage_summary,
            {
                "input_tokens": 3198,
                "output_tokens": 82,
                "peak_tokens": 3280,
                "estimated_only": False,
            },
        )

    def test_build_delivery_payload_falls_back_to_preflight_usage_summary(self) -> None:
        history = InMemoryRunHistory()
        run = history.start(
            session_id="sess_usage_preflight",
            trace_id="trace_usage_preflight",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        run.initial_preflight_input_tokens_estimate = 3838
        run.peak_preflight_input_tokens_estimate = 3980

        service = FeishuWebsocketService(
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=lambda envelope: {"status": "accepted", "events": []},
            delivery_client=FakeDeliveryClient(),
            run_history=history,
        )
        event = FeishuInboundEvent(
            event_id="evt_usage_preflight",
            message_id="msg_usage_preflight",
            chat_id="chat_usage_preflight",
            user_id="user_usage_preflight",
            text="hello",
        )
        envelope = to_inbound_envelope(event)

        payload = service._build_delivery_payload(
            event=event,
            envelope=envelope,
            event_payload={
                "event_type": "final",
                "event_id": "evt_final_usage_preflight",
                "run_id": run.run_id,
                "trace_id": run.trace_id,
                "sequence": 1,
                "payload": {"text": "done"},
            },
        )

        self.assertEqual(
            payload.usage_summary,
            {"input_tokens": 3838, "output_tokens": None, "peak_tokens": 3980, "estimated_only": True},
        )

    def test_automation_final_delivery_suppresses_duplicate_window(self) -> None:
        transport = RecordingDeliveryTransport()
        client = FeishuDeliveryClient(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            transport=transport.post,
            session_store=InMemoryFeishuDeliverySessionStore(),
            enable_message_update=False,
        )

        first = client.deliver(
            FeishuDeliveryPayload(
                chat_id="chat_auto_1",
                event_type="final",
                event_id="evt_auto_1",
                run_id="run_auto_1",
                trace_id="trace_auto_1",
                sequence=1,
                text="digest",
                dedupe_key="feishu:chat_auto_1:2026-03-30",
            )
        )
        second = client.deliver(
            FeishuDeliveryPayload(
                chat_id="chat_auto_1",
                event_type="final",
                event_id="evt_auto_2",
                run_id="run_auto_2",
                trace_id="trace_auto_2",
                sequence=1,
                text="digest",
                dedupe_key="feishu:chat_auto_1:2026-03-30",
            )
        )

        self.assertEqual(first["action"], "send")
        self.assertEqual(second["action"], "skip")
        self.assertEqual(second["reason"], "duplicate_window")
        self.assertEqual(len(transport.sent), 1)

    def test_hidden_progress_does_not_block_error_send_when_update_unavailable(self) -> None:
        transport = RecordingDeliveryTransport()
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
        self.assertEqual(transport.sent[0][2]["msg_type"], "interactive")
        error_card = json.loads(transport.sent[0][2]["content"])
        self.assertEqual(error_card["header"]["title"]["content"], "处理失败")
        self.assertEqual(error_card["header"]["template"], "red")
        self.assertEqual(error_card["body"]["elements"][0]["content"], "failed")
        self.assertEqual(sessions.active_count(), 0)

    def test_hidden_progress_does_not_hit_transport_or_dead_letter(self) -> None:
        transport = FlakyDeliveryTransport({"progress": 3, "final": 4})
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
        transport = FlakyDeliveryTransport({"final": 6})
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
        transport = RecordingDeliveryTransport()
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

    def test_add_reaction_calls_feishu_reaction_api(self) -> None:
        transport = RecordingDeliveryTransport()
        client = FeishuDeliveryClient(
            env={
                "FEISHU_APP_ID": "app-id",
                "FEISHU_APP_SECRET": "app-secret",
            },
            transport=transport.post,
            session_store=InMemoryFeishuDeliverySessionStore(),
            enable_message_update=False,
        )

        result = client.add_reaction("om_source_1", "OnIt")

        self.assertTrue(result["ok"])
        self.assertEqual(result["message_id"], "om_source_1")
        self.assertEqual(result["emoji_type"], "OnIt")
        self.assertEqual(len(transport.reactions), 1)
        self.assertTrue(
            transport.reactions[0][0].endswith("/open-apis/im/v1/messages/om_source_1/reactions")
        )
        self.assertEqual(
            transport.reactions[0][2],
            {
                "reaction_type": {
                    "emoji_type": "OnIt",
                }
            },
        )




if __name__ == "__main__":
    unittest.main()
