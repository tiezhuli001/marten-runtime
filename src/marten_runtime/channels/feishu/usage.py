from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from marten_runtime.runtime.history import InMemoryRunHistory, RunRecord

UsageSummary = dict[str, Any]


def build_usage_summary_from_record(record: RunRecord | None) -> UsageSummary | None:
    if record is None:
        return None
    if (record.actual_peak_total_tokens or 0) > 0:
        return {
            "input_tokens": int(record.actual_peak_input_tokens or 0),
            "output_tokens": int(record.actual_peak_output_tokens or 0),
            "peak_tokens": int(record.actual_peak_total_tokens or 0),
            "estimated_only": False,
        }
    if (record.peak_preflight_input_tokens_estimate or 0) > 0:
        return {
            "input_tokens": int(record.initial_preflight_input_tokens_estimate or 0),
            "output_tokens": None,
            "peak_tokens": int(record.peak_preflight_input_tokens_estimate or 0),
            "estimated_only": True,
        }
    return None


def build_usage_summary_from_history(
    run_history: InMemoryRunHistory | None,
    run_id: str,
) -> UsageSummary | None:
    if run_history is None:
        return None
    try:
        record = run_history.get(run_id)
    except KeyError:
        return None
    return build_usage_summary_from_record(record)


def format_usage_summary(usage_summary: Mapping[str, Any] | None) -> str | None:
    if not usage_summary:
        return None
    input_tokens = int(usage_summary.get("input_tokens", 0) or 0)
    output_tokens = usage_summary.get("output_tokens")
    peak_tokens = int(usage_summary.get("peak_tokens", 0) or 0)
    if input_tokens <= 0 and peak_tokens <= 0 and output_tokens in (None, 0):
        return None
    output_display = "-" if output_tokens is None else str(int(output_tokens))
    return f"本轮模型 token：输入 {input_tokens}｜输出 {output_display}｜峰值 {peak_tokens}"
