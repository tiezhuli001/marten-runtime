from __future__ import annotations

from pydantic import BaseModel, Field


class CapabilityDeclaration(BaseModel):
    name: str
    summary: str
    actions: list[str] = Field(default_factory=list)
    usage_rules: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    parameters_schema: dict[str, object] = Field(
        default_factory=lambda: {"type": "object"}
    )


GLOBAL_CAPABILITY_RULES: tuple[str, ...] = (
    "Re-evaluate tool choice from the current user turn every time. Do not reuse the previous turn's tool family just because the last reply showed a table, card, catalog, or other structured output.",
    "If the user explicitly requests an available execution mode, tool family, or delivery mode, treat that as part of the task contract and honor it first instead of silently substituting a different path just because it could also answer the question.",
    "Treat historical summaries and prior-turn tool results as background only; any claim about the current turn's accepted/running/completed/cancelled/delivered state must be grounded in actions or tool results that actually happened in this turn.",
    "When the user asks for one concrete result, answer with that result and stop after the requested scope. Do not append optional next-step menus such as 如果你需要 / 如果你要 / 如果你愿意 / 我也可以继续帮你.",
    "Choose tools by the result the user wants, not by one shared noun. Examples: 切换到 sess_xxx 这个会话 -> session.resume; 新开一个会话 -> session.new; 当前会话的上下文窗口/当前这轮 token 使用详情 -> runtime.context_status; 会话列表/有哪些会话 -> session.list.",
    "When one tool call will fully satisfy the current turn and the final reply can be deterministic from that tool result alone, set finalize_response=true on that tool call so the runtime can finish directly. This means one tool result is already enough to produce the final reply for the current turn. Examples: 现在有哪些会话列表 -> session.list with finalize_response=true; 告诉我当前北京时间 -> time with finalize_response=true; 当前上下文窗口和 token 使用详情 -> runtime.context_status with finalize_response=true. Counterexample: 先告诉我当前时间，再查 GitHub 最近提交 -> do not finalize on the first tool call. Leave it omitted when another tool call or a model-authored combined answer is still needed.",
    "When the user explicitly requests an execution mode such as delegation, background execution, direct inspection, or immediate in-session completion, that requested execution mode is part of the task contract. Do not replace requested delegation/background execution with a parent-session direct tool call that happens to answer the same fact.",
)


