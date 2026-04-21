from __future__ import annotations

from typing import TYPE_CHECKING

from marten_runtime.runtime.query_hardening import (
    is_explicit_multi_step_tool_request,
    is_automation_list_query,
    is_runtime_context_query,
    is_session_catalog_query,
    is_session_switch_query,
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


def explicit_tool_surface_for_request(request: LLMRequest) -> list[str] | None:
    message = request.message or ""
    available = set(request.available_tools)
    single_intent_surface = _explicit_single_intent_tool_surface(message, available)
    if single_intent_surface is not None:
        return single_intent_surface
    if not is_explicit_multi_step_tool_request(message):
        return None
    ordered: list[str] = []
    if "time" in available and is_time_query(message):
        ordered.append("time")
    if "runtime" in available and is_runtime_context_query(message):
        ordered.append("runtime")
    if "session" in available and (is_session_catalog_query(message) or is_session_switch_query(message)):
        ordered.append("session")
    if "mcp" in available and _mentions_mcp(message):
        ordered.append("mcp")
    if "automation" in available and is_automation_list_query(message):
        ordered.append("automation")
    if "skill" in available and _mentions_skill(message):
        ordered.append("skill")
    if "spawn_subagent" in available and _mentions_subagent(message):
        ordered.append("spawn_subagent")
    if "self_improve" in available and _mentions_self_improve(message):
        ordered.append("self_improve")
    return ordered or None


def should_omit_capability_catalog_for_request(request: LLMRequest) -> bool:
    if _is_explicit_subagent_request(request.message or ""):
        return True
    message = request.message or ""
    return (
        is_explicit_multi_step_tool_request(message)
        or is_runtime_context_query(message)
        or is_time_query(message)
        or is_session_catalog_query(message)
        or is_session_switch_query(message)
        or is_automation_list_query(message)
    )


def should_use_wider_interactive_timeout(request: LLMRequest) -> bool:
    message = request.message or ""
    return is_explicit_multi_step_tool_request(message) or _is_explicit_subagent_request(message)


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
    if "session" in available and is_session_catalog_query(message):
        instructions.append(
            "这是会话目录/活跃会话查询。优先使用 session family tool；"
            "回答时聚焦会话标题、状态、消息数、创建时间等会话元数据。"
            "只有当用户明确提到定时任务、自动化、cron 或 automation 时，才使用 automation family tool。"
        )
    if "session" in available and is_session_switch_query(message):
        instructions.append(
            "这是显式会话切换请求。优先考虑 session family tool；"
            "如果你决定使用 session，请根据用户语义在 new 或 resume 之间自行选择合适 action。"
        )
    if "automation" in available and is_automation_list_query(message):
        instructions.append(
            "这是定时任务/自动化查询。优先使用 automation family tool；"
            "不要把定时任务列表误解成会话目录。"
        )
    if "spawn_subagent" in available and _is_explicit_subagent_request(message):
        instructions.append(
            "这是显式子代理请求。优先使用 spawn_subagent；"
            "当前回合的目标是受理后台任务并返回受理状态，不要把它改写成主线程直接完成。"
        )
    if request.channel_protocol_instruction_text:
        instructions.append(request.channel_protocol_instruction_text)
    if not instructions:
        return None
    return "\n".join(instructions)


def _is_explicit_subagent_request(message: str) -> bool:
    return _mentions_subagent(message) and any(
        token in message.lower() or token in message
        for token in ("开启", "启动", "开一个", "开个", "请用", "用", "后台执行", "delegate", "spawn")
    )


def _mentions_subagent(message: str) -> bool:
    normalized = message.lower()
    return any(token in normalized or token in message for token in ("子代理", "子 agent", "subagent", "后台任务", "后台执行"))


def _mentions_mcp(message: str) -> bool:
    normalized = message.lower()
    return any(token in normalized or token in message for token in ("mcp", "github server", "server_id", "tool_name", "github"))


def _mentions_skill(message: str) -> bool:
    normalized = message.lower()
    return any(token in normalized or token in message for token in ("skill", "技能", "加载 skill", "加载技能"))


def _mentions_self_improve(message: str) -> bool:
    normalized = message.lower()
    return any(token in normalized or token in message for token in ("self_improve", "self-improve", "自我改进", "复盘"))


def _explicit_single_intent_tool_surface(
    message: str,
    available: set[str],
) -> list[str] | None:
    if is_explicit_multi_step_tool_request(message):
        return None
    if _is_explicit_subagent_request(message):
        ordered = _ordered_available_tools(
            available,
            ["spawn_subagent", "mcp", "skill", "runtime", "time"],
        )
        return ordered or None
    if (
        is_runtime_context_query(message)
        or is_time_query(message)
        or is_session_catalog_query(message)
        or is_session_switch_query(message)
        or is_automation_list_query(message)
    ):
        ordered = _ordered_available_tools(
            available,
            ["session", "automation", "runtime", "time", "spawn_subagent"],
        )
        return ordered or None
    return None


def _ordered_available_tools(available: set[str], ordered_names: list[str]) -> list[str]:
    return [tool_name for tool_name in ordered_names if tool_name in available]
