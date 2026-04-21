from __future__ import annotations

from marten_runtime.runtime.direct_rendering import maybe_render_tool_followup_text
from marten_runtime.runtime.llm_client import LLMRequest, ToolExchange
from marten_runtime.tools.builtins.runtime_tool import annotate_runtime_context_status_peak


def append_tool_exchange(
    tool_history: list[ToolExchange],
    *,
    tool_name: str,
    tool_payload: dict,
    tool_result: object,
) -> None:
    tool_history.append(
        ToolExchange(
            tool_name=tool_name,
            tool_payload=tool_payload,
            tool_result=tool_result if isinstance(tool_result, dict) else {},
        )
    )


def normalize_tool_result_for_followup(
    *,
    tool_name: str,
    tool_payload: dict,
    tool_result: object,
    peak_input_tokens_estimate: int,
    peak_stage: str,
    actual_peak_input_tokens: int | None,
    actual_peak_output_tokens: int | None,
    actual_peak_total_tokens: int | None,
    actual_peak_stage: str | None,
    message: str = "",
    tool_history_count: int = 1,
    tool_history: list[ToolExchange] | None = None,
) -> tuple[object, str | None]:
    if isinstance(tool_result, dict) and tool_name == "runtime":
        annotated = annotate_runtime_context_status_peak(
            tool_result,
            peak_input_tokens_estimate=peak_input_tokens_estimate,
            peak_stage=peak_stage,
            actual_peak_input_tokens=actual_peak_input_tokens,
            actual_peak_output_tokens=actual_peak_output_tokens,
            actual_peak_total_tokens=actual_peak_total_tokens,
            actual_peak_stage=actual_peak_stage,
        )
        return annotated, maybe_render_tool_followup_text(
            tool_name,
            annotated,
            tool_payload=tool_payload,
            tool_history=tool_history,
            message=message,
        ) or None
    if isinstance(tool_result, dict) and tool_name == "session":
        return tool_result, maybe_render_tool_followup_text(
            tool_name,
            tool_result,
            tool_payload=tool_payload,
            tool_history=tool_history,
            message=message,
        ) or None
    del tool_payload, message, tool_history_count, tool_history
    return tool_result, None


def build_tool_followup_request(
    base_request: LLMRequest,
    *,
    tool_history: list[ToolExchange],
    tool_result: object,
    requested_tool_name: str | None,
    requested_tool_payload: dict,
) -> LLMRequest:
    return base_request.model_copy(
        update={
            "tool_history": list(tool_history),
            "tool_result": tool_result,
            "requested_tool_name": requested_tool_name,
            "requested_tool_payload": requested_tool_payload,
        }
    )
