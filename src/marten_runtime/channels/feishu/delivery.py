from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from urllib import error, request as urllib_request

from pydantic import BaseModel

from marten_runtime.channels.dead_letter import InMemoryDeadLetterQueue
from marten_runtime.channels.delivery_retry import DeliveryRetryPolicy
from marten_runtime.channels.feishu.delivery_session import InMemoryFeishuDeliverySessionStore
from marten_runtime.channels.feishu import rendering as feishu_rendering
from marten_runtime.runtime.cooperative_stop import interruptible_sleep, raise_if_interrupted


class FeishuDeliveryPayload(BaseModel):
    chat_id: str
    event_type: str
    event_id: str
    run_id: str
    trace_id: str
    sequence: int
    visibility: str = "channel"
    text: str
    card: dict[str, object] | None = None
    dedupe_key: str | None = None
    usage_summary: dict[str, int | None | bool] | None = None


Transport = Callable[[str, dict[str, str], dict], dict]
logger = logging.getLogger(__name__)


def _perform_request(url: str, headers: dict[str, str], body: dict, *, method: str) -> dict:
    payload = json.dumps(body).encode("utf-8")
    req = urllib_request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib_request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:  # pragma: no cover - exercised through integration later
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"feishu_http_error:{exc.code}:{detail}") from exc
    except error.URLError as exc:  # pragma: no cover - exercised through integration later
        raise RuntimeError(f"feishu_transport_error:{exc.reason}") from exc


def _default_transport(url: str, headers: dict[str, str], body: dict) -> dict:
    return _perform_request(url, headers, body, method="POST")


def _default_update_transport(url: str, headers: dict[str, str], body: dict) -> dict:
    return _perform_request(url, headers, body, method="PUT")


