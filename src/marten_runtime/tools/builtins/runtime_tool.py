from __future__ import annotations

from typing import TYPE_CHECKING, Any

from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMRequest, estimate_request_tokens, estimate_request_usage

if TYPE_CHECKING:
    from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.runtime.usage_models import NormalizedUsage, PreflightEstimate
from marten_runtime.session.compaction_trigger import CompactionSettings


def run_runtime_tool(
    payload: dict,
    *,
    tool_context: dict | None = None,
    runtime_loop: RuntimeLoop | None = None,
    run_history: InMemoryRunHistory | None = None,
    latest_checkpoint_available: bool | None = None,
) -> dict:
    action = str(payload.get("action", "context_status")).strip().lower() or "context_status"
    if action != "context_status":
        raise ValueError("unsupported runtime action")
    return _build_context_status(
        tool_context=tool_context,
        runtime_loop=runtime_loop,
        run_history=run_history,
        latest_checkpoint_available=latest_checkpoint_available,
    )


def _build_context_status(
    *,
    tool_context: dict | None,
    runtime_loop: RuntimeLoop | None,
    run_history: InMemoryRunHistory | None,
    latest_checkpoint_available: bool | None,
) -> dict:
    tool_context = tool_context or {}
    current_request = tool_context.get("current_request")
    compact_settings = tool_context.get("compact_settings")
    request_estimate = _estimate_usage(current_request)
    resolved_settings = compact_settings if isinstance(compact_settings, CompactionSettings) else CompactionSettings()
    effective_window = resolved_settings.effective_window
    usage_percent = min(100, round((request_estimate.input_tokens_estimate / max(1, effective_window)) * 100))
    model_profile = str(tool_context.get("model_profile") or getattr(getattr(runtime_loop, "llm", None), "profile_name", "unknown"))
    run_id = str(tool_context.get("run_id") or "")
    compaction_status = "none"
    current_run = {
        "initial_input_tokens_estimate": request_estimate.input_tokens_estimate,
        "peak_input_tokens_estimate": request_estimate.input_tokens_estimate,
        "peak_stage": "initial_request",
        "actual_peak_input_tokens": None,
        "actual_peak_output_tokens": None,
        "actual_peak_total_tokens": None,
        "actual_peak_stage": None,
    }
    if run_id and run_history is not None:
        run_record = run_history.get(run_id)
        diagnostics = run_record.compaction
        current_run = {
            "initial_input_tokens_estimate": (
                run_record.initial_preflight_input_tokens_estimate or request_estimate.input_tokens_estimate
            ),
            "peak_input_tokens_estimate": (
                run_record.peak_preflight_input_tokens_estimate or request_estimate.input_tokens_estimate
            ),
            "peak_stage": run_record.peak_preflight_stage or "initial_request",
            "actual_peak_input_tokens": run_record.actual_peak_input_tokens,
            "actual_peak_output_tokens": run_record.actual_peak_output_tokens,
            "actual_peak_total_tokens": run_record.actual_peak_total_tokens,
            "actual_peak_stage": run_record.actual_peak_stage,
        }
        if diagnostics.used_compacted_context and diagnostics.decision == "reactive":
            compaction_status = "reactive-used"
        elif diagnostics.used_compacted_context and diagnostics.decision == "proactive":
            compaction_status = "proactive-used"
        elif diagnostics.used_compacted_context:
            compaction_status = "checkpoint-available"
        elif request_estimate.input_tokens_estimate >= diagnostics.proactive_threshold_tokens > 0:
            compaction_status = "advisory"
        elif request_estimate.input_tokens_estimate >= diagnostics.advisory_threshold_tokens > 0:
            compaction_status = "advisory"
    checkpoint_state = "available" if latest_checkpoint_available else "none"
    if checkpoint_state == "available" and compaction_status == "none":
        compaction_status = "checkpoint-available"
    last_actual_usage = _normalize_usage(tool_context.get("latest_actual_usage"))
    previous_run = _find_latest_session_run_with_actual_usage(
        run_history=run_history,
        session_id=str(tool_context.get("session_id") or ""),
        exclude_run_id=run_id,
    )
    if last_actual_usage is None and run_id and run_history is not None:
        last_actual_usage = run_history.get(run_id).latest_actual_usage
    if last_actual_usage is None and previous_run is not None:
        last_actual_usage = previous_run.latest_actual_usage
    last_completed_run = None
    if previous_run is not None:
        last_completed_run = {
            "run_id": previous_run.run_id,
            "actual_peak_input_tokens": previous_run.actual_peak_input_tokens,
            "actual_peak_output_tokens": previous_run.actual_peak_output_tokens,
            "actual_peak_total_tokens": previous_run.actual_peak_total_tokens,
            "actual_peak_stage": previous_run.actual_peak_stage,
        }
    return {
        "ok": True,
        "action": "context_status",
        "model_profile": model_profile,
        "context_window": resolved_settings.context_window_tokens,
        "effective_window": effective_window,
        "estimated_usage": request_estimate.input_tokens_estimate,
        "estimate_source": request_estimate.estimator_kind,
        "current_run": current_run,
        "next_request_estimate": {
            "input_tokens_estimate": request_estimate.input_tokens_estimate,
            "estimator_kind": request_estimate.estimator_kind,
            "degraded": request_estimate.degraded,
            "effective_window_tokens": effective_window,
            "context_window_tokens": resolved_settings.context_window_tokens,
        },
        "last_actual_usage": (
            None if last_actual_usage is None else last_actual_usage.model_dump(mode="json")
        ),
        "last_completed_run": last_completed_run,
        "usage_percent": usage_percent,
        "compaction_status": compaction_status,
        "latest_checkpoint": checkpoint_state,
        "summary": _build_summary(
            context_window=resolved_settings.context_window_tokens,
            effective_window=effective_window,
            estimated_usage=request_estimate.input_tokens_estimate,
            usage_percent=usage_percent,
            compaction_status=compaction_status,
            latest_checkpoint=checkpoint_state,
            estimator_kind=request_estimate.estimator_kind,
            degraded=request_estimate.degraded,
            current_run=current_run,
        ),
    }


