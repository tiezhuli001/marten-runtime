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

if TYPE_CHECKING:
    from marten_runtime.runtime.llm_client import ToolExchange, ToolFollowupFragment


def _llm_requested_terminal_render(tool_payload: dict | None) -> bool:
    if not isinstance(tool_payload, dict):
        return False
    return bool(tool_payload.get("finalize_response") is True)


def maybe_render_tool_followup_text(
    tool_name: str,
    tool_result: object,
    *,
    tool_payload: dict | None = None,
    tool_history: list["ToolExchange"] | None = None,
    message: str = "",
) -> str:
    del message
    tool_round_trip_count = len(tool_history or [])
    if tool_name == "time":
        if not _llm_requested_terminal_render(tool_payload):
            return ""
        return render_direct_tool_text(tool_name, tool_result, tool_payload=tool_payload)
    if tool_name == "runtime":
        if tool_round_trip_count > 1:
            return ""
        return render_direct_tool_text(tool_name, tool_result, tool_payload=tool_payload)
    if tool_name == "automation":
        return render_direct_tool_text(tool_name, tool_result, tool_payload=tool_payload)
    if tool_name == "mcp":
        if str((tool_payload or {}).get("action") or "").strip() == "list":
            return ""
        if not _llm_requested_terminal_render(tool_payload):
            return ""
        return render_direct_tool_text(tool_name, tool_result, tool_payload=tool_payload)
    if tool_name == "session":
        if not _llm_requested_terminal_render(tool_payload):
            return ""
        return render_direct_tool_text(tool_name, tool_result, tool_payload=tool_payload)
    if tool_name == "spawn_subagent":
        if not _llm_requested_terminal_render(tool_payload):
            return ""
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
        if (
            action == "show"
            and not str((tool_payload or {}).get("session_id") or "").strip()
            and bool(session.get("is_current"))
        ):
            current_summary = _render_current_session_summary(session)
            if current_summary:
                return current_summary
        if isinstance(tool_result.get("transition"), dict):
            session = dict(session)
            session["transition"] = dict(tool_result["transition"])
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
    current_session = tool_result.get("current_session")
    if not isinstance(current_session, dict):
        current_session = next(
            (
                item
                for item in items
                if isinstance(item, dict) and bool(item.get("is_current"))
            ),
            None,
        )
    lines = [heading]
    current_summary = _render_current_session_summary(current_session)
    if current_summary:
        lines.extend(["", current_summary])
    lines.extend(
        [
            "",
            "| 序号 | 标题 | 状态 | 消息数 | 创建时间 | session_id |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for index, item in enumerate(items[:5], start=1):
        if not isinstance(item, dict):
            continue
        title = _sanitize_session_catalog_text(
            str(item.get("session_title") or item.get("session_preview") or item.get("session_id") or "").strip()
        )
        if item.get("is_current"):
            title = f"当前 · {title or str(item.get('session_id') or '').strip()}"
        session_id = str(item.get("session_id") or "").strip()
        state = str(item.get("state") or "").strip() or "unknown"
        message_count = int(item.get("message_count") or 0)
        created_at = _format_catalog_timestamp(str(item.get("created_at") or "").strip())
        lines.append(
            "| {index} | {title} | {state} | {message_count} | {created_at} | {session_id} |".format(
                index=index,
                title=_session_table_cell(title or session_id or "未命名会话"),
                state=_session_table_cell(state),
                message_count=message_count,
                created_at=_session_table_cell(created_at or "-"),
                session_id=_session_table_cell(session_id or "-"),
            )
        )
    if count > 5:
        lines.append("")
        lines.append(f"其余 {count - 5} 个会话请用 session.show 查看。")
    return "\n".join(line for line in lines if line is not None).strip()


def _session_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _render_current_session_summary(session: dict[str, object] | None) -> str:
    if not isinstance(session, dict):
        return ""
    session_id = str(session.get("session_id") or "").strip() or "-"
    title = _sanitize_session_catalog_text(
        str(session.get("session_title") or session.get("session_preview") or session_id).strip()
    )
    state = str(session.get("state") or "").strip() or "unknown"
    message_count = int(session.get("message_count") or 0)
    return (
        f"当前会话：{title or session_id}（{state}，{message_count} 条，session_id：{session_id}）"
    )


def _render_session_record_text(action: str, session: dict[str, object]) -> str:
    session_id = str(session.get("session_id") or "").strip()
    title = _sanitize_session_catalog_text(
        str(session.get("session_title") or session.get("session_preview") or session_id).strip()
    )
    preview = _sanitize_session_catalog_text(str(session.get("session_preview") or "").strip())
    state = str(session.get("state") or "").strip() or "unknown"
    message_count = int(session.get("message_count") or 0)
    created_at = _format_catalog_timestamp(str(session.get("created_at") or "").strip())
    transition = session.get("transition") if isinstance(session.get("transition"), dict) else None
    if action == "new":
        heading = "已切换到新会话"
    elif action == "resume":
        same_session_noop = False
        if transition is not None:
            same_session_noop = (
                str(transition.get("mode") or "").strip() == "noop_same_session"
                or transition.get("binding_changed") is False
            )
        heading = (
            f"当前已在会话 `{session_id}`"
            if same_session_noop and session_id
            else (f"已切换到会话 `{session_id}`" if session_id else "已切换到已有会话")
        )
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


def render_recovery_fragment(fragment: "ToolFollowupFragment" | None) -> str:
    if fragment is None:
        return ""
    if getattr(fragment, "safe_for_fallback", True) is not True:
        return ""
    return _normalize_direct_rendered_text(getattr(fragment, "text", ""))


def render_recovery_fragments_text(fragments: list["ToolFollowupFragment"]) -> str:
    parts = [part for part in (render_recovery_fragment(item) for item in fragments) if part]
    if not parts:
        return ""
    return "\n\n".join(parts)


def is_partial_fragment_aggregation(
    fragments: list["ToolFollowupFragment"],
    text: str,
) -> bool:
    parts = [part for part in (render_recovery_fragment(item) for item in fragments) if part]
    if len(parts) < 2:
        return False
    normalized_text = _normalize_direct_rendered_text(text)
    if not normalized_text:
        return False
    full_text = _normalize_direct_rendered_text("\n\n".join(parts))
    if normalized_text == full_text:
        return False
    full_mask = (1 << len(parts)) - 1
    for mask in range(1, full_mask):
        selected = [
            parts[index]
            for index in range(len(parts))
            if mask & (1 << index)
        ]
        candidate = _normalize_direct_rendered_text("\n\n".join(selected))
        if candidate == normalized_text:
            return True
    return False


def _normalize_direct_rendered_text(text: str) -> str:
    return "\n".join(line.strip() for line in str(text).strip().splitlines() if line.strip())


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
