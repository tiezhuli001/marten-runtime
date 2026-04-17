from __future__ import annotations

from typing import TYPE_CHECKING

from marten_runtime.runtime.query_hardening import (
    is_explicit_multi_step_tool_request,
    is_runtime_context_query,
    is_time_query,
)
from marten_runtime.runtime.tool_episode_summary_prompt import (
    render_tool_followup_summary_instruction,
)

if TYPE_CHECKING:
    from marten_runtime.runtime.llm_client import LLMRequest


def should_lock_runtime_context_followup(
    *, message: str, tool_history_count: int
) -> bool:
    if tool_history_count > 1:
        return False
    return not is_explicit_multi_step_tool_request(message)


def tool_followup_instruction(
    tool_name: str | None,
    *,
    lock_runtime_context_followup: bool = True,
    tool_history_count: int = 0,
) -> str | None:
    round_trip_consistency_instruction = ""
    if tool_history_count >= 2:
        current_request_ordinal = tool_history_count + 1
        round_trip_consistency_instruction = (
            "当前这次请求已经发生多次模型/工具往返。"
            f"当前已发生 {tool_history_count} 次工具调用，"
            f"你现在正在第 {current_request_ordinal} 次模型请求上继续生成最终回答，"
            "因此不得写成单次模型执行、不得写成一次性完成全部工具调用。"
            "如果你要量化这次链路，必须把工具调用次数和模型请求次数分开表述，"
            "不要把工具调用次数和模型请求次数写成同一个数字概念。"
            "如果你要描述这次链路是否为多轮、是否发生多次往返，必须明确写成“多次/多轮”，"
            "不要写成单次，不要写成未发生多次，也不要把它概括成单轮完成。"
        )
    if tool_name == "runtime":
        if not lock_runtime_context_followup:
            base = render_tool_followup_summary_instruction()
            return f"{round_trip_consistency_instruction}\n\n{base}".strip()
        base = (
            "仅根据刚刚返回的 runtime 工具结果回答当前这一个上下文/压缩状态问题。"
            "不要重述无关的旧任务结果，不要继续展开之前的话题，也不要补做用户当前没有要求的工具查询。"
        )
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    if tool_name == "mcp":
        base = (
            "如果你要继续发起 mcp family 调用，必须沿用刚刚看到的精确 server_id 和精确 tool_name，"
            "保持 action 为 list/detail/call 三者之一，并让 arguments 始终是一个对象。"
            "不要自造别名、不要重命名子工具。\n\n"
            + render_tool_followup_summary_instruction()
        )
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    if tool_name == "skill":
        base = (
            "你已经加载了刚刚那个 skill 正文。"
            "除非用户现在明确要求你再加载另一个 skill，"
            "否则不要重复调用 skill 去再次加载同一个 skill，"
            "应直接基于已加载的 skill 内容完成回答。\n\n"
            + render_tool_followup_summary_instruction()
        )
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    if tool_name:
        base = render_tool_followup_summary_instruction()
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    return None


def is_tool_followup_request(request: LLMRequest) -> bool:
    return bool(request.tool_history) or (
        request.tool_result is not None and bool(request.requested_tool_name)
    )


def request_specific_instruction(request: LLMRequest) -> str | None:
    message = request.message or ""
    available = set(request.available_tools)
    instructions: list[str] = []
    if "runtime" in available and is_runtime_context_query(message):
        instructions.append(
            "这是实时上下文查询。请先读取当前 runtime 状态，再基于本轮实际返回的数据回答；"
            "不要直接凭记忆概括当前上下文占用。"
        )
    if "time" in available and is_time_query(message):
        instructions.append(
            "这是当前时间查询。请先读取当前时间工具结果，再回答用户；"
            "不要直接凭记忆猜测现在时间。"
        )
    if request.channel_protocol_instruction_text:
        instructions.append(request.channel_protocol_instruction_text)
    if not instructions:
        return None
    return "\n".join(instructions)
