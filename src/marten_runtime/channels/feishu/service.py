from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from uuid import uuid4

import httpx
import websockets
from lark_oapi.ws.const import (
    HEADER_BIZ_RT,
    HEADER_MESSAGE_ID,
    HEADER_SEQ,
    HEADER_SUM,
    HEADER_TRACE_ID,
    HEADER_TYPE,
)
from lark_oapi.ws.enum import FrameType, MessageType
from lark_oapi.ws.pb.pbbp2_pb2 import Frame

from marten_runtime.channels.feishu.delivery import FeishuDeliveryPayload
from marten_runtime.channels.feishu.inbound import parse_feishu_callback, to_inbound_envelope
from marten_runtime.channels.feishu.models import (
    FeishuDispatchResult,
    FeishuInboundEvent,
    FeishuWebsocketClientConfig,
    FeishuWebsocketEndpoint,
    FeishuWebsocketState,
)
from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.gateway.models import InboundEnvelope
from marten_runtime.runtime.lanes import ConversationLaneManager


RuntimeHandler = Callable[[InboundEnvelope], dict[str, object]]
EndpointTransport = Callable[[str, dict[str, str], dict[str, str]], dict[str, object]]
logger = logging.getLogger(__name__)


class FeishuWebsocketService:
    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        receipt_store: InMemoryReceiptStore,
        runtime_handler: RuntimeHandler,
        delivery_client: object,
        allowed_chat_types: list[str] | None = None,
        allowed_chat_ids: list[str] | None = None,
        endpoint_transport: EndpointTransport | None = None,
        connector: Callable[[str], Any] | None = None,
        client_config: FeishuWebsocketClientConfig | None = None,
        lane_manager: ConversationLaneManager | None = None,
    ) -> None:
        self.env = dict(env or {})
        self.receipt_store = receipt_store
        self.runtime_handler = runtime_handler
        self.delivery_client = delivery_client
        self.allowed_chat_types = {item for item in (allowed_chat_types or []) if item}
        self.allowed_chat_ids = {item for item in (allowed_chat_ids or []) if item}
        self.endpoint_transport = endpoint_transport or _default_endpoint_transport
        self.connector = connector or websockets.connect
        self.client_config = client_config or FeishuWebsocketClientConfig()
        self.lane_manager = lane_manager
        self.state = FeishuWebsocketState()
        self._fragments: dict[str, list[bytes]] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._lock_handle: object | None = None
        self._lock_path = self._resolve_lock_path()
        self._semantic_recent: dict[str, datetime] = {}
        self._semantic_duplicate_total = 0
        self._last_semantic_duplicate: dict[str, object] | None = None
        self._last_enqueued_lane: dict[str, object] | None = None
        self._dispatch_tasks: set[asyncio.Task[None]] = set()

    def fetch_endpoint(self) -> FeishuWebsocketEndpoint:
        app_id = self.env.get("FEISHU_APP_ID")
        app_secret = self.env.get("FEISHU_APP_SECRET")
        if not app_id or not app_secret:
            raise RuntimeError("FEISHU_APP_CREDENTIALS_MISSING")
        base_url = self.env.get("FEISHU_BASE_URL", "https://open.feishu.cn").rstrip("/")
        response = self.endpoint_transport(
            f"{base_url}/callback/ws/endpoint",
            {"locale": "zh"},
            {
                "AppID": app_id,
                "AppSecret": app_secret,
            },
        )
        if int(response.get("code", 0)) != 0:
            raise RuntimeError(f"FEISHU_WS_ENDPOINT_FAILED:{response.get('code')}:{response.get('msg', '')}")
        data = response.get("data")
        if not isinstance(data, Mapping) or not data.get("URL"):
            raise RuntimeError("FEISHU_WS_ENDPOINT_INVALID")
        endpoint = FeishuWebsocketEndpoint(
            url=str(data["URL"]),
            client_config=_to_client_config(data.get("ClientConfig", {})),
        )
        self.client_config = endpoint.client_config
        return endpoint

    async def start_background(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self._acquire_singleton_lock():
            self.state.running = False
            self.state.connected = False
            self.state.last_error = f"FEISHU_WEBSOCKET_LOCKED:{self._lock_path}"
            return
        self._stop_event = asyncio.Event()
        self.state.running = True
        self._task = asyncio.create_task(self.run_forever())

    async def stop_background(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        await self._cancel_dispatch_tasks()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._stop_event = None
        self.state.running = False
        self.state.connected = False
        self._release_singleton_lock()

    async def run_forever(self) -> None:
        attempts = 0
        stop_event = self._stop_event
        if stop_event is None:
            stop_event = asyncio.Event()
            self._stop_event = stop_event
        while not stop_event.is_set():
            try:
                endpoint = await asyncio.to_thread(self.fetch_endpoint)
                self._update_endpoint_state(endpoint.url)
                async with self.connector(endpoint.url) as websocket:
                    self.state.connected = True
                    attempts = 0
                    ping_task = asyncio.create_task(self._ping_loop(websocket))
                    try:
                        while not stop_event.is_set():
                            frame_bytes = await websocket.recv()
                            ack = await self.handle_frame_bytes(frame_bytes)
                            if ack is not None:
                                await websocket.send(ack)
                    finally:
                        ping_task.cancel()
                        try:
                            await ping_task
                        except asyncio.CancelledError:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state.connected = False
                self.state.last_error = f"{type(exc).__name__}:{exc}"
                logger.exception("feishu websocket loop failed")
                attempts += 1
                self.state.reconnect_attempts = attempts
                if not self.client_config.auto_reconnect:
                    break
                if self.client_config.reconnect_count >= 0 and attempts > self.client_config.reconnect_count:
                    break
                await asyncio.sleep(max(self.client_config.reconnect_interval_s, 1))
        self.state.connected = False
        self.state.running = False
        self._release_singleton_lock()

    async def handle_frame_bytes(self, frame_bytes: bytes) -> bytes | None:
        frame = Frame()
        frame.ParseFromString(frame_bytes)
        frame_type = FrameType(frame.method)
        if frame_type == FrameType.CONTROL:
            self._handle_control_frame(frame)
            return None
        payload = self._resolve_payload(frame)
        if payload is None:
            return None
        headers = _headers_to_dict(frame)
        message_type = headers.get(HEADER_TYPE)
        if message_type != MessageType.EVENT.value:
            return self._build_ack_frame(frame, {"code": 200})
        self.state.last_message_id = headers.get(HEADER_MESSAGE_ID)
        self.state.last_trace_id = headers.get(HEADER_TRACE_ID)
        if self.state.running:
            self._schedule_dispatch(payload)
            return self._build_ack_frame(frame, {"code": 200})
        result = await asyncio.to_thread(self.handle_event_payload, payload)
        if self._should_promote_result_state(result):
            self.state.last_status = result.status
        return self._build_ack_frame(frame, {"code": 200})

    def handle_event_payload(self, payload: dict[str, object] | bytes | str) -> FeishuDispatchResult:
        payload_dict = _coerce_payload(payload)
        event_type = str(payload_dict.get("header", {}).get("event_type") or "")
        if event_type and event_type != "im.message.receive_v1":
            return FeishuDispatchResult(
                status="ignored",
                body={"status": "ignored", "reason": "unsupported_event_type", "event_type": event_type},
            )
        event = parse_feishu_callback(payload_dict)
        if _is_self_message(event):
            self.state.last_event_id = event.message_id or event.event_id
            self.state.last_event_at = datetime.now(timezone.utc)
            return FeishuDispatchResult(
                status="ignored",
                body={
                    "status": "ignored",
                    "reason": "self_message",
                    "event_id": event.event_id,
                    "message_id": event.message_id,
                    "sender_type": event.sender_type,
                },
                event=event,
            )
        if not event.text.strip():
            self.state.last_event_id = event.message_id or event.event_id
            self.state.last_event_at = datetime.now(timezone.utc)
            return FeishuDispatchResult(
                status="ignored",
                body={
                    "status": "ignored",
                    "reason": "blank_message",
                    "event_id": event.event_id,
                    "message_id": event.message_id,
                    "chat_id": event.chat_id,
                },
                event=event,
            )
        if not self._is_allowed_chat(event):
            self.state.last_event_id = event.message_id or event.event_id
            self.state.last_event_at = datetime.now(timezone.utc)
            return FeishuDispatchResult(
                status="ignored",
                body={
                    "status": "ignored",
                    "reason": "chat_not_allowed",
                    "chat_id": event.chat_id,
                    "chat_type": event.chat_type,
                },
                event=event,
            )
        envelope = to_inbound_envelope(event)
        self.state.last_runtime_trace_id = envelope.trace_id
        claim = self.receipt_store.claim(
            channel_id=envelope.channel_id,
            dedupe_key=envelope.dedupe_key,
            trace_id=envelope.trace_id,
            conversation_id=envelope.conversation_id,
            message_id=envelope.message_id,
        )
        if not claim.claimed:
            self.state.last_event_id = claim.record.message_id
            self.state.last_event_at = datetime.now(timezone.utc)
            return FeishuDispatchResult(
                status="ignored",
                body={
                    "status": "ignored",
                    "reason": "duplicate",
                    "dedupe_key": envelope.dedupe_key,
                    "trace_id": claim.record.trace_id,
                    "conversation_id": claim.record.conversation_id,
                    "message_id": claim.record.message_id,
                },
                envelope=envelope,
                event=event,
            )
        semantic_duplicate = self._claim_semantic_replay(event)
        if semantic_duplicate is not None:
            self.state.last_event_id = event.message_id or event.event_id
            self.state.last_event_at = datetime.now(timezone.utc)
            return semantic_duplicate
        self._add_ack_reaction(event.message_id)
        lane_lease = None
        if self.lane_manager is not None:
            lane_lease = self.lane_manager.acquire(
                channel_id=envelope.channel_id,
                conversation_id=envelope.conversation_id,
                run_id=f"run_{uuid4().hex[:8]}",
                trace_id=envelope.trace_id,
            )
            current_stats = self.lane_manager.stats()
            self._last_enqueued_lane = current_stats.get("last_enqueued_lane")
        try:
            body = self.runtime_handler(envelope)
        except Exception as exc:
            logger.exception("feishu runtime handler failed")
            self.state.last_event_id = event.message_id or event.event_id
            self.state.last_event_at = datetime.now(timezone.utc)
            self.state.last_error = f"{exc.__class__.__name__}:{exc}"
            return FeishuDispatchResult(
                status="error",
                body={
                    "status": "error",
                    "error_code": "RUNTIME_HANDLER_FAILED",
                    "message": str(exc),
                    "message_id": event.message_id,
                    "event_id": event.event_id,
                    "chat_id": event.chat_id,
                },
                envelope=envelope,
                event=event,
            )
        finally:
            if lane_lease is not None:
                self.lane_manager.release(
                    channel_id=envelope.channel_id,
                    conversation_id=envelope.conversation_id,
                    run_id=lane_lease.run_id,
                )
        self.state.last_session_id = str(body.get("session_id", "")).strip() or None
        last_run_id = None
        for event_payload in body.get("events", []):
            if isinstance(event_payload, Mapping):
                candidate = str(event_payload.get("run_id", "")).strip()
                if candidate:
                    last_run_id = candidate
        delivery_results: list[dict[str, object]] = []
        for event_payload in body.get("events", []):
            delivery_results.append(
                self.delivery_client.deliver(
                    FeishuDeliveryPayload(
                        chat_id=event.chat_id,
                        event_type=str(event_payload["event_type"]),
                        event_id=str(event_payload["event_id"]),
                        run_id=str(event_payload["run_id"]),
                        trace_id=str(event_payload["trace_id"]),
                        sequence=int(event_payload["sequence"]),
                        text=str(event_payload["payload"]["text"]),
                        dedupe_key=(
                            envelope.dedupe_key
                            if str(event_payload["event_type"]) in {"final", "error"}
                            else None
                        ),
                    )
                )
            )
        self.state.last_run_id = last_run_id
        self.state.last_runtime_trace_id = envelope.trace_id
        self.state.last_event_id = event.message_id or event.event_id
        self.state.last_event_at = datetime.now(timezone.utc)
        return FeishuDispatchResult(
            status="accepted",
            body=body,
            envelope=envelope,
            event=event,
            delivery_results=delivery_results,
        )

    def stats(self) -> dict[str, object]:
        return {
            "running": self.state.running,
            "connected": self.state.connected,
            "lock_acquired": self.state.lock_acquired,
            "endpoint_url": _redact_endpoint_url(self.state.endpoint_url),
            "service_id": self.state.service_id,
            "connection_id": self.state.connection_id,
            "reconnect_attempts": self.state.reconnect_attempts,
            "last_error": self.state.last_error,
            "last_message_id": self.state.last_message_id,
            "last_trace_id": self.state.last_trace_id,
            "last_runtime_trace_id": self.state.last_runtime_trace_id,
            "last_session_id": self.state.last_session_id,
            "last_run_id": self.state.last_run_id,
            "last_event_id": self.state.last_event_id,
            "last_status": self.state.last_status,
            "last_event_at": self.state.last_event_at.isoformat() if self.state.last_event_at else None,
            "allowed_chat_types": sorted(self.allowed_chat_types),
            "allowed_chat_ids": sorted(self.allowed_chat_ids),
            "client_config": self.client_config.model_dump(),
            "semantic_duplicate_total": self._semantic_duplicate_total,
            "last_semantic_duplicate": self._last_semantic_duplicate,
            "queued_lane_count": self.lane_manager.stats().get("queued_lane_count", 0) if self.lane_manager else 0,
            "queued_items_total": self.lane_manager.stats().get("queued_items_total", 0) if self.lane_manager else 0,
            "last_enqueued_lane": self._last_enqueued_lane,
            "inflight_dispatch_count": len(self._dispatch_tasks),
        }

    async def wait_for_idle(self) -> None:
        while self._dispatch_tasks:
            tasks = tuple(self._dispatch_tasks)
            await asyncio.gather(*tasks, return_exceptions=True)

    def _resolve_lock_path(self) -> str:
        override = self.env.get("FEISHU_WEBSOCKET_LOCK_PATH")
        if override:
            return override
        app_id = self.env.get("FEISHU_APP_ID", "default")
        return str(Path("/tmp") / f"marten-runtime-feishu-{app_id}.lock")

    def _acquire_singleton_lock(self) -> bool:
        if self._lock_handle is not None:
            self.state.lock_acquired = True
            return True
        Path(self._lock_path).parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            self.state.lock_acquired = False
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._lock_handle = handle
        self.state.lock_acquired = True
        return True

    def _release_singleton_lock(self) -> None:
        handle = self._lock_handle
        if handle is None:
            self.state.lock_acquired = False
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._lock_handle = None
            self.state.lock_acquired = False

    async def _ping_loop(self, websocket: Any) -> None:
        stop_event = self._stop_event
        if stop_event is None:
            return
        while not stop_event.is_set():
            await asyncio.sleep(max(self.client_config.ping_interval_s, 1))
            frame = Frame()
            header = frame.headers.add()
            header.key = HEADER_TYPE
            header.value = MessageType.PING.value
            frame.service = int(self.state.service_id or 0)
            frame.method = FrameType.CONTROL.value
            frame.SeqID = 0
            frame.LogID = 0
            await websocket.send(frame.SerializeToString())

    def _schedule_dispatch(self, payload: dict[str, object] | bytes | str) -> None:
        task = asyncio.create_task(self._dispatch_event_payload(payload))
        self._dispatch_tasks.add(task)
        task.add_done_callback(self._dispatch_tasks.discard)

    async def _dispatch_event_payload(self, payload: dict[str, object] | bytes | str) -> None:
        try:
            result = await asyncio.to_thread(self.handle_event_payload, payload)
        except Exception:
            logger.exception("feishu background dispatch failed")
            return
        if self._should_promote_result_state(result):
            self.state.last_status = result.status

    async def _cancel_dispatch_tasks(self) -> None:
        if not self._dispatch_tasks:
            return
        tasks = tuple(self._dispatch_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _handle_control_frame(self, frame: Frame) -> None:
        headers = _headers_to_dict(frame)
        message_type = headers.get(HEADER_TYPE)
        if message_type != MessageType.PONG.value or not frame.payload:
            return
        self.client_config = _to_client_config(json.loads(frame.payload.decode("utf-8")))

    def _resolve_payload(self, frame: Frame) -> bytes | None:
        headers = _headers_to_dict(frame)
        message_id = headers.get(HEADER_MESSAGE_ID)
        total = int(headers.get(HEADER_SUM, "1"))
        seq = int(headers.get(HEADER_SEQ, "0"))
        if total <= 1 or message_id is None:
            return frame.payload
        parts = self._fragments.get(message_id)
        if parts is None:
            parts = [b""] * total
            self._fragments[message_id] = parts
        parts[seq] = frame.payload
        if any(not part for part in parts):
            return None
        payload = b"".join(parts)
        del self._fragments[message_id]
        return payload

    def _build_ack_frame(self, source_frame: Frame, response: dict[str, object]) -> bytes:
        header = source_frame.headers.add()
        header.key = HEADER_BIZ_RT
        header.value = "0"
        source_frame.payload = json.dumps(response, ensure_ascii=True).encode("utf-8")
        return source_frame.SerializeToString()

    def _update_endpoint_state(self, url: str) -> None:
        self.state.endpoint_url = url
        query = parse_qs(urlparse(url).query)
        self.state.connection_id = _first_value(query.get("device_id"))
        self.state.service_id = _first_value(query.get("service_id"))

    def _is_allowed_chat(self, event: FeishuInboundEvent) -> bool:
        if self.allowed_chat_types and event.chat_type not in self.allowed_chat_types:
            return False
        if self.allowed_chat_ids and event.chat_id not in self.allowed_chat_ids:
            return False
        return True

    def _should_promote_result_state(self, result: FeishuDispatchResult) -> bool:
        if result.status != "ignored":
            return True
        reason = None
        if isinstance(result.body, Mapping):
            candidate = result.body.get("reason")
            if candidate is not None:
                reason = str(candidate)
        return reason not in {"duplicate", "duplicate_semantic"}

    def _claim_semantic_replay(self, event: FeishuInboundEvent) -> FeishuDispatchResult | None:
        normalized_text = _normalize_message_text(event.text)
        if not normalized_text:
            return None
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=5)
        self._semantic_recent = {
            key: seen_at for key, seen_at in self._semantic_recent.items() if seen_at >= cutoff
        }
        semantic_key = f"{event.chat_id}:{event.user_id}:{normalized_text}"
        seen_at = self._semantic_recent.get(semantic_key)
        if seen_at is not None:
            self._semantic_duplicate_total += 1
            self._last_semantic_duplicate = {
                "chat_id": event.chat_id,
                "user_id": event.user_id,
                "message_id": event.message_id,
                "event_id": event.event_id,
                "text": event.text,
                "first_seen_at": seen_at.isoformat(),
                "duplicate_seen_at": now.isoformat(),
            }
            return FeishuDispatchResult(
                status="ignored",
                body={
                    "status": "ignored",
                    "reason": "duplicate_semantic",
                    "chat_id": event.chat_id,
                    "message_id": event.message_id,
                    "event_id": event.event_id,
                },
                event=event,
            )
        self._semantic_recent[semantic_key] = now
        return None

    def _add_ack_reaction(self, message_id: str) -> None:
        if not message_id:
            return
        add_reaction = getattr(self.delivery_client, "add_reaction", None)
        if not callable(add_reaction):
            return
        try:
            add_reaction(message_id, "OnIt")
        except Exception:
            logger.exception("feishu add reaction failed")


def _default_endpoint_transport(url: str, headers: dict[str, str], body: dict[str, str]) -> dict[str, object]:
    response = httpx.post(url, headers=headers, json=body, timeout=30)
    response.raise_for_status()
    return response.json()


def _redact_endpoint_url(url: str | None) -> str | None:
    if not url:
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key in ("access_key", "ticket"):
        if key in query:
            query[key] = ["REDACTED"]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _headers_to_dict(frame: Frame) -> dict[str, str]:
    return {item.key: item.value for item in frame.headers}


def _coerce_payload(payload: dict[str, object] | bytes | str) -> dict[str, object]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        return json.loads(payload.decode("utf-8"))
    return json.loads(payload)


def _to_client_config(payload: Mapping[str, object]) -> FeishuWebsocketClientConfig:
    return FeishuWebsocketClientConfig(
        reconnect_count=int(payload.get("ReconnectCount", payload.get("reconnect_count", -1))),
        reconnect_interval_s=int(payload.get("ReconnectInterval", payload.get("reconnect_interval_s", 5))),
        reconnect_nonce_s=int(payload.get("ReconnectNonce", payload.get("reconnect_nonce_s", 0))),
        ping_interval_s=int(payload.get("PingInterval", payload.get("ping_interval_s", 120))),
        auto_reconnect=bool(payload.get("AutoReconnect", payload.get("auto_reconnect", True))),
    )


def _is_self_message(event: FeishuInboundEvent) -> bool:
    return event.sender_type.lower() == "app"


def _first_value(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


def _normalize_message_text(text: str) -> str:
    return " ".join(text.strip().lower().split())
