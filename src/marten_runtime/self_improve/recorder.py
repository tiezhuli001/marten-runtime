from __future__ import annotations

import re
from uuid import uuid4

from marten_runtime.self_improve.models import FailureEvent, RecoveryEvent
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


class SelfImproveRecorder:
    def __init__(self, store: SQLiteSelfImproveStore) -> None:
        self.store = store

    def build_fingerprint(
        self,
        *,
        agent_id: str,
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
                message=message,
            ),
        )
        self.store.record_failure(event)
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
            if failure.fingerprint != recovery_fingerprint:
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
