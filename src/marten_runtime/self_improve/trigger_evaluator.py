from __future__ import annotations

from uuid import uuid4

from marten_runtime.runtime.llm_client import ToolExchange
from marten_runtime.self_improve.models import ReviewTrigger
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


class SelfImproveTriggerEvaluator:
    def __init__(
        self,
        store: SQLiteSelfImproveStore,
        *,
        failure_burst_threshold: int = 2,
        recovery_threshold: int = 2,
        complex_episode_min_tool_calls: int = 2,
    ) -> None:
        self.store = store
        self.failure_burst_threshold = failure_burst_threshold
        self.recovery_threshold = recovery_threshold
        self.complex_episode_min_tool_calls = complex_episode_min_tool_calls

    def evaluate_failure_burst(
        self,
        *,
        agent_id: str,
        run_id: str,
        trace_id: str,
        fingerprint: str,
        summary: str,
        channel_id: str | None = None,
        tool_name: str | None = None,
        provider_name: str | None = None,
    ) -> ReviewTrigger | None:
        failures = [
            item
            for item in self.store.list_recent_failures(agent_id=agent_id, limit=20)
            if item.fingerprint == fingerprint
        ]
        if len(failures) < self.failure_burst_threshold:
            return None
        semantic_fingerprint = f"{agent_id}|lesson_failure_burst|{fingerprint}"
        trigger = ReviewTrigger(
            trigger_id=f"trigger_{uuid4().hex[:8]}",
            agent_id=agent_id,
            trigger_kind="lesson_failure_burst",
            source_run_id=run_id,
            source_trace_id=trace_id,
            source_fingerprints=[fingerprint],
            payload_json={
                "failure_count": len(failures),
                "latest_failure_summary": summary,
                "source_channel_id": channel_id,
                "tool_name": tool_name,
                "provider_name": provider_name,
            },
            semantic_fingerprint=semantic_fingerprint,
        )
        return self.store.create_review_trigger_if_absent(trigger)

    def evaluate_recovery_threshold(
        self,
        *,
        agent_id: str,
        run_id: str,
        trace_id: str,
        fingerprint: str,
        fix_summary: str,
        success_evidence: str,
        channel_id: str | None = None,
    ) -> ReviewTrigger | None:
        failures = [
            item
            for item in self.store.list_recent_failures(agent_id=agent_id, limit=20)
            if item.fingerprint == fingerprint
        ]
        if len(failures) < self.recovery_threshold:
            return None
        semantic_fingerprint = f"{agent_id}|lesson_recovery_threshold|{fingerprint}"
        trigger = ReviewTrigger(
            trigger_id=f"trigger_{uuid4().hex[:8]}",
            agent_id=agent_id,
            trigger_kind="lesson_recovery_threshold",
            source_run_id=run_id,
            source_trace_id=trace_id,
            source_fingerprints=[fingerprint],
            payload_json={
                "failure_count": len(failures),
                "fix_summary": fix_summary,
                "success_evidence": success_evidence,
                "source_channel_id": channel_id,
            },
            semantic_fingerprint=semantic_fingerprint,
        )
        return self.store.create_review_trigger_if_absent(trigger)

    def evaluate_complex_successful_tool_episode(
        self,
        *,
        agent_id: str,
        run_id: str,
        trace_id: str,
        user_message: str,
        tool_history: list[ToolExchange],
        final_text: str,
        summary: str,
        channel_id: str | None = None,
    ) -> ReviewTrigger | None:
        filtered_history = [
            item
            for item in tool_history
            if item.tool_name not in {"self_improve", "automation", "runtime"}
        ]
        if len(filtered_history) < self.complex_episode_min_tool_calls:
            return None
        tool_names = [item.tool_name for item in filtered_history]
        semantic_fingerprint = (
            f"{agent_id}|complex_successful_tool_episode|"
            f"{'|'.join(tool_names[:4])}|{user_message.strip().lower()[:80]}"
        )
        trigger = ReviewTrigger(
            trigger_id=f"trigger_{uuid4().hex[:8]}",
            agent_id=agent_id,
            trigger_kind="complex_successful_tool_episode",
            source_run_id=run_id,
            source_trace_id=trace_id,
            source_fingerprints=[],
            payload_json={
                "tool_names": tool_names,
                "tool_call_count": len(filtered_history),
                "summary": summary,
                "final_text": final_text[:500],
                "source_channel_id": channel_id,
            },
            semantic_fingerprint=semantic_fingerprint,
        )
        return self.store.create_review_trigger_if_absent(trigger)

    def evaluate_pre_compaction_learning_flush(
        self,
        *,
        agent_id: str,
        run_id: str,
        trace_id: str,
        fingerprint: str,
        estimated_tokens_before: int,
        estimated_tokens_after: int,
        channel_id: str | None = None,
    ) -> ReviewTrigger | None:
        semantic_fingerprint = f"{agent_id}|pre_compaction_learning_flush|{fingerprint}"
        trigger = ReviewTrigger(
            trigger_id=f"trigger_{uuid4().hex[:8]}",
            agent_id=agent_id,
            trigger_kind="pre_compaction_learning_flush",
            source_run_id=run_id,
            source_trace_id=trace_id,
            source_fingerprints=[fingerprint],
            payload_json={
                "estimated_tokens_before": estimated_tokens_before,
                "estimated_tokens_after": estimated_tokens_after,
                "source_channel_id": channel_id,
            },
            semantic_fingerprint=semantic_fingerprint,
        )
        return self.store.create_review_trigger_if_absent(trigger)
