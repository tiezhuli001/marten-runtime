from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

# Deterministic last-mile rendering only. This module may turn already-available
# tool results into final user text for narrow recovery/stability cases, but it
# must not participate in query understanding, tool selection, or route policy.
# Keep this surface intentionally small; add new direct renders only with
# explicit evidence that the result is already sufficient and the behavior is
# worth hardening outside the model.

from marten_runtime.tools.builtins.automation_tool import render_automation_tool_text
from marten_runtime.tools.builtins.time_tool import (
    detect_local_timezone_label,
    humanize_timezone_label,
    render_time_tool_text,
    resolve_timezone,
)
from marten_runtime.tools.builtins.runtime_tool import render_runtime_context_status_text
from marten_runtime.runtime.query_hardening import is_explicit_multi_step_tool_request

if TYPE_CHECKING:
    from marten_runtime.runtime.llm_client import ToolExchange


def maybe_render_tool_followup_text(
    tool_name: str,
    tool_result: object,
    *,
    tool_payload: dict | None = None,
    tool_history: list["ToolExchange"] | None = None,
    message: str = "",
) -> str:
    history_text = render_direct_tool_history_text(tool_history or [])
    if history_text:
        return history_text
    if tool_name == "runtime":
        if is_explicit_multi_step_tool_request(message):
            return ""
        return render_direct_tool_text(tool_name, tool_result, tool_payload=tool_payload)
    if tool_name == "automation":
        return render_direct_tool_text(tool_name, tool_result, tool_payload=tool_payload)
    if tool_name == "mcp":
        if str((tool_payload or {}).get("action") or "").strip() == "list":
            return ""
        return render_direct_tool_text(tool_name, tool_result, tool_payload=tool_payload)
    if tool_name == "session":
        if is_explicit_multi_step_tool_request(message):
            return ""
        return render_direct_tool_text(tool_name, tool_result, tool_payload=tool_payload)
    if tool_name == "spawn_subagent":
        return render_direct_tool_text(tool_name, tool_result, tool_payload=tool_payload)
    return ""


def render_direct_tool_text(tool_name: str, tool_result: object, *, tool_payload: dict | None = None) -> str:
    if not isinstance(tool_result, dict):
        return ""
    if tool_name == "runtime":
        return render_runtime_context_status_text(tool_result)
    if tool_name == "time":
        return render_time_tool_text(tool_result)
    if tool_name == "automation":
        return render_automation_tool_text(tool_result)
    if tool_name == "mcp":
        return render_direct_mcp_text(tool_result, tool_payload=tool_payload)
    if tool_name == "session":
        return render_direct_session_text(tool_result, tool_payload=tool_payload)
    if tool_name == "spawn_subagent":
        return render_spawn_subagent_text(tool_result, tool_payload=tool_payload)
    return ""


def render_direct_mcp_text(tool_result: dict[str, object], *, tool_payload: dict | None = None) -> str:
    payload = dict(tool_payload or {})
    server_id = str(tool_result.get("server_id") or payload.get("server_id") or "").strip()
    tool_name = str(tool_result.get("tool_name") or payload.get("tool_name") or "").strip()
    if server_id in {"github_trending", "github-trending"} and tool_name == "trending_repositories":
        return render_github_trending_text(tool_result)
    if server_id == "github" and tool_name == "list_commits":
        return render_github_list_commits_text(tool_result, tool_payload=payload)
    if str(tool_result.get("action") or payload.get("action") or "").strip() == "list":
        return render_mcp_list_text(tool_result)
    return ""


def render_spawn_subagent_text(
    tool_result: dict[str, object],
    *,
    tool_payload: dict[str, object] | None = None,
) -> str:
    if tool_result.get("ok") is False:
        return ""
    if str(tool_result.get("status") or "").strip() != "accepted":
        return ""
    notify_on_finish = bool((tool_payload or {}).get("notify_on_finish", True))
    queue_state = str(tool_result.get("queue_state") or "").strip()
    if queue_state == "queued":
        if notify_on_finish:
            return "已受理，子 agent 已进入队列，开始后会通知你结果。"
        return "已受理，子 agent 已进入队列。"
    if notify_on_finish:
        return "已受理，子 agent 正在后台执行，完成后会通知你结果。"
    return "已受理，子 agent 正在后台执行。"