def _estimate_usage(current_request: Any) -> PreflightEstimate:
    if isinstance(current_request, LLMRequest):
        return estimate_request_usage(current_request)
    return PreflightEstimate(input_tokens_estimate=0, estimator_kind="rough", degraded=True)


def _normalize_usage(value: Any) -> NormalizedUsage | None:
    if isinstance(value, NormalizedUsage):
        return value
    if isinstance(value, dict):
        return NormalizedUsage(**value)
    return None


def _find_latest_session_run_with_actual_usage(
    *,
    run_history: InMemoryRunHistory | None,
    session_id: str,
    exclude_run_id: str,
):
    if run_history is None or not session_id:
        return None
    candidates = [
        item
        for item in run_history.list_runs()
        if (
            item.session_id == session_id
            and item.run_id != exclude_run_id
            and item.finished_at is not None
            and (item.latest_actual_usage is not None or item.actual_peak_total_tokens is not None)
        )
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.finished_at or item.started_at)
    return candidates[-1]


def _build_summary(
    *,
    context_window: int,
    effective_window: int,
    estimated_usage: int,
    usage_percent: int,
    compaction_status: str,
    latest_checkpoint: str,
    estimator_kind: str,
    degraded: bool,
    current_run: dict[str, Any],
) -> str:
    checkpoint_text = "，已有压缩检查点" if latest_checkpoint == "available" else ""
    if compaction_status == "proactive-used":
        status_text = "本轮已主动压缩"
    elif compaction_status == "reactive-used":
        status_text = "本轮已触发重试压缩"
    elif compaction_status == "checkpoint-available":
        status_text = "已有可复用压缩检查点"
    elif compaction_status == "advisory":
        status_text = "上下文接近压缩建议线"
    else:
        status_text = "上下文状态稳定"
    estimate_text = (
        f"当前 rough fallback 估算占用 {estimated_usage}/{effective_window} tokens（{usage_percent}%）"
        if degraded
        else f"当前估算占用 {estimated_usage}/{effective_window} tokens（{usage_percent}%）"
    )
    initial_tokens = int(current_run.get("initial_input_tokens_estimate") or estimated_usage)
    actual_peak_total = int(current_run.get("actual_peak_total_tokens") or 0)
    actual_peak_input = int(current_run.get("actual_peak_input_tokens") or 0)
    actual_peak_output = int(current_run.get("actual_peak_output_tokens") or 0)
    actual_peak_stage = str(current_run.get("actual_peak_stage") or "").strip()
    if actual_peak_total > 0:
        run_pressure_text = (
            f"本轮首发请求约 {initial_tokens} tokens，本轮 actual-peak 约 {actual_peak_total} tokens"
            f"（输入 {actual_peak_input} + 输出 {actual_peak_output}）"
        )
        if actual_peak_stage == "llm_second":
            run_pressure_text += "，峰值主要来自工具结果注入后的 follow-up 模型调用。"
        else:
            run_pressure_text += "。"
    else:
        peak_tokens = int(current_run.get("peak_input_tokens_estimate") or initial_tokens)
        run_pressure_text = (
            f"本轮未发生模型调用，因此 actual-peak 暂无数据。"
            f"本轮首发请求约 {initial_tokens} tokens，本轮峰值输入上下文约 {peak_tokens} tokens。"
        )
    return (
        f"{estimate_text}，原始窗口 {context_window}，{status_text}{checkpoint_text}。{run_pressure_text}"
    )