class FeishuDeliveryClient:
    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        transport: Transport | None = None,
        update_transport: Transport | None = None,
        session_store: InMemoryFeishuDeliverySessionStore | None = None,
        enable_message_update: bool = True,
        retry_policy: DeliveryRetryPolicy | None = None,
        dead_letter_queue: InMemoryDeadLetterQueue | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.env = env if env is not None else os.environ
        self.transport = transport or _default_transport
        self.update_transport = update_transport or _default_update_transport
        self.session_store = session_store or InMemoryFeishuDeliverySessionStore()
        self.enable_message_update = enable_message_update
        self.retry_policy = retry_policy or DeliveryRetryPolicy()
        self.dead_letter_queue = dead_letter_queue or InMemoryDeadLetterQueue()
        self.sleeper = sleeper or time.sleep
        self._tenant_access_token: str | None = None
        self._tenant_access_token_expire_at: float = 0.0
        self._delivered_keys: set[str] = set()

    def add_reaction(self, message_id: str, emoji_type: str = "OnIt") -> dict[str, object]:
        tenant_access_token = self._get_tenant_access_token()
        base_url = self.env.get("FEISHU_BASE_URL", "https://open.feishu.cn").rstrip("/")
        response = self.transport(
            f"{base_url}/open-apis/im/v1/messages/{message_id}/reactions",
            {
                "Authorization": f"Bearer {tenant_access_token}",
                "Content-Type": "application/json",
            },
            {
                "reaction_type": {
                    "emoji_type": emoji_type,
                }
            },
        )
        if response.get("code", 0) != 0:
            raise RuntimeError(f"feishu_reaction_failed:{response.get('code')}:{response.get('msg', '')}")
        logger.info("feishu_reaction action=add emoji_type=%s source_message_id=%s", emoji_type, message_id)
        return {
            "ok": True,
            "message_id": message_id,
            "emoji_type": emoji_type,
        }

    def send(self, payload: FeishuDeliveryPayload) -> dict:
        tenant_access_token = self._get_tenant_access_token()
        base_url = self.env.get("FEISHU_BASE_URL", "https://open.feishu.cn").rstrip("/")
        message_body = self._build_message_body(payload)
        response = self.transport(
            f"{base_url}/open-apis/im/v1/messages?receive_id_type=chat_id",
            {
                "Authorization": f"Bearer {tenant_access_token}",
                "Content-Type": "application/json",
            },
            {
                "receive_id": payload.chat_id,
                **message_body,
            },
        )
        if response.get("code", 0) != 0:
            raise RuntimeError(f"feishu_delivery_failed:{response.get('code')}:{response.get('msg', '')}")
        result = {
            "ok": True,
            "action": "send",
            "event_type": payload.event_type,
            "event_id": payload.event_id,
            "run_id": payload.run_id,
            "trace_id": payload.trace_id,
            "sequence": payload.sequence,
            "chat_id": payload.chat_id,
            "message_id": response.get("data", {}).get("message_id"),
        }
        self._log_delivery_event("send", payload, result["message_id"])
        return result

    def update(self, message_id: str, payload: FeishuDeliveryPayload) -> dict:
        if not self.enable_message_update:
            raise RuntimeError("FEISHU_MESSAGE_UPDATE_DISABLED")
        tenant_access_token = self._get_tenant_access_token()
        base_url = self.env.get("FEISHU_BASE_URL", "https://open.feishu.cn").rstrip("/")
        message_body = self._build_message_body(payload)
        response = self.update_transport(
            f"{base_url}/open-apis/im/v1/messages/{message_id}",
            {
                "Authorization": f"Bearer {tenant_access_token}",
                "Content-Type": "application/json",
            },
            message_body,
        )
        if response.get("code", 0) != 0:
            raise RuntimeError(f"feishu_delivery_failed:{response.get('code')}:{response.get('msg', '')}")
        result = {
            "ok": True,
            "action": "update",
            "event_type": payload.event_type,
            "event_id": payload.event_id,
            "run_id": payload.run_id,
            "trace_id": payload.trace_id,
            "sequence": payload.sequence,
            "chat_id": payload.chat_id,
            "message_id": response.get("data", {}).get("message_id", message_id),
        }
        self._log_delivery_event("update", payload, result["message_id"])
        return result

    def deliver(
        self,
        payload: FeishuDeliveryPayload,
        *,
        cooperative_context: dict | None = None,
    ) -> dict:
        if payload.event_type == "progress":
            self._log_delivery_event("skip", payload, None, reason="progress_hidden")
            return {
                "ok": True,
                "action": "skip",
                "event_type": payload.event_type,
                "event_id": payload.event_id,
                "run_id": payload.run_id,
                "trace_id": payload.trace_id,
                "sequence": payload.sequence,
                "chat_id": payload.chat_id,
                "message_id": None,
                "retry_count": 0,
            }
        if payload.event_type == "final" and payload.dedupe_key:
            if payload.dedupe_key in self._delivered_keys:
                self._log_delivery_event("skip", payload, None, reason="duplicate_window")
                return {
                    "ok": True,
                    "action": "skip",
                    "reason": "duplicate_window",
                    "event_type": payload.event_type,
                    "event_id": payload.event_id,
                    "run_id": payload.run_id,
                    "trace_id": payload.trace_id,
                    "sequence": payload.sequence,
                    "chat_id": payload.chat_id,
                    "message_id": None,
                    "retry_count": 0,
                }
        session = self.session_store.start_or_get(
            channel_id="feishu",
            conversation_id=payload.chat_id,
            run_id=payload.run_id,
            trace_id=payload.trace_id,
        )
        result = self._deliver_with_retry(
            payload,
            session.message_id,
            cooperative_context=cooperative_context,
        )
        if not result["ok"]:
            if payload.event_type in {"final", "error"}:
                self.session_store.finalize_error(
                    channel_id="feishu",
                    conversation_id=payload.chat_id,
                    run_id=payload.run_id,
                    trace_id=payload.trace_id,
                    message_id=str(result.get("message_id") or session.message_id or ""),
                    event_id=payload.event_id,
                    sequence=payload.sequence,
                )
            return result
        if payload.event_type == "progress":
            self.session_store.append_progress(
                channel_id="feishu",
                conversation_id=payload.chat_id,
                run_id=payload.run_id,
                trace_id=payload.trace_id,
                message_id=str(result["message_id"]),
                event_id=payload.event_id,
                sequence=payload.sequence,
            )
            return result
        if payload.event_type == "final":
            if payload.dedupe_key:
                self._delivered_keys.add(payload.dedupe_key)
            self.session_store.finalize_success(
                channel_id="feishu",
                conversation_id=payload.chat_id,
                run_id=payload.run_id,
                trace_id=payload.trace_id,
                message_id=str(result["message_id"]),
                event_id=payload.event_id,
                sequence=payload.sequence,
            )
            return result
        if payload.event_type == "error":
            self.session_store.finalize_error(
                channel_id="feishu",
                conversation_id=payload.chat_id,
                run_id=payload.run_id,
                trace_id=payload.trace_id,
                message_id=str(result["message_id"]),
                event_id=payload.event_id,
                sequence=payload.sequence,
            )
        return result

    def _deliver_with_retry(
        self,
        payload: FeishuDeliveryPayload,
        message_id: str | None,
        *,
        cooperative_context: dict | None = None,
    ) -> dict:
        retry_count = 0
        limit = self.retry_policy.retry_limit_for(payload.event_type)
        while True:
            try:
                raise_if_interrupted(
                    stop_event=(cooperative_context or {}).get("stop_event"),
                    deadline_monotonic=(cooperative_context or {}).get("deadline_monotonic"),
                    cancelled_message="FEISHU_DELIVERY_CANCELLED",
                    timed_out_message="FEISHU_DELIVERY_TIMED_OUT",
                )
                result = self._attempt_delivery(payload, message_id)
                result["retry_count"] = retry_count
                result["ok"] = True
                return result
            except (RuntimeError, TimeoutError) as exc:
                if retry_count >= limit:
                    dead_letter = self.dead_letter_queue.record(
                        channel_id="feishu",
                        conversation_id=payload.chat_id,
                        payload=payload,
                        attempts=retry_count + 1,
                        error=str(exc),
                    )
                    return {
                        "ok": False,
                        "action": "send" if not message_id else "update",
                        "event_type": payload.event_type,
                        "event_id": payload.event_id,
                        "run_id": payload.run_id,
                        "trace_id": payload.trace_id,
                        "sequence": payload.sequence,
                        "chat_id": payload.chat_id,
                        "message_id": message_id,
                        "retry_count": retry_count,
                        "dead_letter_id": dead_letter.dead_letter_id,
                        "error": str(exc),
                    }
                retry_count += 1
                try:
                    interruptible_sleep(
                        self.retry_policy.backoff_for(retry_count),
                        stop_event=(cooperative_context or {}).get("stop_event"),
                        deadline_monotonic=(cooperative_context or {}).get("deadline_monotonic"),
                        cancelled_message="FEISHU_DELIVERY_CANCELLED",
                        timed_out_message="FEISHU_DELIVERY_TIMED_OUT",
                        sleeper=self.sleeper,
                    )
                except TimeoutError as stop_exc:
                    dead_letter = self.dead_letter_queue.record(
                        channel_id="feishu",
                        conversation_id=payload.chat_id,
                        payload=payload,
                        attempts=retry_count,
                        error=str(stop_exc),
                    )
                    return {
                        "ok": False,
                        "action": "send" if not message_id else "update",
                        "event_type": payload.event_type,
                        "event_id": payload.event_id,
                        "run_id": payload.run_id,
                        "trace_id": payload.trace_id,
                        "sequence": payload.sequence,
                        "chat_id": payload.chat_id,
                        "message_id": message_id,
                        "retry_count": retry_count,
                        "dead_letter_id": dead_letter.dead_letter_id,
                        "error": str(stop_exc),
                    }

    def _attempt_delivery(self, payload: FeishuDeliveryPayload, message_id: str | None) -> dict:
        should_try_update = message_id is not None and self.enable_message_update
        if should_try_update:
            try:
                return self.update(message_id, payload)
            except RuntimeError:
                return self.send(payload)
        return self.send(payload)

    def _get_tenant_access_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._tenant_access_token_expire_at:
            return self._tenant_access_token
        app_id = self.env.get("FEISHU_APP_ID")
        app_secret = self.env.get("FEISHU_APP_SECRET")
        if not app_id or not app_secret:
            raise RuntimeError("FEISHU_APP_CREDENTIALS_MISSING")
        base_url = self.env.get("FEISHU_BASE_URL", "https://open.feishu.cn").rstrip("/")
        response = self.transport(
            f"{base_url}/open-apis/auth/v3/tenant_access_token/internal",
            {"Content-Type": "application/json"},
            {
                "app_id": app_id,
                "app_secret": app_secret,
            },
        )
        if response.get("code", 0) != 0:
            raise RuntimeError(f"feishu_access_token_failed:{response.get('code')}:{response.get('msg', '')}")
        self._tenant_access_token = str(response["tenant_access_token"])
        self._tenant_access_token_expire_at = now + int(response.get("expire", 3600)) - 60
        return self._tenant_access_token

    def _build_message_body(self, payload: FeishuDeliveryPayload) -> dict[str, str]:
        if payload.event_type in {"final", "error"}:
            return {
                "msg_type": "interactive",
                "content": self._render_card(payload),
            }
        return {
            "msg_type": "text",
            "content": json.dumps({"text": self._render_text(payload)}, ensure_ascii=False),
        }

    def _render_card(self, payload: FeishuDeliveryPayload) -> str:
        if payload.card is not None:
            return json.dumps(payload.card, ensure_ascii=False)
        kwargs: dict[str, object] = {"event_type": payload.event_type}
        if payload.usage_summary is not None:
            kwargs["usage_summary"] = payload.usage_summary
        return json.dumps(
            feishu_rendering.render_final_reply_card(payload.text, **kwargs),
            ensure_ascii=False,
        )

    def _render_text(self, payload: FeishuDeliveryPayload) -> str:
        return payload.text

    def _log_delivery_event(
        self,
        action: str,
        payload: FeishuDeliveryPayload,
        message_id: str | None,
        *,
        reason: str | None = None,
    ) -> None:
        detail = f" reason={reason}" if reason else ""
        logger.info(
            "feishu_delivery action=%s event_type=%s run_id=%s trace_id=%s event_id=%s chat_id=%s message_id=%s%s",
            action,
            payload.event_type,
            payload.run_id,
            payload.trace_id,
            payload.event_id,
            payload.chat_id,
            message_id or "",
            detail,
        )
