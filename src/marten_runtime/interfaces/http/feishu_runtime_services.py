from __future__ import annotations

from collections.abc import Mapping

from marten_runtime.channels.delivery_retry import DeliveryRetryPolicy
from marten_runtime.channels.feishu.delivery import FeishuDeliveryClient
from marten_runtime.channels.feishu.service import FeishuWebsocketService
from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.lanes import ConversationLaneManager


def build_feishu_delivery_client(
    *,
    env: Mapping[str, str],
    channels_config,
) -> FeishuDeliveryClient:
    return FeishuDeliveryClient(
        env=env,
        retry_policy=DeliveryRetryPolicy(
            progress_max_retries=channels_config.feishu.retry.progress_max_retries,
            final_max_retries=channels_config.feishu.retry.final_max_retries,
            error_max_retries=channels_config.feishu.retry.error_max_retries,
            base_backoff_seconds=channels_config.feishu.retry.base_backoff_seconds,
            max_backoff_seconds=channels_config.feishu.retry.max_backoff_seconds,
        ),
    )


def build_feishu_websocket_service(
    *,
    env: Mapping[str, str],
    channels_config,
    receipt_store: InMemoryReceiptStore,
    runtime_handler,
    delivery_client: FeishuDeliveryClient,
    lane_manager: ConversationLaneManager,
    run_history: InMemoryRunHistory | None,
) -> FeishuWebsocketService:
    return FeishuWebsocketService(
        env=env,
        receipt_store=receipt_store,
        runtime_handler=runtime_handler,
        delivery_client=delivery_client,
        allowed_chat_types=channels_config.feishu.allowed_chat_types,
        allowed_chat_ids=channels_config.feishu.allowed_chat_ids,
        client_config=channels_config.feishu.websocket.model_copy(
            update={"auto_reconnect": channels_config.feishu.websocket.auto_reconnect}
        ),
        lane_manager=lane_manager,
        run_history=run_history,
    )
