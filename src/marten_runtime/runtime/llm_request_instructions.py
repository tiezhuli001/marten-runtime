from __future__ import annotations

from marten_runtime.runtime.tool_episode_summary_prompt import (
    render_tool_followup_summary_instruction,
)

_GENERIC_TOOL_FINALIZATION_CONTRACT = (
    "Tool finalization contract: when one tool call will fully satisfy the current turn "
    "and the final reply can be deterministic from that tool result alone, set "
    "finalize_response=true on that tool call so the runtime can finish directly. "
    "This means one tool result is already enough to produce the final reply for the current turn. "
    "This applies to single-tool terminal turns such as direct confirmations, direct lists, "
    "direct detail views, direct status reads, and direct fact lookups. "
    "Examples: 现在有哪些会话列表 -> session action=list with finalize_response=true; "
    "告诉我当前北京时间 -> time with finalize_response=true; "
    "当前上下文窗口和 token 使用详情 -> runtime action=context_status with finalize_response=true. "
    "Counterexamples: 先列出会话列表，再切换到 sess_xxx -> do not set finalize_response=true on the list call yet; "
    "先告诉我当前时间，再查 GitHub 最近提交 -> do not set finalize_response=true on the time call yet. "
    "Leave it omitted when another tool call is still needed or when the final answer still "
    "needs model-authored synthesis across multiple results."
)

_CURRENT_TURN_PRIORITY_CONTRACT = (
    "当前用户最新一条消息定义本轮任务边界。"
    "较早历史、历史摘要、recent tool outcome summary 和上一轮结构化输出都只作为背景。"
    "只有当前这条消息明确要求继续上一轮、引用上一轮结果、或跟进后台任务时，才延续旧主题。"
    "否则要重新根据当前这条消息选择工具与回答范围，不要因为上一轮刚用了某个工具族，就在本轮复用同一路径。"
    "例如：上一轮刚返回会话列表/表格/目录时，本轮若问当前时间、上下文窗口、GitHub 仓库或子代理任务，就直接按当前问题选择工具；"
    "只有当前消息再次明确要求会话目录时，才调用 session.list。"
)

_FOLLOWUP_STOP_RULE = (
    "最终答复要覆盖用户当前这句消息里的全部直接要求。"
    "如果用户这句消息同时要求引用上一轮结果和刚得到的工具结果，两部分都要写出来。"
    "如果刚刚的工具结果已经足够回答用户当前问题，直接给出答案并结束。"
    "如果刚得到的工具结果只覆盖当前请求的一部分，继续调用仍然需要的工具或整合已得到的相关结果。"
    "不要把无关或只部分相关的工具结果当成最终答案。"
    "不要在结尾追加“如果你需要/如果你要/如果你愿意/我也可以继续帮你”这类下一步菜单。"
)