def render_direct_session_text(
    tool_result: dict[str, object],
    *,
    tool_payload: dict[str, object] | None = None,
) -> str:
    action = str(tool_result.get("action") or (tool_payload or {}).get("action") or "").strip()
    if action in {"new", "resume", "show"}:
        session = tool_result.get("session")
        if not isinstance(session, dict):
            return ""
        return _render_session_record_text(action, session)
    if action != "list":
        return ""
    items = tool_result.get("items")
    if not isinstance(items, list):
        return ""
    count = int(tool_result.get("count") or len(items))
    heading = f"当前有 {count} 个可见会话。"
    if not items:
        return heading
    lines = [heading]
    for index, item in enumerate(items[:5], start=1):
        if not isinstance(item, dict):
            continue
        title = _sanitize_session_catalog_text(
            str(item.get("session_title") or item.get("session_preview") or item.get("session_id") or "").strip()
        )
        preview = _sanitize_session_catalog_text(str(item.get("session_preview") or "").strip())
        session_id = str(item.get("session_id") or "").strip()
        state = str(item.get("state") or "").strip() or "unknown"
        message_count = int(item.get("message_count") or 0)
        created_at = _format_catalog_timestamp(str(item.get("created_at") or "").strip())
        lines.append(f"{index}. 标题：{title or session_id or '未命名会话'}")
        if preview and preview != title:
            lines.append(f"详情：{preview}")
        lines.append(f"状态：{state}")
        lines.append(f"消息数：{message_count}")
        if created_at:
            lines.append(f"创建时间：{created_at}")
        if session_id:
            lines.append(f"session_id：{session_id}")
        lines.append("")
    if count > 5:
        lines.append(f"其余 {count - 5} 个会话请用 session.show 查看。")
    return "\n".join(line for line in lines if line is not None).strip()


def _render_session_record_text(action: str, session: dict[str, object]) -> str:
    session_id = str(session.get("session_id") or "").strip()
    title = _sanitize_session_catalog_text(
        str(session.get("session_title") or session.get("session_preview") or session_id).strip()
    )
    preview = _sanitize_session_catalog_text(str(session.get("session_preview") or "").strip())
    state = str(session.get("state") or "").strip() or "unknown"
    message_count = int(session.get("message_count") or 0)
    created_at = _format_catalog_timestamp(str(session.get("created_at") or "").strip())
    if action == "new":
        heading = "已切换到新会话"
    elif action == "resume":
        heading = f"已切换到会话 `{session_id}`" if session_id else "已切换到已有会话"
    else:
        heading = f"会话详情 `{session_id}`" if session_id else "会话详情"
    lines = [heading]
    if title and action != "new":
        lines.append(f"- 标题：{title}")
    if preview and preview != title:
        lines.append(f"- 详情：{preview}")
    lines.append(f"- 消息数：{message_count}")
    lines.append(f"- 状态：{state}")
    if created_at:
        lines.append(f"- 创建时间：{created_at}")
    if session_id and action == "show":
        lines.append(f"- session_id：{session_id}")
    return "\n".join(lines)


def render_mcp_list_text(tool_result: dict[str, object]) -> str:
    raw_servers = tool_result.get("servers")
    if not isinstance(raw_servers, list):
        return ""
    servers = _dedupe_mcp_servers(raw_servers)
    count = len(servers)
    heading = f"当前可用 MCP 服务共 {count} 个。"
    if not servers:
        return heading
    lines = [heading]
    for index, item in enumerate(servers[:8], start=1):
        if not isinstance(item, dict):
            continue
        server_id = str(item.get("server_id") or "").strip()
        tool_count = int(item.get("tool_count") or 0)
        state = str(item.get("state") or "").strip()
        state_text = f"，状态 {state}" if state else ""
        if server_id:
            lines.append(f"- {index}. {server_id}（{tool_count} 个工具{state_text}）")
    if count > 8:
        lines.append(f"- 其余 {count - 8} 个服务已省略。")
    return "\n".join(lines)


def _dedupe_mcp_servers(servers: list[object]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in servers:
        if not isinstance(item, dict):
            continue
        server_id = str(item.get("server_id") or "").strip()
        if not server_id:
            continue
        canonical = _canonical_mcp_server_id(server_id)
        if canonical in seen:
            continue
        seen.add(canonical)
        deduped.append(item)
    return deduped


def _canonical_mcp_server_id(server_id: str) -> str:
    return server_id.strip().lower().replace("-", "_")


def render_direct_tool_history_text(history: list["ToolExchange"]) -> str:
    if len(history) != 3:
        return ""
    first, second, third = history
    if [first.tool_name, second.tool_name, third.tool_name] != ["time", "runtime", "mcp"]:
        return ""
    if not _is_successful_tool_result(first.tool_result):
        return ""
    if not _is_successful_tool_result(second.tool_result):
        return ""
    if not _is_successful_tool_result(third.tool_result):
        return ""
    if str(second.tool_result.get("action") or second.tool_payload.get("action") or "").strip() != "context_status":
        return ""
    if str(third.tool_result.get("action") or third.tool_payload.get("action") or "").strip() != "list":
        return ""
    time_text = render_direct_tool_text("time", first.tool_result, tool_payload=first.tool_payload)
    runtime_text = render_runtime_context_status_text(second.tool_result)
    mcp_text = render_direct_tool_text("mcp", third.tool_result, tool_payload=third.tool_payload)
    round_trip_text = "本次请求共发生 3 次模型请求和 3 次工具调用，属于多次模型/工具往返。"
    parts = [item for item in [time_text, runtime_text, mcp_text, round_trip_text] if item]
    return "\n\n".join(parts)


def _is_successful_tool_result(tool_result: object) -> bool:
    if not isinstance(tool_result, dict):
        return False
    return tool_result.get("ok") is not False and tool_result.get("is_error") is not True


def _sanitize_session_catalog_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?:^|\s)@_user_\d+\b", " ", text)
    text = _strip_markdown_links(text)
    text = " ".join(text.split())
    return text.strip()


