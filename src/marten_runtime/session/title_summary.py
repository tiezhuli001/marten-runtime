from __future__ import annotations

import re

from marten_runtime.runtime.llm_client import LLMRequest, ToolSnapshot


def build_session_title_summary(
    *,
    llm_client,
    session_id: str,
    trace_id: str,
    app_id: str,
    agent_id: str,
    user_message: str,
) -> tuple[str, str]:
    cleaned_message = _clean_summary_source(user_message)
    fallback_title, fallback_preview = _fallback_summary(cleaned_message)
    try:
        reply = llm_client.complete(
            LLMRequest(
                session_id=session_id,
                trace_id=trace_id,
                message=(
                    "Generate a short session topic title and one-sentence preview.\n"
                    "Return exactly two lines:\n"
                    "Title: <short title>\n"
                    "Preview: <one sentence>\n\n"
                    f"User message: {cleaned_message}"
                ),
                summary_input_text=cleaned_message,
                agent_id=agent_id,
                app_id=app_id,
                available_tools=[],
                tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_empty"),
                request_kind="session_summary",
            )
        )
    except Exception:
        return fallback_title, fallback_preview
    text = (reply.final_text or "").strip()
    if not text:
        return fallback_title, fallback_preview
    title_match = re.search(r"(?im)^title:\s*(.+)$", text)
    preview_match = re.search(r"(?im)^preview:\s*(.+)$", text)
    title = _normalize(title_match.group(1) if title_match else fallback_title)
    preview = _normalize(preview_match.group(1) if preview_match else fallback_preview)
    return title or fallback_title, preview or fallback_preview


def _fallback_summary(user_message: str) -> tuple[str, str]:
    normalized = _normalize(user_message)
    if not normalized:
        return "新会话", "用户开启了一个新会话。"
    title = _truncate(normalized, 36)
    preview = _truncate(normalized, 100)
    if preview[-1:] not in {"。", "！", "？", ".", "!", "?"}:
        preview = f"{preview}。"
    return title, preview


def _normalize(value: str) -> str:
    return " ".join(str(value).split()).strip()


def _clean_summary_source(user_message: str) -> str:
    cleaned = str(user_message or "")
    cleaned = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", cleaned)
    cleaned = re.sub(r"(?:^|\s)@(?:_user_\d+|[^\s]+)", " ", cleaned)
    cleaned = _normalize(cleaned)
    return cleaned


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"
