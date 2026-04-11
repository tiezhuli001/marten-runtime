import json
import threading

from lark_oapi.ws.const import (
    HEADER_MESSAGE_ID,
    HEADER_SEQ,
    HEADER_SUM,
    HEADER_TRACE_ID,
    HEADER_TYPE,
)
from lark_oapi.ws.enum import FrameType, MessageType
from lark_oapi.ws.pb.pbbp2_pb2 import Frame

from marten_runtime.channels.feishu.delivery import FeishuDeliveryPayload


class FakeDeliveryClient:
    def __init__(self) -> None:
        self.payloads: list[FeishuDeliveryPayload] = []
        self.reactions: list[tuple[str, str]] = []

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

    def add_reaction(self, message_id: str, emoji_type: str = "OnIt") -> dict[str, object]:
        self.reactions.append((message_id, emoji_type))
        return {
            "ok": True,
            "message_id": message_id,
            "emoji_type": emoji_type,
        }


class BlockingDeliveryClient:
    def __init__(self) -> None:
        self.payloads: list[FeishuDeliveryPayload] = []
        self.first_delivery_started = threading.Event()
        self.release_first_delivery = threading.Event()
        self.second_delivery_started = threading.Event()

    def deliver(self, payload: FeishuDeliveryPayload) -> dict[str, object]:
        if payload.run_id == "run_1":
            self.first_delivery_started.set()
            self.release_first_delivery.wait(timeout=2)
        else:
            self.second_delivery_started.set()
        self.payloads.append(payload)
        return {
            "ok": True,
            "message_id": f"om_blocking_{len(self.payloads)}",
            "event_id": payload.event_id,
            "event_type": payload.event_type,
            "run_id": payload.run_id,
            "trace_id": payload.trace_id,
            "sequence": payload.sequence,
        }

    def add_reaction(self, message_id: str, emoji_type: str = "OnIt") -> dict[str, object]:
        return {
            "ok": True,
            "message_id": message_id,
            "emoji_type": emoji_type,
        }


class RecordingDeliveryTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, str], dict]] = []
        self.updated: list[tuple[str, dict[str, str], dict]] = []
        self.reactions: list[tuple[str, dict[str, str], dict]] = []

    def post(self, url: str, headers: dict[str, str], body: dict) -> dict:
        if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
            return {
                "code": 0,
                "tenant_access_token": "tenant-token",
                "expire": 7200,
            }
        if "/reactions" in url:
            self.reactions.append((url, headers, body))
            return {"code": 0, "data": {}}
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


class FlakyDeliveryTransport:
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




def build_event_frame(payload: dict[str, object]) -> bytes:
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
