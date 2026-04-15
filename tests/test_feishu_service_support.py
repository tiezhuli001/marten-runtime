import time
import threading
import unittest
from unittest.mock import patch

from lark_oapi.ws.const import HEADER_MESSAGE_ID, HEADER_TYPE
from lark_oapi.ws.pb.pbbp2_pb2 import Frame

from marten_runtime.channels.feishu.models import FeishuInboundEvent
from marten_runtime.channels.feishu.service_support import (
    coerce_payload,
    default_endpoint_transport,
    elapsed_ms,
    first_value,
    headers_to_dict,
    is_self_message,
    normalize_message_text,
    redact_endpoint_url,
    to_client_config,
)


class FeishuServiceSupportTests(unittest.TestCase):
    def test_redact_endpoint_url_masks_sensitive_query_fields(self) -> None:
        url = 'wss://example/ws?access_key=secret&ticket=token&device_id=123'

        redacted = redact_endpoint_url(url)

        self.assertEqual(
            redacted,
            'wss://example/ws?access_key=REDACTED&ticket=REDACTED&device_id=123',
        )

    def test_coerce_payload_accepts_dict_bytes_and_text(self) -> None:
        self.assertEqual(coerce_payload({'ok': True}), {'ok': True})
        self.assertEqual(coerce_payload(b'{"ok": true}'), {'ok': True})
        self.assertEqual(coerce_payload('{"ok": true}'), {'ok': True})

    def test_to_client_config_accepts_both_key_styles(self) -> None:
        camel = to_client_config({'ReconnectCount': 2, 'PingInterval': 9, 'AutoReconnect': False})
        snake = to_client_config({'reconnect_count': 3, 'ping_interval_s': 7, 'auto_reconnect': True})

        self.assertEqual(camel.reconnect_count, 2)
        self.assertEqual(camel.ping_interval_s, 9)
        self.assertFalse(camel.auto_reconnect)
        self.assertEqual(snake.reconnect_count, 3)
        self.assertEqual(snake.ping_interval_s, 7)
        self.assertTrue(snake.auto_reconnect)

    def test_headers_to_dict_and_first_value_preserve_frame_metadata(self) -> None:
        frame = Frame()
        for key, value in ((HEADER_TYPE, 'event'), (HEADER_MESSAGE_ID, 'msg-1')):
            header = frame.headers.add()
            header.key = key
            header.value = value

        self.assertEqual(headers_to_dict(frame)[HEADER_MESSAGE_ID], 'msg-1')
        self.assertEqual(first_value(['x', 'y']), 'x')
        self.assertIsNone(first_value([]))

    def test_normalize_message_text_and_is_self_message_keep_semantic_rules(self) -> None:
        event = FeishuInboundEvent(
            event_id='evt_1',
            message_id='msg_1',
            chat_id='oc_1',
            chat_type='p2p',
            user_id='ou_1',
            text=' hello ',
            sender_type='app',
        )

        self.assertEqual(normalize_message_text('  Hello   WORLD  '), 'hello world')
        self.assertTrue(is_self_message(event))

    def test_elapsed_ms_is_non_negative(self) -> None:
        started_at = time.perf_counter()
        self.assertGreaterEqual(elapsed_ms(started_at), 0)

    def test_default_endpoint_transport_honors_cooperative_timeout_override(self) -> None:
        captured: list[float] = []

        def fake_post(url: str, headers: dict[str, str], json: dict, timeout: float):
            del url, headers, json
            captured.append(timeout)

            class _Response:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict[str, object]:
                    return {"code": 0}

            return _Response()

        with patch('marten_runtime.channels.feishu.service_support.httpx.post', fake_post):
            result = default_endpoint_transport(
                'https://example.test/endpoint',
                {'Authorization': 'Bearer x'},
                {'ok': True},
                timeout_seconds_override=1.25,
                deadline_monotonic=time.monotonic() + 5,
            )

        self.assertEqual(result, {'code': 0})
        self.assertEqual(captured, [1.25])

    def test_default_endpoint_transport_stops_before_http_call_when_cancelled(self) -> None:
        stop_event = threading.Event()
        stop_event.set()

        with self.assertRaises(TimeoutError) as ctx:
            default_endpoint_transport(
                'https://example.test/endpoint',
                {'Authorization': 'Bearer x'},
                {'ok': True},
                stop_event=stop_event,
            )

        self.assertIn('HTTP_CALL_CANCELLED', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
