import unittest

from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.interfaces.http.feishu_runtime_services import (
    build_feishu_delivery_client,
    build_feishu_websocket_service,
)
from tests.http_app_support import build_test_app


class FeishuRuntimeServicesTests(unittest.TestCase):
    def test_build_feishu_delivery_client_preserves_retry_policy(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime

        client = build_feishu_delivery_client(
            env=runtime.env,
            channels_config=runtime.channels_config,
        )

        self.assertEqual(
            client.retry_policy.progress_max_retries,
            runtime.channels_config.feishu.retry.progress_max_retries,
        )
        self.assertEqual(
            client.retry_policy.max_backoff_seconds,
            runtime.channels_config.feishu.retry.max_backoff_seconds,
        )

    def test_build_feishu_websocket_service_preserves_channel_routing_config(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime

        service = build_feishu_websocket_service(
            env=runtime.env,
            channels_config=runtime.channels_config,
            receipt_store=InMemoryReceiptStore(),
            runtime_handler=lambda envelope: {"status": "accepted"},
            delivery_client=runtime.feishu_delivery,
            lane_manager=runtime.lane_manager,
            run_history=runtime.run_history,
        )

        self.assertEqual(
            service.client_config.auto_reconnect,
            runtime.channels_config.feishu.websocket.auto_reconnect,
        )
        self.assertEqual(
            service.allowed_chat_types,
            set(runtime.channels_config.feishu.allowed_chat_types),
        )


if __name__ == "__main__":
    unittest.main()
