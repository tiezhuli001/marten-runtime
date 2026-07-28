from __future__ import annotations

from pydantic import BaseModel, Field

from marten_runtime.tools.builtins.bazi_tool import BAZI_PARAMETERS_SCHEMA


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
    "If an earlier user turn already parked one concrete future task or topic for continuation, treat that named task/topic as valid session context when the current turn says 继续上一轮那个任务, 继续跟进, 接着做, or 压缩后继续.",
    "When a compact summary already gives the main task and unfinished items, phrasing such as 在压缩后的上下文里继续执行, 压缩后继续, or 继续这个长线程任务 means continue that task. Treat 上下文, 长线程, and 当前会话 there as continuation cues, not as session metadata or runtime-number queries.",
    "Ground live current time/date/datetime/timezone facts in the time tool result from this turn, and ground current-session context/token/window/compression facts in the runtime tool result from this turn.",
    "For memory writes/deletes, include the durable scope and bucket explicitly. append/replace/delete should carry scope and section, and append/replace should also carry content and type. Typical section names include preferences, facts, profile, project, and constraints.",
    "Only confirm a durable-memory write after a successful memory tool result in this turn, and only answer live current time/date/datetime after a time tool result in this turn.",
    "Even when similar facts already appear in memory, summaries, or prior replies, explicit durable-memory write requests still require a memory tool result in this turn, and live time/runtime status requests still require their corresponding time/runtime tool result in this turn.",
    "When the user already names one visible session by title or label, prefer one direct session.resume/session.show call with session_id or session_ref. Reserve session.list for explicit session catalog requests.",
    "Domain nouns already present in the task summary or bound history are task content. They stay in plain task execution unless the current turn explicitly asks for one skill body or the task truly depends on a missing skill document.",
    "When drafting copy, examples, templates, or field descriptions that mention time/runtime/session/memory outputs, label those snippets as 示例/Example or quote them as samples instead of phrasing them as actual current-turn facts or completed actions.",
    "When the user asks for one concrete result, answer with that result and stop after the requested scope. Do not append optional next-step menus such as 如果你需要 / 如果你要 / 如果你愿意 / 我也可以继续帮你.",
    "Choose tools by the result the user wants, not by one shared noun. Examples: 切换到 sess_xxx 这个会话 -> session.resume; 新开一个会话 -> session.new; 当前会话的上下文窗口/当前这轮 token 使用详情 -> runtime.context_status; 会话列表/有哪些会话 -> session.list.",
    "When one tool call will fully satisfy the current turn and the final reply can be deterministic from that tool result alone, set finalize_response=true on that tool call so the runtime can finish directly. This means one tool result is already enough to produce the final reply for the current turn. Examples: 现在有哪些会话列表 -> session.list with finalize_response=true; 告诉我当前北京时间 -> time with finalize_response=true; 当前上下文窗口和 token 使用详情 -> runtime.context_status with finalize_response=true. Counterexample: 先告诉我当前时间，再查 GitHub 最近提交 -> do not finalize on the first tool call. Leave it omitted when another tool call or a model-authored combined answer is still needed.",
    "When the user explicitly requests an execution mode such as delegation, background execution, direct inspection, or immediate in-session completion, that requested execution mode is part of the task contract. Do not replace requested delegation/background execution with a parent-session direct tool call that happens to answer the same fact.",
)


