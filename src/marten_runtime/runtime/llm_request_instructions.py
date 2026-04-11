from __future__ import annotations

from typing import TYPE_CHECKING

from marten_runtime.runtime.query_hardening import (
    is_runtime_context_query,
    is_time_query,
)
from marten_runtime.runtime.tool_episode_summary_prompt import (
    render_tool_followup_summary_instruction,
)

if TYPE_CHECKING:
    from marten_runtime.runtime.llm_client import LLMRequest


def tool_followup_instruction(tool_name: str | None) -> str | None:
    if tool_name == "runtime":
        return (
            "仅根据刚刚返回的 runtime 工具结果回答当前这一个上下文/压缩状态问题。"
            "不要重述无关的旧任务结果，不要继续展开之前的话题，也不要补做用户当前没有要求的工具查询。"
        )
    if tool_name == "mcp":
        return (
            "如果你要继续发起 mcp family 调用，必须沿用刚刚看到的精确 server_id 和精确 tool_name，"
            "保持 action 为 list/detail/call 三者之一，并让 arguments 始终是一个对象。"
            "不要自造别名、不要重命名子工具。\n\n"
            + render_tool_followup_summary_instruction()
        )
    if tool_name:
        return render_tool_followup_summary_instruction()
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
            "这是当前会话的实时上下文查询。请先读取当前 runtime 状态，"
            "不要直接复用上一轮记忆里的上下文数字。"
        )
    if "time" in available and is_time_query(message):
        instructions.append(
            "这是实时当前时间查询。请先读取当前时间，"
            "不要根据记忆或上下文猜测当前时间。"
        )
    if request.channel_protocol_instruction_text:
        instructions.append(request.channel_protocol_instruction_text)
    if not instructions:
        return None
    return "\n".join(instructions)