def annotate_runtime_context_status_peak(
    result: dict[str, Any],
    *,
    peak_input_tokens_estimate: int,
    peak_stage: str,
    actual_peak_input_tokens: int | None = None,
    actual_peak_output_tokens: int | None = None,
    actual_peak_total_tokens: int | None = None,
    actual_peak_stage: str | None = None,
) -> dict[str, Any]:
    if result.get("action") != "context_status":
        return result
    current_run = dict(result.get("current_run") or {})
    initial_tokens = int(current_run.get("initial_input_tokens_estimate") or result.get("estimated_usage") or 0)
    peak_tokens = max(initial_tokens, int(peak_input_tokens_estimate))
    current_run.update(
        {
            "initial_input_tokens_estimate": initial_tokens,
            "peak_input_tokens_estimate": peak_tokens,
            "peak_stage": peak_stage,
            "actual_peak_input_tokens": actual_peak_input_tokens,
            "actual_peak_output_tokens": actual_peak_output_tokens,
            "actual_peak_total_tokens": actual_peak_total_tokens,
            "actual_peak_stage": actual_peak_stage,
        }
    )
    result["current_run"] = current_run
    result["summary"] = _build_summary(
        context_window=int(result.get("context_window") or 0),
        effective_window=int(result.get("effective_window") or 0),
        estimated_usage=int(result.get("estimated_usage") or 0),
        usage_percent=int(result.get("usage_percent") or 0),
        compaction_status=str(result.get("compaction_status") or "none"),
        latest_checkpoint=str(result.get("latest_checkpoint") or "none"),
        estimator_kind=str(result.get("estimate_source") or "rough"),
        degraded=bool((result.get("next_request_estimate") or {}).get("degraded", False)),
        current_run=current_run,
    )
    return result


def render_runtime_context_status_text(result: dict[str, Any]) -> str:
    if result.get("action") != "context_status":
        return ""
    next_request = dict(result.get("next_request_estimate") or {})
    current_run = dict(result.get("current_run") or {})
    last_completed_run = dict(result.get("last_completed_run") or {})
    last_actual = result.get("last_actual_usage")
    lines = [
        "当前上下文使用详情",
        (
            f"- 下一次请求预计输入：{int(next_request.get('input_tokens_estimate') or 0)} tokens"
            f"（{str(next_request.get('estimator_kind') or result.get('estimate_source') or 'rough')}）"
        ),
    ]
    initial_tokens = int(current_run.get("initial_input_tokens_estimate") or 0)
    actual_peak_total = int(current_run.get("actual_peak_total_tokens") or 0)
    actual_peak_input = int(current_run.get("actual_peak_input_tokens") or 0)
    actual_peak_output = int(current_run.get("actual_peak_output_tokens") or 0)
    actual_peak_stage = str(current_run.get("actual_peak_stage") or "").strip()
    if actual_peak_total > 0:
        peak_line = (
            f"- 本轮首发请求：{initial_tokens} tokens；本轮 actual-peak：{actual_peak_total} tokens"
            f"（输入 {actual_peak_input} + 输出 {actual_peak_output}）"
        )
        if actual_peak_stage == "llm_second":
            peak_line += "（峰值主要来自工具结果注入后的 follow-up 模型调用）"
    else:
        peak_tokens = int(current_run.get("peak_input_tokens_estimate") or 0)
        lines.append("- 本轮 actual-peak：无（本轮未发生模型调用）")
        peak_line = f"- 本轮首发请求：{initial_tokens} tokens；本轮峰值输入上下文：{peak_tokens} tokens"
    lines.append(peak_line)
    previous_peak_total = int(last_completed_run.get("actual_peak_total_tokens") or 0)
    if previous_peak_total > 0:
        previous_peak_input = int(last_completed_run.get("actual_peak_input_tokens") or 0)
        previous_peak_output = int(last_completed_run.get("actual_peak_output_tokens") or 0)
        previous_peak_stage = str(last_completed_run.get("actual_peak_stage") or "").strip()
        previous_line = (
            f"- 上一轮 actual-peak：{previous_peak_total} tokens"
            f"（输入 {previous_peak_input} + 输出 {previous_peak_output}）"
        )
        if previous_peak_stage == "llm_second":
            previous_line += "（峰值主要来自工具结果注入后的 follow-up 模型调用）"
        lines.append(previous_line)
    if isinstance(last_actual, dict):
        lines.append(
            "- 上一轮模型调用："
            f"模型输入：{int(last_actual.get('input_tokens') or 0)}｜"
            f"模型输出：{int(last_actual.get('output_tokens') or 0)}｜"
            f"总计：{int(last_actual.get('total_tokens') or 0)}"
        )
    lines.append(
        f"- 有效窗口：{int(result.get('effective_window') or 0)} tokens"
        f"（原始窗口 {int(result.get('context_window') or 0)}）"
    )
    lines.append(f"- 压缩状态：{_render_compaction_status(str(result.get('compaction_status') or 'none'))}")
    return "\n".join(lines)


def _render_compaction_status(status: str) -> str:
    if status == "proactive-used":
        return "本轮已主动压缩"
    if status == "reactive-used":
        return "本轮已触发重试压缩"
    if status == "checkpoint-available":
        return "已有可复用压缩检查点"
    if status == "advisory":
        return "已接近压缩建议线"
    return "稳定"