def get_capability_declarations() -> dict[str, CapabilityDeclaration]:
    return {
        "bazi": CapabilityDeclaration(
            name="bazi",
            summary="Calculate a Bazi chart, Dayun sequence, or birth-time candidates from four pillars.",
            actions=["chart", "dayun", "resolve_pillars"],
            usage_rules=[
                "Use chart for a deterministic natal chart and dayun for the matching fortune-cycle sequence.",
                "Use resolve_pillars with gender when the user provides four complete Jiazi pillars; a unique already-born candidate can seed dayun.",
                "For true_solar, collect a birthPlace at city or district precision; coordinates are internal.",
            ],
            parameters_schema=BAZI_PARAMETERS_SCHEMA,
        ),
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
                "When making action=call, copy server_id and tool_name exactly from the MCP capability catalog or a prior mcp detail/list result; do not invent aliases or renamed subtools, and avoid invented convenience names.",
                "When mcp.list already shows a tool_names entry that matches the needed repository/file/commit operation, that list result is sufficient to make the mcp.call; do not call mcp.detail just to re-confirm a visible tool name.",
                "Set finalize_response=true only when this exact MCP result should end the turn immediately with a direct deterministic reply. Leave it omitted when the current request still needs another tool call or a model-authored combined answer.",
                "Can answer GitHub repository questions and other MCP-backed live facts exposed by configured servers.",
                "When the user asks for one concrete GitHub fact, return that fact directly and stop after the requested scope instead of appending optional follow-up offers.",
                "For GitHub commit-history questions such as 最近一次提交, 最新提交, or latest commit, choose from the exact visible MCP tools in the current catalog and prefer the smallest visible tool sequence that can identify the latest commit directly. Use a detail-oriented visible tool only after a concrete commit sha is already known.",
                "For analysis, diagnosis, comparison, or review tasks, mcp.list/detail results, tool catalogs, github.get_file_contents payloads, and blob SHAs are intermediate evidence unless the user explicitly asked for those exact artifacts. Use them to derive the requested conclusion.",
                "For common GitHub repository reads such as README content, directory structure, or commit history, prefer simple visible repository/file/commit tools over generic GraphQL tools when both are visible. Use GraphQL only when the user explicitly asks for GraphQL or the visible catalog lacks a simpler matching tool.",
                "For README structure tasks, when a visible mcp.list result includes github tool_names with get_file_contents, call that exact tool directly with owner, repo, and path=README.md instead of spending a turn on mcp.detail.",
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
                    "tool_name": {
                        "type": "string",
                        "description": (
                            "Exact visible MCP tool name. For GitHub latest-commit or recent-commit "
                            "questions, select a visible history/list tool that can return commit records "
                            "when such a tool exists; avoid invented convenience names."
                        ),
                    },
                    "query": {"type": "string"},
                    "arguments": {
                        "type": "object",
                        "description": (
                            "Arguments for the chosen exact MCP tool. Keep it an object. For GitHub "
                            "commit-history lookups, include owner and repo when known, and include "
                            "the tool's small result-limit parameter when the visible tool supports one."
                        ),
                    },
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
                "Ground current-session context/token/window/compression answers in this-turn runtime result.",
                "Only produce concrete current-session context/token/window/compression figures after a this-turn runtime result is available.",
                "Even when prior replies or summaries mention token counts or effective window figures, a fresh current-session status question still belongs to runtime and still needs a this-turn runtime result.",
                "Set finalize_response=true only when this runtime status result itself should end the turn immediately with a direct deterministic reply. Leave it omitted when the current request still needs another tool call or a model-authored combined answer.",
                "This tool answers current-session context accounting; session catalogs and session switching belong to session.",
                "It also covers why the effective window is a certain size for the current session.",
                "Requests such as 当前会话的上下文窗口使用情况, 当前上下文窗口多大, 为什么有效窗口是 184000, and 当前这轮 token 使用详情 belong here.",
                "Phrases like 当前会话 or 这个会话 still belong to runtime when the question is about context, tokens, replay, or compression.",
                "Continuation cues such as 继续旧会话, 在新会话里继续, or 继续刚切换的会话 do not belong here by themselves. Those cues stay on plain task continuation unless the user explicitly asks for context/token/window/compression numbers.",
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
                "Use this only for self-improve evidence and candidate management.",
                "Use it when the user explicitly asks about self-improve evidence, lesson candidates, saved lessons, or this subsystem's review data.",
                "Plain task continuation, long-thread continuation, repository execution, and generic problem solving do not belong here.",
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
                "Use action=new only when the current turn itself asks to create/start/open/switch to a fresh session. Treat that as the new session request. A later turn that says it is already in the new session and wants to continue work is plain task continuation.",
                "Use action=resume with an exact session_id for requests to continue or switch back to an existing session.",
                "Use action=show for requests to inspect the current bound session or one known session summary/detail.",
                "Use action=list only for explicit catalog requests such as 会话列表, 列出会话, or 有哪些会话. action=list is not a safe fallback for switching or runtime questions.",
                "For one direct switch such as 新开一个会话 or 切换到 sess_xxx, prefer finalize_response=true when that single session result already completes the turn with a direct confirmation reply.",
                "Set finalize_response=true only when this exact session result should end the turn immediately with a direct confirmation/detail reply. Leave it omitted when the current request still needs another tool call or a model-authored combined answer.",
                "Runtime context size belongs to runtime, and scheduled job lists belong to automation.",
                "After a successful session.new or session.resume, follow-up requests such as 在新会话里继续这个任务 or 继续旧会话 belong to plain task execution in the now-bound session. Use session again only when the user wants session metadata or another switch.",
                "Across later turns, cues like 继续旧会话, 在新会话里继续, or 继续刚切换的会话 still mean continue work inside the already bound session; do not repeat resume/show/list unless the user asks for another switch or explicit session metadata.",
                "Phrases such as 在新会话里继续, 在刚才新会话继续, or 继续刚切换的会话 state the already-bound workspace for the task. They are not a fresh-session creation request by themselves.",
                "When the current turn is only one of those continuation cues, answer with task continuation or a brief continuation confirmation. Do not turn it into a current-session detail card with title, message_count, or session_id unless the user explicitly asked for session metadata.",
                "If the resumed/newly bound session still lacks enough task detail, keep the brief continuation confirmation and ask for the minimum task anchor needed. Do not switch to session.show/list or runtime just to fill empty detail.",
                "Compaction continuation requests such as 在压缩后的上下文里继续执行, 压缩后继续, or 继续这个长线程任务 also belong to plain task execution when the compact summary already provides the task anchor and unfinished items.",
                "Words like 上下文, 长线程, or 当前会话 only map here when the user is explicitly asking for session identity, session detail, session list, or a session switch.",
                "Previous turns that listed sessions are only background; if the current turn asks about context window, token usage, replay budget, or compression, leave that turn to runtime and do not call session.",
                "If the previous reply showed a session table or current-session row, treat that as background only; do not repeat action=list unless the current turn explicitly asks for the session catalog again.",
                "If the request includes a sess_xxx target, pass that exact session_id.",
                "If the user names one visible session by title or label such as 旧会话, 当前会话, or 调试会话, pass that concrete label through session_ref and go directly to resume/show instead of listing first.",
                "Requests like 切换到 sess_xxx 这个会话 or 恢复 sess_xxx belong to action=resume. Requests like 当前会话 id, 当前会话编号, or 当前会话详情 belong to action=show.",
                "Requests like 当前会话的上下文窗口使用情况 belong to runtime instead of session.",
            ],
            examples=[
                "切换到 sess_dcce8f9c 这个会话",
                "恢复 sess_dcce8f9c",
                "恢复到旧会话",
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
                            "Copy the exact sess_xxx token from the user when one is present. It is preferred "
                            "when the user gave an exact sess_xxx token. For show, omit it only when the user is "
                            "explicitly asking about the current bound session and no session_ref is needed."
                        ),
                    },
                    "session_ref": {
                        "type": "string",
                        "description": (
                            "For resume/show when the user names one visible session by title or label instead "
                            "of exact sess_xxx. Copy that concrete visible session title or label here, such as "
                            "旧会话, 当前会话, or 调试会话."
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
                "For explicit durable-memory requests such as 记住, 写入记忆, or 保存到记忆, reach memory first before confirming success.",
                "For requests that update or overwrite a current durable preference or standing rule, prefer replace on section=preferences unless the user explicitly asked to append another separate item.",
                "For append/replace/delete, include intent explicitly. Use intent=durable_write for append/replace and intent=durable_delete for delete so the host can verify that this turn is a structured durable-memory mutation.",
                "For append/replace/delete, include source_excerpt copied from the current user message. Quote the exact request span that authorizes the durable mutation so the host can anchor this write/delete to the current turn without reparsing prose.",
                "For append/replace/delete, include scope, type, and section explicitly. Use scope=global for user-wide memory, scope=agent for the selected runtime agent, and scope=workspace only when a workspace_id is available. Type should be preference, fact, constraint, or workflow_hint. Typical sections are preferences, facts, profile, workflow_hints, and constraints.",
                "For append/replace, include the durable content text as well. For delete, section is still required and content is optional when clearing a whole bucket.",
                "Only confirm 已记住 / 已更新 after a successful memory tool result exists in this turn.",
                "Even when the requested preference already appears in attached memory, an explicit 记住 / 更新记忆 / 修改记忆 request still requires a memory tool call in this turn before confirming success.",
                "When the current prompt already includes the user's durable memory state, requests like 读取当前偏好 or 查看当前偏好 can answer from that attached memory state directly; use get when the needed durable state is not already available.",
                "When the latest durable memory state is already attached and the user is only asking what was remembered or what the current preference is, answer from that attached state directly instead of calling get again.",
                "Immediate read-after-write follow-ups such as 读取当前偏好, 说明你记住了什么, or 复述刚才记住的内容 should stay on the just-written memory state when it is already present in the prompt.",
                "Short confirmation-only or literal-output requests such as 收到的话只回两个字 are not durable memory writes. Reply directly and do not call memory for those turns.",
                "Session history questions belong to session, and short-lived context accounting belongs to runtime.",
            ],
            examples=[
                "记住这个长期偏好：我默认使用 minimax",
                "记住：以后始终用中文回复（scope=global,type=preference,section=preferences）",
                "更新记忆：以后回答尽量简洁（scope=global,type=preference,section=preferences）",
                "记住 main agent 约束：保持 thin harness 边界（scope=agent,type=constraint）",
                "说明你记住了什么",
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
                    "intent": {
                        "type": "string",
                        "enum": ["durable_write", "durable_delete"],
                        "description": (
                            "Required for append/replace/delete. Use durable_write for append/replace "
                            "and durable_delete for delete."
                        ),
                    },
                    "source_excerpt": {
                        "type": "string",
                        "description": (
                            "Required for append/replace/delete. Copy the exact current-user-message span "
                            "that authorizes this durable memory mutation."
                        ),
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["global", "agent", "workspace"],
                        "description": "Required for append/replace/delete. global is user-wide, agent is selected-agent memory, workspace is local workspace memory.",
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Required when scope=agent unless supplied by runtime tool context.",
                    },
                    "workspace_id": {
                        "type": "string",
                        "description": "Required when scope=workspace.",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["preference", "fact", "constraint", "workflow_hint"],
                        "description": "Required for append/replace. Describes the durable memory kind.",
                    },
                    "section": {
                        "type": "string",
                        "description": (
                            "Required for append/replace/delete. Use a stable durable bucket such as "
                            "preferences, facts, profile, workflow_hints, or constraints."
                        ),
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Optional 0-100 priority for prompt loading. Default is 50.",
                    },
                    "memory_id": {
                        "type": "string",
                        "description": "Optional exact memory item id for replace/delete.",
                    },
                    "source_run_id": {
                        "type": "string",
                        "description": "Optional run id provenance; runtime may supply it from tool context.",
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "Required for append/replace. Use the durable statement to store. For delete, "
                            "omit it only when clearing the whole section."
                        ),
                    },
                },
                "required": ["action"],
                "allOf": [
                    {
                        "if": {"properties": {"action": {"enum": ["append", "replace"]}}},
                        "then": {"required": ["intent", "source_excerpt", "scope", "type", "section", "content"]},
                    },
                    {
                        "if": {"properties": {"action": {"enum": ["delete"]}}},
                        "then": {"required": ["intent", "source_excerpt", "scope", "section"]},
                    },
                ],
                "additionalProperties": False,
            },
        ),
        "knowledge": CapabilityDeclaration(
            name="knowledge",
            summary="Manage namespace-scoped Knowledge/RAG sources, chunks, embeddings, retrieval, reindex, and ingest job progress.",
            actions=[
                "ingest_text",
                "ingest_file",
                "ingest_status",
                "cancel_ingest",
                "search",
                "get_chunk",
                "delete_source",
                "reindex",
                "stats",
                "model_status",
                "unload_models",
            ],
            usage_rules=[
                "Use this when the user asks to build, search, inspect, delete, or reindex a knowledge base.",
                "The LLM decides whether the current turn needs knowledge. Host code only executes the selected action.",
                "Always include namespace when the user named one. Use a configured default namespace only when the task context already implies it.",
                "For large files, call ingest_file and report the returned job_id/status rather than waiting for all indexing work inside the conversation turn.",
                "For search answers, use returned source_id, chunk_id, score parts, and diagnostics as citation evidence.",
                "For delete_source and reindex, the user request should clearly authorize the operation.",
                "Embedding model changes use current [knowledge.embedding] config and require manual action=reindex for the namespace.",
                "Use model_status to inspect loaded/not_loaded state and unload_models to release local embedding/reranker memory on request.",
            ],
            examples=[
                "把这个 txt 写入 fanqie 知识库",
                "搜索 fanqie 知识库里主角第一次遇到师父的章节",
                "knowledge.reindex --namespace fanqie",
                "查看知识库模型内存状态",
                "卸载 knowledge 模型释放内存",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "ingest_text",
                            "ingest_file",
                            "ingest_status",
                            "cancel_ingest",
                            "search",
                            "get_chunk",
                            "delete_source",
                            "reindex",
                            "stats",
                            "model_status",
                            "unload_models",
                        ],
                    },
                    "namespace": {"type": "string"},
                    "source": {"type": "object"},
                    "file_path": {"type": "string"},
                    "job_id": {"type": "string"},
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1},
                    "filters": {"type": "object"},
                    "chunk_id": {"type": "string"},
                    "source_id": {"type": "string"},
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
                "If compact summary, working context, or bound session history already contains enough task detail to continue, continue directly instead of loading a skill just to explore.",
                "Plain continuation cues such as 继续这个任务, 压缩后继续, or 继续上一轮那个任务 do not belong here unless the user also asked for a named skill or the task truly depends on one missing skill body.",
                "When loading a skill, copy the exact skill_id from Visible skills. Do not translate, paraphrase, or invent a new skill name.",
                "Task-summary nouns such as object names,告警名,仓库名,卡片名, or 渲染问题 are still task content. Keep working on that task directly unless the current turn truly needs one missing skill body.",
            ],
            examples=[
                "加载 pua skill",
                "读取 long-run-execution skill",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["load"]},
                    "skill_id": {
                        "type": "string",
                        "description": (
                            "Exact visible skill_id only. Copy it exactly from Visible skills; do not translate "
                            "or invent another name."
                        ),
                    },
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
                "Ground current time/date/datetime answers in this-turn time tool result, including first-turn plain questions such as 现在几点, 现在北京时间, and UTC 时间.",
                "Only answer a live current-time/current-date/current-datetime request after this-turn time tool result is available.",
                "Even when timestamps appear elsewhere in the prompt, a fresh current-time question still needs a this-turn time tool result.",
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
                "Keep the child task brief semantic and goal-first. Describe the target conclusion, target repository or object when already known, and required output shape. Do not pre-script exact MCP subtool names, path-by-path traversal plans, or directory-by-directory fetch sequences inside the task brief.",
                "When the current prompt already includes one bound repository context, carry that repository into the child task as the default target repository. Do not ask the child to request owner/repo again unless the user explicitly asked to switch repositories.",
                "Keep that explicit delegation/background execution mode stable across retries, failover, and repair turns for the same user request.",
                "Infer a concise task brief, label, context_mode, and tool profile; do not ask the user for internal field names.",
                "Set finalize_response=true only when this acceptance result itself should end the turn immediately. Leave it omitted when the current request still needs another tool call or a model-authored combined answer.",
                "The standard MCP-capable child profile is the default when tool_profile is omitted.",
                "When the user explicitly asks to split work into multiple child tasks, keep launching one distinct child task per requested slice until every requested child task has been dispatched.",
                "When the current prompt already includes a real prior child-task state or completion summary and the user is only asking whether that task finished or what it concluded, answer from that attached state directly, preserving the child summary's concrete object phrase and coverage nouns in one sentence. Reuse the attached summary's own task objects, document/module names, structure layers, coverage terms, and conclusion phrases instead of flattening them into a more generic abstraction. Use spawn_subagent only for launching a new child task.",
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


