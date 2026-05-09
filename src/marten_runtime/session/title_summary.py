from __future__ import annotations

import re

from marten_runtime.runtime.llm_client import LLMRequest, ToolSnapshot


def default_session_catalog_metadata() -> tuple[str, str]:
    return _default_summary()


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
    fallback_title, fallback_preview = _default_summary()
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
    if session_catalog_metadata_needs_refresh(title=title, preview=preview):
        return fallback_title, fallback_preview
    return title or fallback_title, preview or fallback_preview
def session_catalog_metadata_needs_refresh(*, title: str, preview: str) -> bool:
    normalized_title = _normalize(title)
    normalized_preview = _normalize(preview)
    fallback_title, fallback_preview = default_session_catalog_metadata()
    return (
        not normalized_title
        or not normalized_preview
        or (
            normalized_title == fallback_title
            and normalized_preview == fallback_preview
        )
        or _is_title_template_placeholder(normalized_title)
        or _is_preview_template_placeholder(normalized_preview)
    )


def _default_summary() -> tuple[str, str]:
    return "新会话", "用户开启了一个新会话。"


def _normalize(value: str) -> str:
    return " ".join(str(value).split()).strip()


def _clean_summary_source(user_message: str) -> str:
    cleaned = str(user_message or "")
    cleaned = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", cleaned)
    cleaned = re.sub(r"(?:^|\s)@(?:_user_\d+|[^\s]+)", " ", cleaned)
    return _normalize(cleaned)


def _is_title_template_placeholder(value: str) -> bool:
    return _normalize(value).lower() == "<short title>"


def _is_preview_template_placeholder(value: str) -> bool:
    return _normalize(value).lower() == "<one sentence>"
