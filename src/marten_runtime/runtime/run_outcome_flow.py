from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import ToolExchange
from marten_runtime.runtime.provider_retry import ProviderTransportError
from marten_runtime.runtime.tool_episode_summary_prompt import ToolEpisodeSummaryDraft
from marten_runtime.runtime.timing import elapsed_ms
from marten_runtime.runtime.tool_outcome_flow import (
    build_combined_tool_episode_summary,
    build_fallback_tool_episode_summary,
)
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.tools.registry import ToolSnapshot

logger = logging.getLogger(__name__)


def tool_rejection_text(error_code: str) -> str:
    if error_code == "TOOL_NOT_ALLOWED":
        return "当前操作未被允许，请换个说法或缩小范围。"
    if error_code == "TOOL_NOT_FOUND":
        return "当前所需工具不可用，请稍后重试。"
    return error_code.lower()


def is_provider_failure(exc: Exception) -> bool:
    if isinstance(exc, (ProviderTransportError, TimeoutError, OSError)):
        return True
    return str(exc).startswith("provider_")

def finish_run_success(
    *,
    events: list[OutboundEvent],
    session_id: str,
    run_id: str,
    trace_id: str,
    run_started_at: float,
    llm_request_count: int,
    message: str,
    agent_id: str,
    final_text: str,
    tool_history: list[ToolExchange],
    tool_snapshot: ToolSnapshot,
    history: InMemoryRunHistory,
    self_improve_recorder: SelfImproveRecorder | None,
    append_post_turn_summary_callback=None,
    combined_summary_draft: ToolEpisodeSummaryDraft | None = None,
) -> list[OutboundEvent]:
    events.append(
        OutboundEvent(
            session_id=session_id,
            run_id=run_id,
            event_id=f"evt_{uuid4().hex[:8]}",
            event_type="final",
            sequence=2,
            trace_id=trace_id,
            payload={"text": final_text},
            created_at=datetime.now(timezone.utc),
        )
    )
    summary_callback = append_post_turn_summary_callback or append_post_turn_summary
    summary_callback(
        history=history,
        user_message=message,
        tool_history=tool_history,
        final_text=final_text,
        combined_summary_draft=combined_summary_draft,
        run_id=run_id,
        tool_snapshot=tool_snapshot,
    )
    history.finish(run_id, delivery_status="final")
    history.finalize_total_timing(run_id, elapsed_ms=elapsed_ms(run_started_at))
    history.set_llm_request_count(run_id, llm_request_count)
    record_recovery(
        self_improve_recorder,
        agent_id=agent_id,
        run_id=run_id,
        trace_id=trace_id,
        message=message,
    )
    return events


def finish_run_error(
    *,
    events: list[OutboundEvent],
    session_id: str,
    run_id: str,
    trace_id: str,
    run_started_at: float,
    llm_request_count: int,
    error_code: str,
    error_text: str,
    history: InMemoryRunHistory,
) -> list[OutboundEvent]:
    events.append(
        OutboundEvent(
            session_id=session_id,
            run_id=run_id,
            event_id=f"evt_{uuid4().hex[:8]}",
            event_type="error",
            sequence=2,
            trace_id=trace_id,
            payload={"code": error_code, "text": error_text},
            created_at=datetime.now(timezone.utc),
        )
    )
    history.fail(run_id, error_code=error_code)
    history.finalize_total_timing(run_id, elapsed_ms=elapsed_ms(run_started_at))
    history.set_llm_request_count(run_id, llm_request_count)
    return events


def record_failure(
    self_improve_recorder: SelfImproveRecorder | None,
    *,
    agent_id: str,
    run_id: str,
    trace_id: str,
    session_id: str,
    error_code: str,
    error_stage: str,
    message: str,
    summary: str,
    tool_name: str | None = None,
    provider_name: str | None = None,
) -> None:
    if self_improve_recorder is None:
        return
    self_improve_recorder.record_failure(
        agent_id=agent_id,
        run_id=run_id,
        trace_id=trace_id,
        session_id=session_id,
        error_code=error_code,
        error_stage=error_stage,
        tool_name=tool_name,
        provider_name=provider_name,
        summary=summary,
        message=message,
    )


def record_recovery(
    self_improve_recorder: SelfImproveRecorder | None,
    *,
    agent_id: str,
    run_id: str,
    trace_id: str,
    message: str,
) -> None:
    if self_improve_recorder is None:
        return
    self_improve_recorder.record_recovery(
        agent_id=agent_id,
        run_id=run_id,
        trace_id=trace_id,
        message=message,
        fix_summary="later successful completion on a compatible request",
        success_evidence="final reply generated",
    )


def append_post_turn_summary(
    *,
    history: InMemoryRunHistory,
    user_message: str,
    tool_history: list[ToolExchange],
    final_text: str,
    combined_summary_draft: ToolEpisodeSummaryDraft | None,
    run_id: str,
    tool_snapshot: ToolSnapshot,
) -> None:
    if not tool_history or not final_text.strip():
        return
    latest = tool_history[-1]
    if (
        latest.tool_name == "runtime"
        and str(
            (latest.tool_result or {}).get("action")
            or (latest.tool_payload or {}).get("action")
            or ""
        )
        == "context_status"
    ):
        return
    if any(item.tool_name in {"self_improve", "automation"} for item in tool_history):
        return
    summary = summarize_completed_tool_episode(
        user_message=user_message,
        tool_history=tool_history,
        final_text=final_text,
        combined_summary_draft=combined_summary_draft,
        run_id=run_id,
        tool_snapshot=tool_snapshot,
    )
    if summary is not None:
        history.append_tool_outcome_summary(run_id, summary)


def summarize_completed_tool_episode(
    *,
    user_message: str,
    tool_history: list[ToolExchange],
    final_text: str,
    combined_summary_draft: ToolEpisodeSummaryDraft | None,
    run_id: str,
    tool_snapshot: ToolSnapshot,
):
    del user_message
    try:
        fallback_summary = build_fallback_tool_episode_summary(
            run_id=run_id,
            history=tool_history,
            final_text=final_text,
            tool_snapshot=tool_snapshot,
        )
        draft = combined_summary_draft
        if draft is not None and draft.summary.strip():
            return build_combined_tool_episode_summary(
                run_id=run_id,
                history=tool_history,
                tool_snapshot=tool_snapshot,
                draft=draft,
                fallback_summary=fallback_summary,
            )
    except Exception:
        logger.debug("tool episode summary extraction failed", exc_info=True)
    return build_fallback_tool_episode_summary(
        run_id=run_id,
        history=tool_history,
        final_text=final_text,
        tool_snapshot=tool_snapshot,
    )