def get_capability_declarations() -> dict[str, CapabilityDeclaration]:
    return {
        "automation": CapabilityDeclaration(
            name="automation",
            summary="Manage recurring automations and inspect scheduled jobs, timed tasks, cron jobs, and 定时任务.",
            actions=[
                "register",
                "list",
                "detail",
                "update",
                "delete",
                "pause",
                "resume",
            ],
            usage_rules=[
                "Use this when the user asks about scheduled jobs, timed tasks, cron rules, automations, or creating, updating, pausing, resuming, or deleting a recurring task.",
                "Scheduled job lists belong to automation; session lists belong to session, and current context window/token accounting belongs to runtime.",
            ],
            examples=[
                "当前有哪些定时任务",
                "暂停 github digest 这个自动化",
                "创建一个每周一早上 9 点执行的自动化",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "register",
                            "list",
                            "detail",
                            "update",
                            "delete",
                            "pause",
                            "resume",
                        ],
                    },
                    "automation_id": {"type": "string"},
                    "include_disabled": {"type": "boolean"},
                },
                "required": ["action"],
                "additionalProperties": True,
            },
        ),
        "mcp": CapabilityDeclaration(
            name="mcp",
            summary=(
                "One family tool that fronts configured MCP servers and returns live structured facts "
                "from external systems."
            ),
            actions=["list", "detail", "call"],
            usage_rules=[
                "Use action=list to inspect available servers, action=detail with an exact server_id to inspect that server, and action=call with an exact server_id, exact tool_name, and an object arguments payload.",
                "When making action=call, copy server_id and tool_name exactly from the MCP capability catalog or a prior mcp detail/list result; do not invent aliases or renamed subtools.",
                "Set finalize_response=true only when this exact MCP result should end the turn immediately with a direct deterministic reply. Leave it omitted when the current request still needs another tool call or a model-authored combined answer.",
                "Can answer GitHub repository questions and other MCP-backed live facts exposed by configured servers.",
                "When the user asks for one concrete GitHub fact, return that fact directly and stop after the requested scope instead of appending optional follow-up offers.",
                "For GitHub commit-history questions such as 最近一次提交, 最新提交, or latest commit, prefer a commit-history/list surface that can identify the latest commit directly. Use a commit-detail surface only when a concrete commit sha is already known.",
            ],
            examples=[
                "GitHub 这个仓库最近一次提交是什么时候",
                "查这个仓库最新提交的 sha 和时间",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "detail", "call"]},
                    "server_id": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "query": {"type": "string"},
                    "arguments": {"type": "object"},
                    "finalize_response": {
                        "type": "boolean",
                        "description": (
                            "Set true only when this MCP result itself should end the turn with a direct "
                            "deterministic reply. Omit it when another tool call or a combined final answer "
                            "is still needed."
                        ),
                    },
                },
                "required": ["action"],
                "additionalProperties": True,
            },
        ),
        "runtime": CapabilityDeclaration(
            name="runtime",
            summary=(
                "Only family tool for live current-session context window, token usage, "
                "effective window, replay budget, and compression status questions, even "
                "when the user says 当前会话 or 这个会话."
            ),
            actions=["context_status"],
            usage_rules=[
                "Use this when the user asks about current context window usage, token accounting, effective window size, compression status, replay policy, or conversation context health.",
                "The current turn wins over previous turns: if the user is now asking about current context window or token usage, stay on runtime even when previous turns showed session lists or switched sessions.",
                "Returns live runtime context data for the current session.",
                "Set finalize_response=true only when this runtime status result itself should end the turn immediately with a direct deterministic reply. Leave it omitted when the current request still needs another tool call or a model-authored combined answer.",
                "This tool answers current-session context accounting; session catalogs and session switching belong to session.",
                "It also covers why the effective window is a certain size for the current session.",
                "Requests such as 当前会话的上下文窗口使用情况, 当前上下文窗口多大, 为什么有效窗口是 184000, and 当前这轮 token 使用详情 belong here.",
                "Phrases like 当前会话 or 这个会话 still belong to runtime when the question is about context, tokens, replay, or compression.",
                "If the previous reply showed a session catalog, current-session context/token/window questions still belong here.",
            ],
            examples=[
                "当前会话的上下文窗口使用情况",
                "当前上下文窗口多大",
                "为什么有效窗口是 184000",
                "当前这轮 token 使用详情",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["context_status"],
                        "description": (
                            "Use context_status for current-session context window, token usage, "
                            "replay budget, compression status, or effective-window questions."
                        ),
                    },
                    "finalize_response": {
                        "type": "boolean",
                        "description": (
                            "Set true only when this runtime status result itself should end the turn "
                            "with a direct deterministic reply. Omit it when another tool call or a "
                            "combined final answer is still needed."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        ),
        "self_improve": CapabilityDeclaration(
            name="self_improve",
            summary="Inspect self-improve evidence, candidates, and active lessons.",
            actions=[
                "list_candidates",
                "candidate_detail",
                "delete_candidate",
                "summary",
                "list_evidence",
                "list_system_lessons",
                "save_candidate",
            ],
            usage_rules=[
                "Use this only for self-improve evidence and candidate management."
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list_candidates",
                            "candidate_detail",
                            "delete_candidate",
                            "summary",
                            "list_evidence",
                            "list_system_lessons",
                            "save_candidate",
                        ],
                    },
                    "candidate_id": {"type": "string"},
                },
                "required": ["action"],
                "additionalProperties": True,
            },
        ),
        "session": CapabilityDeclaration(
            name="session",
            summary=(
                "Session catalog, switch, and detail only. Use this for explicit session list/show/new/resume tasks. "
                "Do not use it for current-session context/token/window/compression questions or unrelated GitHub, "
                "subagent, MCP, or time requests."
            ),
            actions=["resume", "new", "show", "list"],
            usage_rules=[
                "Use this when the user wants to switch to an existing session, start a fresh session, inspect the current bound session or one known session record, or browse the session catalog.",
                "Use action=new for requests to start a fresh session in the current channel conversation.",
                "Use action=resume with an exact session_id for requests to continue or switch back to an existing session.",
                "Use action=show for requests to inspect the current bound session or one known session summary/detail.",
                "Use action=list only for explicit catalog requests such as 会话列表, 列出会话, or 有哪些会话. action=list is not a safe fallback for switching or runtime questions.",
                "Set finalize_response=true only when this exact session result should end the turn immediately with a direct confirmation/detail reply. Leave it omitted when the current request still needs another tool call or a model-authored combined answer.",
                "Runtime context size belongs to runtime, and scheduled job lists belong to automation.",
                "Previous turns that listed sessions are only background; if the current turn asks about context window, token usage, replay budget, or compression, leave that turn to runtime and do not call session.",
                "If the previous reply showed a session table or current-session row, treat that as background only; do not repeat action=list unless the current turn explicitly asks for the session catalog again.",
                "If the request includes a sess_xxx target, pass that exact session_id.",
                "Requests like 切换到 sess_xxx 这个会话 or 恢复 sess_xxx belong to action=resume. Requests like 当前会话 id, 当前会话编号, or 当前会话详情 belong to action=show.",
                "Requests like 当前会话的上下文窗口使用情况 belong to runtime instead of session.",
            ],
            examples=[
                "切换到 sess_dcce8f9c 这个会话",
                "恢复 sess_dcce8f9c",
                "新开一个会话",
                "告诉我当前会话 id",
                "查看 sess_dcce8f9c 的摘要",
                "现在有哪些会话列表",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["resume", "new", "show", "list"],
                        "description": (
                            "Use resume to switch/continue an exact sess_xxx target. "
                            "Use new to start a fresh session. "
                            "Use show for the current bound session or one known session record. "
                            "Use list only for explicit session catalog requests such as 会话列表 or 有哪些会话."
                        ),
                    },
                    "session_id": {
                        "type": "string",
                        "description": (
                            "Required for resume. For show, Copy the exact sess_xxx token from the user "
                            "when one is present; omit it only when the user is explicitly asking about the current bound session."
                        ),
                    },
                    "finalize_response": {
                        "type": "boolean",
                        "description": (
                            "Set true only when this session tool result itself should end the turn "
                            "with a direct deterministic reply. Omit it when another tool call or a "
                            "combined final answer is still needed."
                        ),
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        ),
        "memory": CapabilityDeclaration(
            name="memory",
            summary="Read or update the current user's thin long-term memory for stable preferences and durable facts.",
            actions=["get", "append", "replace", "delete"],
            usage_rules=[
                "Use this only when the user explicitly wants to remember, inspect, replace, or delete durable memory.",
                "Session history questions belong to session, and short-lived context accounting belongs to runtime.",
            ],
            examples=[
                "记住我默认使用 minimax",
                "查看我的长期记忆",
                "删除我之前存的偏好",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "append", "replace", "delete"],
                    },
                    "section": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        ),
        "skill": CapabilityDeclaration(
            name="skill",
            summary="Load one skill body on demand when the visible summary is not enough.",
            actions=["load"],
            usage_rules=[
                "Read visible skill summaries first and load only the one that clearly applies.",
                "Use this when the user explicitly names a skill or when one visible skill summary is clearly insufficient for the task.",
            ],
            examples=[
                "加载 pua skill",
                "读取 long-run-execution skill",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["load"]},
                    "skill_id": {"type": "string"},
                },
                "required": ["action", "skill_id"],
                "additionalProperties": False,
            },
        ),
        "time": CapabilityDeclaration(
            name="time",
            summary=(
                "Read the live current time for a requested timezone or offset, including natural-language "
                "queries like 现在几点 or what time is it."
            ),
            actions=[],
            usage_rules=[
                "Use this when the user asks for the current time, date, datetime, or a timezone-specific current time.",
                "Returns live clock data rather than remembered or inferred time values.",
                "Set finalize_response=true only when this exact clock result should end the turn immediately with a direct deterministic reply. Leave it omitted when the current request still needs another tool call or a model-authored combined answer.",
            ],
            examples=[
                "现在几点",
                "北京时间",
                "UTC 时间",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "timezone": {"type": "string"},
                    "tz": {"type": "string"},
                    "finalize_response": {
                        "type": "boolean",
                        "description": (
                            "Set true only when this clock result itself should end the turn with a "
                            "direct deterministic reply. Omit it when another tool call or a combined "
                            "final answer is still needed."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        ),
        "spawn_subagent": CapabilityDeclaration(
            name="spawn_subagent",
            summary=(
                "Delegate a background task to an isolated child session and return an immediate acceptance reply. "
                "Requests like 开启子代理查询 GitHub / MCP / 外部实时数据 belong here."
            ),
            actions=[],
            usage_rules=[
                "Use this for background or isolated child execution when the user wants asynchronous work or when isolating tool-heavy side work would keep the primary conversation cleaner.",
                "A previous session catalog reply is only background. Current-turn requests to 开启子代理, 后台执行, or query GitHub in the background still belong here.",
                "If the user explicitly requests delegation/background execution, keep that execution mode and package the work into the child task instead of replacing it with a parent-session direct tool call.",
                "The task field is only for the child work itself; keep parent-thread acknowledgement, waiting, delivery, and notification wording out of the child task brief.",
                "Keep that explicit delegation/background execution mode stable across retries, failover, and repair turns for the same user request.",
                "Infer a concise task brief, label, context_mode, and tool profile; do not ask the user for internal field names.",
                "Set finalize_response=true only when this acceptance result itself should end the turn immediately. Leave it omitted when the current request still needs another tool call or a model-authored combined answer.",
                "The standard MCP-capable child profile is the default when tool_profile is omitted.",
                "The restricted profile only has runtime, skill, and time.",
                "Use tool_profile=standard or tool_profile=mcp for MCP, web/API, or other external live data because those child tasks need MCP access.",
                "Use tool_profile=restricted only when the child should stay on runtime, skill, and time.",
                "Omit optional fields when defaults are already correct; do not send placeholder values such as agent_id=default.",
                "Only use acceptance/waiting wording such as 已受理, 后台执行中, or 请等待子 agent 返回结果 after this turn actually called spawn_subagent and received an accepted/queued/running result; do not infer current task state from historical summaries.",
            ],
            examples=[
                "开一个子代理在后台跑测试",
                "把这个任务交给子 agent",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "label": {"type": "string"},
                    "tool_profile": {
                        "type": "string",
                        "enum": ["restricted", "standard", "elevated", "mcp"],
                        "description": (
                            "Omit the field to get the default standard behavior. "
                            "restricted exposes runtime/skill/time only. "
                            "standard or mcp should be used for MCP, web/API, or other external live-data tasks because they need MCP access."
                        ),
                    },
                    "context_mode": {
                        "type": "string",
                        "enum": ["brief_only", "brief_plus_snapshot"],
                        "description": (
                            "Usually omit this and keep the default brief_only behavior. "
                            "Use brief_plus_snapshot only when the child needs the parent compacted snapshot."
                        ),
                    },
                    "notify_on_finish": {"type": "boolean"},
                    "finalize_response": {
                        "type": "boolean",
                        "description": (
                            "Set true only when this acceptance result itself should end the turn with "
                            "a direct deterministic acknowledgement. Omit it when the current request "
                            "still needs more tool work or a combined final answer."
                        ),
                    },
                    "agent_id": {
                        "type": "string",
                        "description": (
                            "Usually omit this. Set it only when intentionally targeting a known registered child agent; "
                            "do not send placeholder values like default."
                        ),
                    },
                },
                "required": ["task"],
                "additionalProperties": False,
            },
        ),
        "cancel_subagent": CapabilityDeclaration(
            name="cancel_subagent",
            summary="Cancel a background subagent task by task id when the user wants to stop an already accepted child task.",
            actions=[],
            usage_rules=[
                "Use this only when the user is asking to stop or cancel an existing subagent/background task."
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
        ),
    }


def render_capability_catalog(
    declarations: dict[str, CapabilityDeclaration],
    *,
    mcp_catalog_text: str | None = None,
) -> str | None:
    if not declarations:
        return None
    lines = ["Capability catalog:"]
    lines.extend(f"- Global rule: {rule}" for rule in GLOBAL_CAPABILITY_RULES)
    for name, declaration in declarations.items():
        action_text = (
            f" Actions: {', '.join(declaration.actions)}."
            if declaration.actions
            else ""
        )
        usage_text = (
            f" Rules: {' '.join(declaration.usage_rules)}"
            if declaration.usage_rules
            else ""
        )
        example_text = (
            f" Examples: {'; '.join(declaration.examples)}."
            if declaration.examples
            else ""
        )
        lines.append(
            f"- {name}: {declaration.summary}{action_text}{usage_text}{example_text}".strip()
        )
    if mcp_catalog_text:
        lines.append("")
        lines.append(mcp_catalog_text)
    return "\n".join(lines)


def render_tool_description(declaration: CapabilityDeclaration) -> str:
    segments = [declaration.summary]
    if declaration.actions:
        segments.append(f"Actions: {', '.join(declaration.actions)}.")
    if declaration.usage_rules:
        segments.append(f"Rules: {' '.join(declaration.usage_rules)}")
    if declaration.examples:
        segments.append(f"Examples: {'; '.join(declaration.examples)}.")
    return " ".join(segment.strip() for segment in segments if segment.strip())


def get_parameters_schema(declaration: CapabilityDeclaration) -> dict[str, object]:
    return dict(declaration.parameters_schema)
