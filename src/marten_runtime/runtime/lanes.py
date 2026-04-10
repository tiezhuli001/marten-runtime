from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Condition
from typing import Any


@dataclass(frozen=True)
class LaneKey:
    channel_id: str
    conversation_id: str


@dataclass(frozen=True)
class LaneLease:
    lane_key: LaneKey
    run_id: str
    trace_id: str
    enqueued_at: datetime
    started_at: datetime
    queue_depth_at_enqueue: int = 1
    queue_wait_ms: int = 0

    @property
    def waited_in_lane(self) -> bool:
        return self.queue_wait_ms > 0 or self.queue_depth_at_enqueue > 1


@dataclass
class _LaneEntry:
    lane_key: LaneKey
    run_id: str
    trace_id: str
    enqueued_at: datetime
    started_at: datetime | None = None


class ConversationLaneManager:
    def __init__(self) -> None:
        self._condition = Condition()
        self._queues: dict[LaneKey, deque[_LaneEntry]] = {}
        self._max_queue_depth = 0
        self._last_enqueued_lane: dict[str, Any] | None = None

    def acquire(
        self,
        *,
        channel_id: str,
        conversation_id: str,
        run_id: str,
        trace_id: str,
    ) -> LaneLease:
        lane_key = LaneKey(channel_id=channel_id, conversation_id=conversation_id)
        entry = _LaneEntry(
            lane_key=lane_key,
            run_id=run_id,
            trace_id=trace_id,
            enqueued_at=datetime.now(timezone.utc),
        )
        with self._condition:
            queue = self._queues.setdefault(lane_key, deque())
            queue.append(entry)
            queue_depth_at_enqueue = len(queue)
            if len(queue) > 1:
                self._last_enqueued_lane = {
                    "channel_id": lane_key.channel_id,
                    "conversation_id": lane_key.conversation_id,
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "enqueued_at": entry.enqueued_at.isoformat(),
                    "queue_depth": len(queue),
                }
            self._max_queue_depth = max(self._max_queue_depth, len(queue))
            while True:
                head = queue[0]
                if head is entry:
                    started_at = datetime.now(timezone.utc)
                    entry.started_at = started_at
                    queue_wait_ms = max(
                        0,
                        int((started_at - entry.enqueued_at).total_seconds() * 1000),
                    )
                    return LaneLease(
                        lane_key=lane_key,
                        run_id=run_id,
                        trace_id=trace_id,
                        enqueued_at=entry.enqueued_at,
                        started_at=started_at,
                        queue_depth_at_enqueue=queue_depth_at_enqueue,
                        queue_wait_ms=queue_wait_ms,
                    )
                self._condition.wait()

    def release(self, *, channel_id: str, conversation_id: str, run_id: str | None = None) -> None:
        lane_key = LaneKey(channel_id=channel_id, conversation_id=conversation_id)
        with self._condition:
            queue = self._queues.get(lane_key)
            if not queue:
                return
            head = queue[0]
            if run_id is not None and head.run_id != run_id:
                return
            queue.popleft()
            if not queue:
                self._queues.pop(lane_key, None)
            self._condition.notify_all()

    def stats(self) -> dict[str, Any]:
        with self._condition:
            active_lanes = []
            queued_lane_count = 0
            queued_items_total = 0
            for lane_key, queue in sorted(
                self._queues.items(),
                key=lambda item: (item[0].channel_id, item[0].conversation_id),
            ):
                if not queue:
                    continue
                head = queue[0]
                active_lanes.append(
                    {
                        "channel_id": lane_key.channel_id,
                        "conversation_id": lane_key.conversation_id,
                        "active_run_id": head.run_id,
                        "active_trace_id": head.trace_id,
                        "enqueued_at": head.enqueued_at.isoformat(),
                        "started_at": head.started_at.isoformat() if head.started_at else None,
                        "queue_depth": len(queue),
                    }
                )
                if len(queue) > 1:
                    queued_lane_count += 1
                    queued_items_total += len(queue) - 1
            return {
                "mode": "conversation_lanes",
                "active_lane_count": len(active_lanes),
                "active_lanes": active_lanes,
                "queued_lane_count": queued_lane_count,
                "queued_items_total": queued_items_total,
                "max_queue_depth": self._max_queue_depth,
                "last_enqueued_lane": self._last_enqueued_lane,
            }
