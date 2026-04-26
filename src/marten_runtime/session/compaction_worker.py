from __future__ import annotations

import threading
import time
from collections.abc import Mapping

from marten_runtime.session.compaction_runner import run_compaction


class SessionCompactionWorker:
    def __init__(
        self,
        *,
        session_store,
        llm_client_factory,
        profile_name: str | None,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        self.session_store = session_store
        self.llm_client_factory = llm_client_factory
        self.profile_name = profile_name
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._wake_event.set()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)

    def wake(self) -> None:
        self._wake_event.set()

    def run_once(self) -> bool:
        claimed = self.session_store.claim_next_compaction_job()
        if claimed is None:
            return False
        queue_wait_ms = _elapsed_ms(
            claimed.get("enqueued_at"),
            claimed.get("started_at"),
        )
        llm_started = time.perf_counter()
        try:
            llm = self.llm_client_factory.create_isolated(
                str(claimed.get("compaction_profile_name") or self.profile_name or "")
                or None
            )
            session = self.session_store.get(str(claimed.get("source_session_id") or ""))
            snapshot_messages = _snapshot_session_history(
                session.history,
                claimed.get("snapshot_message_count"),
            )
            compacted = run_compaction(
                llm=llm,
                session_id=session.session_id,
                current_message=str(claimed.get("current_message") or ""),
                session_messages=snapshot_messages,
                preserved_tail_user_turns=int(claimed.get("preserved_tail_user_turns") or 8),
                prompt_mode="history_summary",
                trigger_kind=None,
            )
        except Exception as exc:
            self.session_store.mark_compaction_job_failed(
                str(claimed.get("job_id") or ""),
                queue_wait_ms=queue_wait_ms,
                compaction_llm_ms=int((time.perf_counter() - llm_started) * 1000),
                persist_ms=0,
                result_reason="generation_failed",
                error_text=str(exc),
            )
            return True
        compaction_llm_ms = int((time.perf_counter() - llm_started) * 1000)
        if compacted is None:
            self.session_store.mark_compaction_job_failed(
                str(claimed.get("job_id") or ""),
                queue_wait_ms=queue_wait_ms,
                compaction_llm_ms=compaction_llm_ms,
                persist_ms=0,
                result_reason="empty_summary",
                error_text="compaction returned empty summary",
            )
            return True
        persist_started = time.perf_counter()
        write_applied = self.session_store.set_compacted_context_if_newer(
            session.session_id,
            compacted,
        )
        persist_ms = int((time.perf_counter() - persist_started) * 1000)
        self.session_store.mark_compaction_job_succeeded(
            str(claimed.get("job_id") or ""),
            queue_wait_ms=queue_wait_ms,
            compaction_llm_ms=compaction_llm_ms,
            persist_ms=persist_ms,
            result_reason="generated" if write_applied else "stale_ignored",
            source_range_end=compacted.source_message_range[1],
            write_applied=write_applied,
        )
        return True

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            processed = self.run_once()
            if processed:
                continue
            self._wake_event.wait(self.poll_interval_seconds)
            self._wake_event.clear()


def _elapsed_ms(
    start_value,
    end_value,
) -> int:
    from datetime import datetime

    if not isinstance(start_value, str) or not isinstance(end_value, str):
        return 0
    try:
        started = datetime.fromisoformat(start_value)
        ended = datetime.fromisoformat(end_value)
    except ValueError:
        return 0
    return max(0, int((ended - started).total_seconds() * 1000))


def _snapshot_session_history(session_messages, snapshot_message_count):  # noqa: ANN001
    history = list(session_messages or [])
    try:
        count = int(snapshot_message_count)
    except (TypeError, ValueError):
        count = 0
    if count <= 0 or count >= len(history):
        return history
    return history[:count]