def render_capability_catalog_for_request(
    declarations: dict[str, CapabilityDeclaration],
    *,
    available_tools: list[str] | None = None,
    mcp_catalog_text: str | None = None,
) -> str | None:
    if not declarations:
        return None
    allowed = set(str(item).strip() for item in list(available_tools or []) if str(item).strip())
    if not allowed:
        return render_capability_catalog(
            declarations,
            mcp_catalog_text=mcp_catalog_text,
        )
    lines = ["Capability catalog:"]
    lines.extend(f"- Global rule: {rule}" for rule in GLOBAL_CAPABILITY_RULES)
    for name, declaration in declarations.items():
        if name not in allowed:
            continue
        lines.append(f"- {name}: {render_tool_description_for_provider(declaration)}")
    if "mcp" in allowed and mcp_catalog_text:
        lines.append("")
        lines.append(mcp_catalog_text)
    return "\n".join(lines)


def render_tool_description_for_provider(
    declaration: CapabilityDeclaration,
) -> str:
    segments = [declaration.summary.strip()]
    if declaration.actions:
        segments.append(f"Actions: {', '.join(declaration.actions)}.")
    if declaration.name in {"mcp", "session", "spawn_subagent"} and declaration.usage_rules:
        segments.append(f"Rules: {' '.join(declaration.usage_rules)}")
    return " ".join(segment for segment in segments if segment)


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
