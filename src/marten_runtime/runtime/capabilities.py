from __future__ import annotations

from pydantic import BaseModel, Field


class CapabilityDeclaration(BaseModel):
    name: str
    summary: str
    actions: list[str] = Field(default_factory=list)
    usage_rules: list[str] = Field(default_factory=list)


def get_capability_declarations() -> dict[str, CapabilityDeclaration]:
    return {
        "automation": CapabilityDeclaration(
            name="automation",
            summary="Manage recurring automations and inspect scheduled jobs.",
            actions=["register", "list", "detail", "update", "delete", "pause", "resume"],
            usage_rules=["Use this when the user wants to create or manage scheduled tasks."],
        ),
        "mcp": CapabilityDeclaration(
            name="mcp",
            summary="Inspect MCP server capabilities progressively and call one tool when needed.",
            actions=["list", "detail", "call"],
            usage_rules=["Inspect servers first, then detail, then call one tool with explicit arguments."],
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
            usage_rules=["Use this only for self-improve evidence and candidate management."],
        ),
        "skill": CapabilityDeclaration(
            name="skill",
            summary="Load one skill body on demand when the visible summary is not enough.",
            actions=["load"],
            usage_rules=["Read visible skill summaries first and load only the one that clearly applies."],
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
                "For queries like 现在几点 / 当前时间 / what time is it, 先调用 `time`，不要直接猜当前时间，也不要依赖上下文或记忆回答。",
            ],
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
    for name, declaration in declarations.items():
        action_text = f" Actions: {', '.join(declaration.actions)}." if declaration.actions else ""
        usage_text = f" Rules: {' '.join(declaration.usage_rules)}" if declaration.usage_rules else ""
        lines.append(f"- {name}: {declaration.summary}{action_text}{usage_text}".strip())
    if mcp_catalog_text:
        lines.append("")
        lines.append(mcp_catalog_text)
    return "\n".join(lines)


def render_tool_description(declaration: CapabilityDeclaration) -> str:
    if declaration.name == "automation":
        return (
            "Manage recurring automations with action=register/list/detail/update/delete/pause/resume. "
            "Use this when the user wants to create or manage scheduled tasks. "
            "For requests like 当前有哪些定时任务 / 列出定时任务 / 查看任务列表, call the family tool with action=list. "
            "Stay inside the automation family contract and 不要调用不存在的子工具名."
        )
    if declaration.name == "mcp":
        return (
            "Inspect available MCP servers and tools, then call one tool by server_id and tool_name when "
            "realtime external capabilities are needed."
        )
    if declaration.name == "self_improve":
        return (
            "Inspect self-improve candidates, evidence, active lessons, and internal candidate persistence "
            "with action=list_candidates/candidate_detail/delete_candidate/summary/list_evidence/"
            "list_system_lessons/save_candidate."
        )
    if declaration.name == "skill":
        return (
            "Load one skill body by skill_id when the summary is not enough and more detailed instructions "
            "are needed before continuing."
        )
    if declaration.name == "time":
        return (
            "Read the live current time for a requested timezone or UTC offset. For questions like 现在几点, "
            "当前时间, or what time is it, 先调用这个工具，不要直接猜当前时间，也不要依赖上下文或记忆回答。"
        )
    return declaration.summary
