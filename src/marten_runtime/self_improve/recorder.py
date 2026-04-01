from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.self_improve.models import FailureEvent, RecoveryEvent
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.self_improve.triggering import current_window_start, threshold_window_cutoff


class SelfImproveRecorder:
    def __init__(self, store: SQLiteSelfImproveStore) -> None:
        self.store = store
        self.failure_threshold = 3

    def build_fingerprint(
        self,
        *,
        agent_id: str,
        error_code: str | None = None,
        provider_name: str | None = None,
        tool_name: str | None = None,
        message: str = "",
    ) -> str:
        normalized_message = re.sub(r"\s+", " ", message.strip().lower())
        return "|".join([agent_id, normalized_message[:120]])

    def record_failure(
        self,
        *,
        agent_id: str,
        run_id: str,
        trace_id: str,
        session_id: str,
        error_code: str,
        error_stage: str,
        summary: str,
        message: str,
        tool_name: str | None = None,
        provider_name: str | None = None,
    ) -> FailureEvent:
        event = FailureEvent(
            failure_id=f"failure_{uuid4().hex[:8]}",
            agent_id=agent_id,
            run_id=run_id,
            trace_id=trace_id,
            session_id=session_id,
            error_code=error_code,
            error_stage=error_stage,
            tool_name=tool_name,
            provider_name=provider_name,
            summary=summary,
            fingerprint=self.build_fingerprint(
                agent_id=agent_id,
                error_code=error_code,
                provider_name=provider_name,
                tool_name=tool_name,
                message=message,
            ),
        )
        self.store.record_failure(event)
        self._maybe_create_threshold_trigger(
            agent_id=agent_id,
            fingerprint=event.fingerprint,
            created_at=event.created_at,
        )
        return event

    def record_recovery(
        self,
        *,
        agent_id: str,
        run_id: str,
        trace_id: str,
        message: str,
        fix_summary: str,
        success_evidence: str,
    ) -> RecoveryEvent | None:
        recovery_fingerprint = self.build_fingerprint(agent_id=agent_id, message=message)
        for failure in self.store.list_recent_failures(agent_id=agent_id, limit=20):
            if self.build_fingerprint(
                agent_id=agent_id,
                provider_name=failure.provider_name,
                tool_name=failure.tool_name,
                message=message,
            ) != recovery_fingerprint:
                continue
            event = RecoveryEvent(
                recovery_id=f"recovery_{uuid4().hex[:8]}",
                agent_id=agent_id,
                run_id=run_id,
                trace_id=trace_id,
                related_failure_fingerprint=failure.fingerprint,
                recovery_kind="same_fingerprint_success",
                fix_summary=fix_summary,
                success_evidence=success_evidence,
            )
            self.store.record_recovery(event)
            return event
        return None

    def _maybe_create_threshold_trigger(
        self,
        *,
        agent_id: str,
        fingerprint: str,
        created_at: datetime,
    ) -> None:
        recent_count = self.store.count_recent_failures_since(
            agent_id=agent_id,
            fingerprint=fingerprint,
            created_at_gte=threshold_window_cutoff(created_at).isoformat(),
        )
        if recent_count < self.failure_threshold:
            return
        self.store.create_threshold_trigger(
            agent_id=agent_id,
            fingerprint=fingerprint,
            window_start=current_window_start(created_at.astimezone(timezone.utc)).isoformat(),
        )
