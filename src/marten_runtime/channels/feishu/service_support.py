from __future__ import annotations

import json
import time
from collections.abc import Mapping
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from lark_oapi.ws.pb.pbbp2_pb2 import Frame

from marten_runtime.channels.feishu.models import (
    FeishuInboundEvent,
    FeishuWebsocketClientConfig,
)


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


def elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))
