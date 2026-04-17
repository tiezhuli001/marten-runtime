from __future__ import annotations

from pydantic import BaseModel, Field


class CapabilityDeclaration(BaseModel):
    name: str
    summary: str
    actions: list[str] = Field(default_factory=list)
    usage_rules: list[str] = Field(default_factory=list)
    parameters_schema: dict[str, object] = Field(
        default_factory=lambda: {"type": "object"}
    )


GLOBAL_CAPABILITY_RULES: tuple[str, ...] = (
    "If the user explicitly requests an available execution mode, tool family, or delivery mode, treat that as part of the task contract and honor it first instead of silently substituting a different path just because it could also answer the question.",
    "Treat historical summaries and prior-turn tool results as background only; any claim about the current turn's accepted/running/completed/cancelled/delivered state must be grounded in actions or tool results that actually happened in this turn.",
)


def get_capability_declarations() -> dict[str, CapabilityDeclaration]:
    return {
        "automation": CapabilityDeclaration(
            name="automation",
            summary="Manage recurring automations and inspect scheduled jobs.",
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
                "Use this for creating, listing, inspecting, updating, pausing, resuming, or deleting scheduled tasks."
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
                "Can answer GitHub repository questions and other MCP-backed live facts exposed by configured servers.",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "detail", "call"]},
                    "server_id": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "query": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["action"],
                "additionalProperties": True,
            },
        ),
        "runtime": CapabilityDeclaration(
            name="runtime",
            summary="Inspect the current runtime context status in a user-readable way.",
            actions=["context_status"],
            usage_rules=[
                "Use this when the user asks about current context window usage, compression status, or conversation context health.",
                "Returns live runtime context data for the current session.",
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["context_status"]},
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
        "skill": CapabilityDeclaration(
            name="skill",
            summary="Load one skill body on demand when the visible summary is not enough.",
            actions=["load"],
            usage_rules=[
                "Read visible skill summaries first and load only the one that clearly applies."
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
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "timezone": {"type": "string"},
                    "tz": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        "spawn_subagent": CapabilityDeclaration(
            name="spawn_subagent",
            summary="Delegate a background task to an isolated child session and return an immediate acceptance reply.",
            actions=[],
            usage_rules=[
                "Use this when the user explicitly asks for a subagent/background/async child task, or when isolating tool-heavy side work from the main thread would keep the primary conversation cleaner.",
                "When the user explicitly asks to 开启子代理/后台执行, prefer this instead of directly using main-thread tools to finish the task yourself.",
                "Infer a concise task brief, label, context_mode, and minimal sufficient tool profile; do not ask the user for internal field names.",
                "Only use acceptance/waiting wording such as 已受理, 后台执行中, or 请等待子 agent 返回结果 after this turn actually called spawn_subagent and received an accepted/queued/running result; do not infer current task state from historical summaries."
            ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "label": {"type": "string"},
                    "tool_profile": {"type": "string"},
                    "context_mode": {"type": "string"},
                    "notify_on_finish": {"type": "boolean"},
                    "agent_id": {"type": "string"},
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
        lines.append(
            f"- {name}: {declaration.summary}{action_text}{usage_text}".strip()
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
    return " ".join(segment.strip() for segment in segments if segment.strip())


def get_parameters_schema(declaration: CapabilityDeclaration) -> dict[str, object]:
    return dict(declaration.parameters_schema)
