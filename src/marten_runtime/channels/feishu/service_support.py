from __future__ import annotations

import json
from collections.abc import Mapping
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from lark_oapi.ws.pb.pbbp2_pb2 import Frame

from marten_runtime.channels.feishu.delivery import FeishuDeliveryPayload
from marten_runtime.channels.feishu.models import (
    FeishuInboundEvent,
    FeishuWebsocketClientConfig,
)
from marten_runtime.channels.feishu.usage import build_usage_summary_from_history
from marten_runtime.runtime.timing import elapsed_ms



def default_endpoint_transport(
    url: str, headers: dict[str, str], body: dict[str, str]
) -> dict[str, object]:
    response = httpx.post(url, headers=headers, json=body, timeout=30)
    response.raise_for_status()
    return response.json()


def redact_endpoint_url(url: str | None) -> str | None:
    if not url:
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key in ("access_key", "ticket"):
        if key in query:
            query[key] = ["REDACTED"]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def headers_to_dict(frame: Frame) -> dict[str, str]:
    return {item.key: item.value for item in frame.headers}


def coerce_payload(payload: dict[str, object] | bytes | str) -> dict[str, object]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        return json.loads(payload.decode("utf-8"))
    return json.loads(payload)


def to_client_config(payload: Mapping[str, object]) -> FeishuWebsocketClientConfig:
    return FeishuWebsocketClientConfig(
        reconnect_count=int(payload.get("ReconnectCount", payload.get("reconnect_count", -1))),
        reconnect_interval_s=int(payload.get("ReconnectInterval", payload.get("reconnect_interval_s", 5))),
        reconnect_nonce_s=int(payload.get("ReconnectNonce", payload.get("reconnect_nonce_s", 0))),
        ping_interval_s=int(payload.get("PingInterval", payload.get("ping_interval_s", 120))),
        auto_reconnect=bool(payload.get("AutoReconnect", payload.get("auto_reconnect", True))),
    )


def is_self_message(event: FeishuInboundEvent) -> bool:
    return event.sender_type.lower() == "app"


def first_value(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


def normalize_message_text(text: str) -> str:
    return " ".join(text.strip().lower().split())

def bind_queue_observation_to_body(
    *,
    run_history: object | None,
    body: Mapping[str, object],
    lane_lease: object,
) -> None:
    if run_history is None:
        return
    for event in body.get("events", []):
        if not isinstance(event, Mapping):
            continue
        run_id = str(event.get("run_id", "")).strip()
        if not run_id:
            continue
        run_history.set_queue_diagnostics(
            run_id,
            queue_depth_at_enqueue=lane_lease.queue_depth_at_enqueue,
            queue_wait_ms=lane_lease.queue_wait_ms,
        )


def build_delivery_payload(
    *,
    event: FeishuInboundEvent,
    envelope: object,
    event_payload: Mapping[str, object],
    run_history: object | None,
) -> FeishuDeliveryPayload:
    event_type = str(event_payload["event_type"])
    payload_body = event_payload.get("payload")
    text = str(payload_body.get("text", "")) if isinstance(payload_body, Mapping) else ""
    run_id = str(event_payload["run_id"])
    return FeishuDeliveryPayload(
        chat_id=event.chat_id,
        event_type=event_type,
        event_id=str(event_payload["event_id"]),
        run_id=run_id,
        trace_id=str(event_payload["trace_id"]),
        sequence=int(event_payload["sequence"]),
        text=text,
        dedupe_key=getattr(envelope, "dedupe_key", None) if event_type in {"final", "error"} else None,
        usage_summary=(
            build_usage_summary_from_history(run_history, run_id)
            if run_history is not None and event_type in {"final", "error"}
            else None
        ),
    )