_SUBAGENT_TASK_CONTRACT = (
    "Subagent task contract: this request is running inside a child agent. "
    "Complete the child work described by the user message directly. "
    "Treat parent-thread acknowledgement, waiting, delivery, notification, or 主线程 wording as parent-side instructions, not as the child result. "
    "When the child task requires realtime data, GitHub, MCP, time, runtime status, or skill content, call the available tools needed to complete that child task before producing the final child summary."
)
def tool_followup_instruction(
    tool_name: str | None,
    *,
    tool_history_count: int = 0,
    has_evidence_ledger: bool = False,
    required_evidence_count: int = 0,
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
    ledger_instruction = ""
    if has_evidence_ledger:
        ledger_instruction = (
            "The current-turn evidence ledger is already available in the prompt. "
            "Use it as a compact checklist for this turn and cover every required evidence item in the final answer."
        )
        if required_evidence_count > 0:
            ledger_instruction = (
                f"{ledger_instruction} There are {required_evidence_count} required evidence items."
            )
    if tool_name == "runtime":
        base = (
            "以刚刚返回的 runtime 工具结果为主完成用户当前这句请求。"
            "如果当前请求还引用了本会话里刚刚得到、且与当前问题直接相关的事实，可以一并回答。"
            "不要额外展开无关的旧任务结果，也不要补做用户当前没有要求的工具查询。"
        )
        if ledger_instruction:
            base = f"{base}\n\n{ledger_instruction}"
        base = f"{base}\n\n{_FOLLOWUP_STOP_RULE}"
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    if tool_name == "mcp":
        base = (
            "如果你要继续发起 mcp family 调用，必须沿用刚刚看到的精确 server_id 和精确 tool_name，"
            "保持 action 为 list/detail/call 三者之一，并让 arguments 始终是一个对象。"
            "不要自造别名、不要重命名子工具。\n\n"
            + (f"{ledger_instruction}\n\n" if ledger_instruction else "")
            + _FOLLOWUP_STOP_RULE
            + "\n\n"
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
            + (f"{ledger_instruction}\n\n" if ledger_instruction else "")
            + _FOLLOWUP_STOP_RULE
            + "\n\n"
            + render_tool_followup_summary_instruction()
        )
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    if tool_name == "spawn_subagent":
        base = (
            "你已经拿到了刚刚这次 spawn_subagent 的接受结果。"
            "不要再次调用 spawn_subagent 只为了补 finalize_response、补接受文案、或重复同一个后台任务。"
            "如果当前请求到这里已经完成，直接基于这次 accepted/queued/running 结果写最终答复。"
            "如果当前请求还明确要求了别的结果，再继续处理剩余部分。"
            "\n\n"
            + (f"{ledger_instruction}\n\n" if ledger_instruction else "")
            + _FOLLOWUP_STOP_RULE
            + "\n\n"
            + render_tool_followup_summary_instruction()
        )
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    if tool_name:
        base = (
            f"{ledger_instruction}\n\n" if ledger_instruction else ""
        ) + f"{_FOLLOWUP_STOP_RULE}\n\n{render_tool_followup_summary_instruction()}"
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    return None


def is_tool_followup_request(request) -> bool:  # noqa: ANN001
    return bool(request.tool_history) or (
        request.tool_result is not None and bool(request.requested_tool_name)
    )


def request_specific_instruction(request) -> str | None:  # noqa: ANN001
    parts: list[str] = []
    if request.channel_protocol_instruction_text:
        parts.append(request.channel_protocol_instruction_text)
    parts.append(_CURRENT_TURN_PRIORITY_CONTRACT)
    if request.available_tools and request.request_kind != "finalization_retry":
        parts.append(_GENERIC_TOOL_FINALIZATION_CONTRACT)
    if request.request_kind == "subagent":
        parts.append(_SUBAGENT_TASK_CONTRACT)
    if request.request_kind == "contract_repair":
        invalid_final_text = " ".join(str(request.invalid_final_text or "").split()).strip()
        repair_instruction = (
            "上一条回复已经直接结束，但这轮仍未满足运行时合同。"
            "重新判断用户当前这句请求，保持用户明确要求的执行模式、实时性要求和绑定要求。"
            "需要工具时，直接发起当前最合适的工具调用。"
            "只有当前请求本身已经可以直接完成时，才输出最终答复。"
            "不要重复上一条无效回复。"
        )
        if invalid_final_text:
            repair_instruction = (
                f"{repair_instruction}\n\n"
                f"上一条无效回复：{invalid_final_text}"
            )
        parts.append(repair_instruction)
    if request.request_kind == "finalization_retry":
        parts.append(
            "The current-turn evidence ledger already lists the required evidence for this final answer. "
            "All required evidence is already available in the prompt transcript and ledger. "
            "所需的工具结果已经全部提供在上文。"
            "直接基于现有结果生成最终答复。"
            "不要再调用任何工具。"
            "回答里要覆盖已经成功拿到且与本题相关的结果。"
        )
    return "\n\n".join(part for part in parts if part).strip() or None
