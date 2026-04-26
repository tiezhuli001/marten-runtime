from __future__ import annotations

PROFILE_ALLOWED_TOOL_SELECTORS = {
    "restricted": {"runtime", "skill", "time"},
    "standard": {"automation", "mcp", "runtime", "skill", "time"},
    "elevated": {"automation", "mcp", "runtime", "skill", "time"},
}

FORBIDDEN_CHILD_TOOLS = {"spawn_subagent", "cancel_subagent"}
PROFILE_ORDER = ["restricted", "standard", "elevated"]
PROFILE_ALIASES = {
    "default": "standard",
    "mcp": "standard",
}


def normalize_tool_profile_name(requested_profile: str | None) -> str:
    normalized = (requested_profile or "").strip().lower()
    if normalized.startswith("mcp:"):
        return "standard"
    return PROFILE_ALIASES.get(normalized, normalized)


def resolve_effective_tool_profile(
    *,
    requested_profile: str,
    parent_allowed_tools: list[str],
) -> str:
    requested_profile = normalize_tool_profile_name(requested_profile)
    if requested_profile not in PROFILE_ALLOWED_TOOL_SELECTORS:
        raise ValueError(f"unknown tool profile: {requested_profile}")
    parent_rank = 0
    for idx, profile in enumerate(PROFILE_ORDER):
        selectors = set(PROFILE_ALLOWED_TOOL_SELECTORS[profile]) - FORBIDDEN_CHILD_TOOLS
        if all(_selector_allows_tool(parent_allowed_tools, item) for item in selectors):
            parent_rank = idx
    requested_rank = PROFILE_ORDER.index(requested_profile)
    return PROFILE_ORDER[min(requested_rank, parent_rank)]


def resolve_child_allowed_tools(
    *,
    requested_profile: str,
    parent_allowed_tools: list[str],
) -> list[str]:
    requested_profile = normalize_tool_profile_name(requested_profile)
    if requested_profile not in PROFILE_ALLOWED_TOOL_SELECTORS:
        raise ValueError(f"unknown tool profile: {requested_profile}")
    requested = PROFILE_ALLOWED_TOOL_SELECTORS[requested_profile]
    effective = sorted(
        item
        for item in requested
        if item not in FORBIDDEN_CHILD_TOOLS
        and _selector_allows_tool(parent_allowed_tools, item)
    )
    return effective


def _selector_allows_tool(parent_allowed_tools: list[str], tool_name: str) -> bool:
    selectors = set(parent_allowed_tools)
    if "*" in selectors or tool_name in selectors:
        return True
    if "builtin:*" in selectors:
        return True
    if tool_name == "mcp" and any(
        selector == "mcp:*" or selector.startswith("mcp:")
        for selector in selectors
    ):
        return True
    return False
