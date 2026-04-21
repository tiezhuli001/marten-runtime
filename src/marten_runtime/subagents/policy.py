from __future__ import annotations

import re

from marten_runtime.session.models import SessionMessage
from marten_runtime.subagents.tool_profiles import (
    PROFILE_ORDER,
    normalize_tool_profile_name,
)

_EXPLICIT_SUBAGENT_INTENT_PATTERNS = [
    r"开启子代理",
    r"开子代理",
    r"启动子代理",
    r"子代理",
    r"子\s*agent",
    r"subagent",
    r"后台处理",
    r"后台执行",
    r"异步处理",
    r"不要污染主线程",
    r"不要污染上下文",
    r"隔离上下文",
]

_BROADER_TOOL_HINT_PATTERNS = [
    r"\bmcp\b",
    r"\bapi\b",
    r"\btool\b",
    r"调用工具",
    r"调用.*工具",
    r"外部数据",
    r"远程数据",
    r"https?://",
]


def has_explicit_subagent_intent(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in _EXPLICIT_SUBAGENT_INTENT_PATTERNS)


def task_likely_needs_broader_tool_access(task: str) -> bool:
    lowered = task.lower()
    return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in _BROADER_TOOL_HINT_PATTERNS)


def infer_default_subagent_tool_profile(
    *,
    task: str,
    latest_user_message: str | None = None,
) -> str:
    if task_likely_needs_broader_tool_access(task):
        return "standard"
    if latest_user_message and has_explicit_subagent_intent(latest_user_message):
        return "standard"
    return "restricted"


def resolve_requested_subagent_tool_profile(
    *,
    task: str,
    latest_user_message: str | None = None,
    requested_tool_profile: str | None = None,
) -> str:
    normalized_requested = (
        normalize_tool_profile_name(requested_tool_profile) or "restricted"
    )
    inferred_minimum = infer_default_subagent_tool_profile(
        task=task,
        latest_user_message=latest_user_message,
    )
    if normalized_requested not in PROFILE_ORDER:
        return normalized_requested
    if PROFILE_ORDER.index(normalized_requested) < PROFILE_ORDER.index(inferred_minimum):
        return inferred_minimum
    return normalized_requested


def latest_user_message_text(session_store, session_id: str) -> str | None:  # noqa: ANN001
    if not session_id:
        return None
    try:
        session = session_store.get(session_id)
    except KeyError:
        return None
    for item in reversed(session.history):
        if isinstance(item, SessionMessage) and item.role == "user":
            text = item.content.strip()
            if text:
                return text
    return None