def _strip_markdown_links(text: str) -> str:
    return re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)


def _format_catalog_timestamp(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(resolve_timezone({"timezone": detect_local_timezone_label()})).strftime("%Y-%m-%d %H:%M:%S")


def render_github_trending_text(tool_result: dict[str, object]) -> str:
    if tool_result.get("ok") is False or tool_result.get("is_error") is True:
        return ""
    parsed = parse_mcp_result_payload(tool_result)
    if not isinstance(parsed, dict):
        return ""
    items = parsed.get("items")
    if not isinstance(items, list):
        return ""
    since = str(parsed.get("since") or "daily").strip().lower()
    fetched_at = str(parsed.get("fetched_at_display") or "").strip()
    period_label = {
        "daily": "今日",
        "weekly": "本周",
        "monthly": "本月",
    }.get(since, "当前")
    heading = f"GitHub {period_label}热榜，按官方 Trending 排序"
    if fetched_at:
        heading += f"（{fetched_at} 抓取，共 {len(items)} 个项目）"
    bullets: list[str] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        rank = int(item.get("rank") or index)
        full_name = str(item.get("full_name") or "").strip()
        if not full_name:
            continue
        detail_bits: list[str] = []
        language = str(item.get("language") or "").strip()
        stars_period = item.get("stars_period")
        if language:
            detail_bits.append(language)
        if isinstance(stars_period, int) and stars_period > 0:
            detail_bits.append(f"+{stars_period}★")
        detail_text = f"（{'，'.join(detail_bits)}）" if detail_bits else ""
        bullets.append(f"- {rank}. {full_name}{detail_text}")
    if not bullets:
        bullets.append("- 暂无项目。")
    return "\n".join([heading, *bullets])


def render_github_list_commits_text(
    tool_result: dict[str, object],
    *,
    tool_payload: dict[str, object] | None = None,
) -> str:
    arguments = tool_result.get("arguments")
    if not isinstance(arguments, dict):
        payload_arguments = (tool_payload or {}).get("arguments")
        arguments = payload_arguments if isinstance(payload_arguments, dict) else (tool_payload or {})
    repo = ""
    if isinstance(arguments, dict):
        owner = str(arguments.get("owner") or "").strip()
        name = str(arguments.get("repo") or "").strip()
        if owner and name:
            repo = f"{owner}/{name}"
    if tool_result.get("ok") is False or tool_result.get("is_error") is True:
        result_text = str(tool_result.get("result_text") or "").strip()
        lowered = result_text.lower()
        if "404 not found" in lowered:
            if repo:
                return f"该仓库 `{repo}` 不存在（404 Not Found），无法获取提交信息。"
            return "该仓库不存在（404 Not Found），无法获取提交信息。"
        return ""
    parsed = parse_mcp_result_payload(tool_result)
    if not isinstance(parsed, list) or not parsed:
        return ""
    first = parsed[0]
    if not isinstance(first, dict):
        return ""
    commit = first.get("commit")
    if not isinstance(commit, dict):
        return ""
    author = commit.get("author")
    if not isinstance(author, dict):
        return ""
    commit_at = str(author.get("date") or "").strip()
    message = str(commit.get("message") or "").strip()
    message = " ".join(message.split())
    if not commit_at:
        return ""
    displayed_at, timezone_suffix = _format_commit_timestamp_for_local_display(commit_at)
    prefix = f"{repo} 最近一次提交是" if repo else "最近一次提交是"
    if message:
        return f"{prefix} **{displayed_at}**{timezone_suffix}，commit 信息为 `{message}`。"
    return f"{prefix} **{displayed_at}**{timezone_suffix}。"


def _format_commit_timestamp_for_local_display(commit_at: str) -> tuple[str, str]:
    try:
        parsed = datetime.fromisoformat(commit_at.replace("Z", "+00:00"))
    except ValueError:
        return commit_at.replace("T", " ").replace("Z", " UTC"), ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_label = detect_local_timezone_label()
    local_dt = parsed.astimezone(resolve_timezone({"timezone": local_label}))
    label = humanize_timezone_label(local_label)
    return local_dt.strftime("%Y-%m-%d %H:%M:%S"), f"（{label}）"


def parse_mcp_result_payload(tool_result: dict[str, object]) -> dict[str, object] | list[object] | None:
    result_text = tool_result.get("result_text")
    if isinstance(result_text, str):
        try:
            parsed = json.loads(result_text)
        except Exception:
            parsed = None
        if isinstance(parsed, (dict, list)):
            return parsed
    content = tool_result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                parsed = json.loads(text)
            except Exception:
                continue
            if isinstance(parsed, (dict, list)):
                return parsed
    return None
