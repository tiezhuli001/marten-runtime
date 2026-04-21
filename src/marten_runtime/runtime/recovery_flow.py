from __future__ import annotations

from marten_runtime.runtime.direct_rendering import (
    render_direct_tool_history_text,
    render_direct_tool_text,
)
from marten_runtime.runtime.llm_client import ToolExchange


def is_generic_tool_failure_text(text: str) -> bool:
    normalized = " ".join(str(text).split())
    return normalized in {
        "工具执行失败，请重试。",
        "工具执行失败，请稍后重试。",
        "tool execution failed, please retry.",
    }


def recover_successful_tool_followup_text(history: list[ToolExchange]) -> str:
    if not history:
        return ""
    combined_text = render_direct_tool_history_text(history)
    if combined_text:
        return combined_text
    latest = history[-1]
    if not isinstance(latest.tool_result, dict):
        return ""
    if latest.tool_result.get("ok") is False or latest.tool_result.get("is_error") is True:
        return ""
    return render_direct_tool_text(
        latest.tool_name,
        latest.tool_result,
        tool_payload=latest.tool_payload,
    )


def recover_tool_result_text(tool_history: list[ToolExchange]) -> str:
    if not tool_history:
        return ""
    latest = tool_history[-1]
    return render_direct_tool_text(
        latest.tool_name,
        latest.tool_result,
        tool_payload=latest.tool_payload,
    )
