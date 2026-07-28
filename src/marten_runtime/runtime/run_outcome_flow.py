from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

from marten_runtime.channels.feishu.rendering import (
    FeishuCardSection,
    normalize_feishu_visible_text,
    parse_feishu_card_protocol,
    recover_feishu_card_protocol,
)
from marten_runtime.runtime.bazi_output_contract import (
    missing_bazi_sections,
    normalize_bazi_timing_contract_text,
    normalize_verification_event_text,
    section_text,
)
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import ToolExchange
from marten_runtime.runtime.observation_policy import is_sensitive_bazi, project_text
from marten_runtime.runtime.provider_retry import ProviderTransportError
from marten_runtime.runtime.tool_episode_summary_prompt import ToolEpisodeSummaryDraft
from marten_runtime.runtime.timing import elapsed_ms
from marten_runtime.runtime.tool_outcome_flow import (
    build_combined_tool_episode_summary,
    build_fallback_tool_episode_summary,
)
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.tools.registry import ToolSnapshot

logger = logging.getLogger(__name__)

_BAZI_SECTION_ORDER = (
    "命盘",
    "原局格局喜用",
    "大运",
    "健康注意",
    "学历",
    "事业",
    "婚姻",
    "六亲",
    "财富等级",
    "过三关",
)
_BAZI_ALL_SECTION_ORDER = (*_BAZI_SECTION_ORDER, "参考依据")
_BAZI_SECTION_ALIASES = {
    "命盘（排盘事实）": "命盘",
    "排盘事实": "命盘",
    "原局": "原局格局喜用",
    "原局核心": "原局格局喜用",
    "子平格局法": "原局格局喜用",
    "盲派": "原局格局喜用",
    "盲派观察": "原局格局喜用",
    "事业财运": "事业",
    "家庭": "六亲",
    "父母": "六亲",
    "子女": "六亲",
    "财富": "财富等级",
}
_BAZI_MENU_LINES = {
    "哪几年适合结婚",
    "哪步运财运更强",
    "是否适合创业或换城市",
}
def tool_rejection_text(error_code: str) -> str:
    if error_code == "TOOL_NOT_ALLOWED":
        return "当前操作未被允许，请换个说法或缩小范围。"
    if error_code == "TOOL_NOT_FOUND":
        return "当前所需工具不可用，请稍后重试。"
    return error_code.lower()


def provider_failure_text(error_code: str) -> str:
    if error_code in {"PROVIDER_UPSTREAM_UNAVAILABLE", "PROVIDER_RATE_LIMITED"}:
        return "当前模型服务繁忙，请稍后重试。"
    if error_code == "PROVIDER_AUTH_ERROR":
        return "当前模型配置不可用，请联系管理员检查服务配置。"
    return "暂时没有生成可见回复，请重试。"


def is_provider_failure(exc: Exception) -> bool:
    if isinstance(exc, (ProviderTransportError, TimeoutError, OSError)):
        return True
    return str(exc).startswith("provider_")


def _invoke_post_commit_callback_safely(
    post_commit_callback,
    *,
    agent_id: str,
) -> None:
    if post_commit_callback is None:
        return
    try:
        post_commit_callback(agent_id=agent_id)
    except Exception:
        logger.exception("post-commit self-improve callback failed", extra={"agent_id": agent_id})

def finish_run_success(
    *,
    events: list[OutboundEvent],
    session_id: str,
    run_id: str,
    trace_id: str,
    run_started_at: float,
    llm_request_count: int,
    message: str,
    agent_id: str,
    final_text: str,
    tool_history: list[ToolExchange],
    tool_snapshot: ToolSnapshot,
    history: InMemoryRunHistory,
    self_improve_recorder: SelfImproveRecorder | None,
    append_post_turn_summary_callback=None,
    combined_summary_draft: ToolEpisodeSummaryDraft | None = None,
    post_commit_callback=None,
    channel_id: str | None = None,
) -> list[OutboundEvent]:
    if agent_id == "bazi":
        final_text = _ensure_bazi_citation_footer(
            final_text,
            tool_history,
            channel_id=channel_id,
        )
    events.append(
        OutboundEvent(
            session_id=session_id,
            run_id=run_id,
            event_id=f"evt_{uuid4().hex[:8]}",
            event_type="final",
            sequence=2,
            trace_id=trace_id,
            payload={"text": final_text},
            created_at=datetime.now(timezone.utc),
        )
    )
    sensitive_observation = is_sensitive_bazi(
        history.get(run_id).observation_policy
    )
    if not sensitive_observation:
        summary_callback = append_post_turn_summary_callback or append_post_turn_summary
        summary_callback(
            history=history,
            user_message=message,
            tool_history=tool_history,
            final_text=final_text,
            combined_summary_draft=combined_summary_draft,
            run_id=run_id,
            tool_snapshot=tool_snapshot,
        )
        trigger_review_from_success(
            history=history,
            self_improve_recorder=self_improve_recorder,
            user_message=message,
            tool_history=tool_history,
            final_text=final_text,
            combined_summary_draft=combined_summary_draft,
            run_id=run_id,
            trace_id=trace_id,
            agent_id=agent_id,
            tool_snapshot=tool_snapshot,
            channel_id=channel_id,
        )
    history.finish(run_id, delivery_status="final")
    history.set_final_text(run_id, final_text)
    history.finalize_total_timing(run_id, elapsed_ms=elapsed_ms(run_started_at))
    history.set_llm_request_count(run_id, llm_request_count)
    if not sensitive_observation:
        record_recovery(
            self_improve_recorder,
            agent_id=agent_id,
            run_id=run_id,
            trace_id=trace_id,
            message=message,
            channel_id=channel_id,
        )
    _invoke_post_commit_callback_safely(
        post_commit_callback,
        agent_id=agent_id,
    )
    return events


def _ensure_bazi_citation_footer(
    final_text: str,
    tool_history: list[ToolExchange],
    *,
    channel_id: str | None = None,
) -> str:
    final_text = _ensure_bazi_pillar_rows(final_text, tool_history)
    references = _bazi_readable_references(tool_history)
    visible_text, protocol = parse_feishu_card_protocol(final_text)
    if protocol is None:
        recovered_visible, recovered_protocol = recover_feishu_card_protocol(final_text)
        if recovered_protocol is not None:
            visible_text, protocol = recovered_visible, recovered_protocol
    if protocol is not None:
        visible_text = _sanitize_bazi_visible_analysis(visible_text)
        protocol = _sanitize_bazi_protocol(protocol)
        if references:
            protocol = protocol.model_copy(
                update={
                    "sections": [
                        *protocol.sections,
                        FeishuCardSection(title="参考依据", items=references),
                    ]
                }
            )
        block = (
            "```feishu_card\n"
            + json.dumps(protocol.model_dump(mode="json"), ensure_ascii=False)
            + "\n```"
        )
        return "\n\n".join(part for part in (visible_text.strip(), block) if part)
    durable_text = _sanitize_bazi_visible_analysis(
        _strip_internal_bazi_citations(normalize_feishu_visible_text(final_text))
    )
    if missing_bazi_sections(durable_text) and not missing_bazi_sections(final_text):
        durable_text = _sanitize_bazi_visible_analysis(
            _strip_internal_bazi_citations(_render_complete_bazi_markdown(final_text))
        )
    if channel_id != "feishu":
        durable_text = normalize_bazi_timing_contract_text(durable_text)
    normalized_text = _normalize_bazi_reference_text(durable_text)
    missing = [
        reference
        for reference in references
        if _normalize_bazi_reference_text(reference) not in normalized_text
    ]
    if missing:
        rendered = "\n".join(f"- {reference}" for reference in missing)
        durable_text = f"{durable_text.rstrip()}\n\n参考依据：\n{rendered}".strip()
    if channel_id == "feishu":
        return _build_bazi_feishu_reply(durable_text)
    return durable_text


def _render_complete_bazi_markdown(text: str) -> str:
    cleaned = "\n".join(
        line
        for line in str(text or "").splitlines()
        if line.strip() not in {"```", "```feishu_card", "feishu_card"}
    )
    sections = [section_text(cleaned, title).strip() for title in _BAZI_ALL_SECTION_ORDER]
    return "\n\n".join(section for section in sections if section).strip()


def _ensure_bazi_pillar_rows(
    final_text: str,
    tool_history: list[ToolExchange],
) -> str:
    pillars = _verified_bazi_pillars(tool_history)
    if len(pillars) != 4:
        return final_text
    stems = "　".join(item[0] for item in pillars)
    branches = "　".join(item[1] for item in pillars)
    stem_line = f"**天干：** {stems}"
    branch_line = f"**地支：** {branches}"
    text = str(final_text or "")
    has_stems = re.search(r"(?m)^\*{0,2}天干[：:]\*{0,2}\s*.*$", text)
    has_branches = re.search(r"(?m)^\*{0,2}地支[：:]\*{0,2}\s*.*$", text)
    if has_stems:
        text = re.sub(
            r"(?m)^\*{0,2}天干[：:]\*{0,2}\s*.*$",
            stem_line,
            text,
            count=1,
        )
    if has_branches:
        text = re.sub(
            r"(?m)^\*{0,2}地支[：:]\*{0,2}\s*.*$",
            branch_line,
            text,
            count=1,
        )
    missing_lines = [
        line
        for line, present in ((stem_line, has_stems), (branch_line, has_branches))
        if not present
    ]
    if not missing_lines:
        return text
    heading = re.search(r"(?m)^#{1,6}\s*[^\n]*命盘[^\n]*$", text)
    block = "\n".join(missing_lines)
    if heading:
        return f"{text[:heading.end()]}\n{block}{text[heading.end():]}"
    return f"## 命盘（排盘事实）\n{block}\n\n{text}".strip()


def _verified_bazi_pillars(tool_history: list[ToolExchange]) -> list[str]:
    for exchange in tool_history:
        if exchange.tool_name != "bazi":
            continue
        action = str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        if action == "chart":
            result = exchange.tool_result.get("result")
            if not isinstance(result, dict):
                continue
            rows = result.get("四柱")
            if not isinstance(rows, list):
                continue
            pillars = [
                str(item.get("干支") or "").strip()
                for item in rows
                if isinstance(item, dict)
            ]
            if len(pillars) == 4 and all(len(item) == 2 for item in pillars):
                return pillars
        if action == "resolve_pillars":
            fields = ("yearPillar", "monthPillar", "dayPillar", "hourPillar")
            pillars = [str(exchange.tool_payload.get(field) or "").strip() for field in fields]
            if len(pillars) == 4 and all(len(item) == 2 for item in pillars):
                return pillars
    return []


def _bazi_readable_references(tool_history: list[ToolExchange]) -> list[str]:
    references: list[str] = []
    for exchange in tool_history:
        action = str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        if exchange.tool_name != "knowledge" or action != "search":
            continue
        for item in exchange.tool_result.get("results") or []:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "").strip()
            chunk_id = str(item.get("chunk_id") or "").strip()
            if not source_id or not chunk_id:
                continue
            title = str(item.get("source_title") or "").strip()
            heading = str(item.get("heading") or "").strip()
            display_title = _book_title(title or "已审核理论资料")
            reference = f"{display_title} · {heading}" if heading else display_title
            if reference not in references:
                references.append(reference)
    return references


def _book_title(title: str) -> str:
    normalized = str(title or "").strip()
    if normalized.startswith("《") and normalized.endswith("》"):
        return normalized
    return f"《{normalized}》"


def _normalize_bazi_reference_text(text: str) -> str:
    return re.sub(r"[\s*_`]+", "", str(text or ""))


def _sanitize_bazi_protocol(protocol):  # noqa: ANN001
    reference_titles = {"参考语料", "参考资料", "参考依据", "Theory 引用"}
    sections: list[FeishuCardSection] = []
    for section in protocol.sections:
        if str(section.title or "").strip().rstrip("：:") in reference_titles:
            continue
        items = [
            cleaned
            for item in section.items
            if (
                cleaned := _sanitize_bazi_visible_analysis(
                    _strip_internal_bazi_citations(str(item or ""))
                )
            )
        ]
        if items:
            sections.append(
                FeishuCardSection(
                    title=_sanitize_bazi_visible_analysis(
                        _strip_internal_bazi_citations(str(section.title or ""))
                    ) or None,
                    items=items,
                )
            )
    sanitized = protocol.model_copy(
        update={
            "title": _sanitize_bazi_visible_analysis(
                _strip_internal_bazi_citations(str(protocol.title or ""))
            ) or None,
            "summary": _sanitize_bazi_visible_analysis(
                _strip_internal_bazi_citations(str(protocol.summary or ""))
            ) or None,
            "sections": sections,
        }
    )
    return sanitized.model_copy(
        update={"sections": _normalize_bazi_protocol_sections(sanitized.sections)}
    )


def _sanitize_bazi_visible_analysis(text: str) -> str:
    kept_lines: list[str] = []
    current_section: str | None = None
    for raw_line in str(text or "").splitlines():
        heading_candidate = re.sub(r"^[\s#*]+", "", raw_line).strip().rstrip("*")
        heading_candidate = re.sub(
            r"^(?:[一二三四五六七八九十]+|\d+)[、.．]\s*",
            "",
            heading_candidate,
        ).strip("：: ")
        heading = _canonical_bazi_section_title(heading_candidate)
        if heading is not None:
            current_section = heading
        normalized = re.sub(r"^[\s*#>\-•\d一二三四五六七八九十、.．]+", "", raw_line)
        normalized = normalized.strip().rstrip("？?").strip()
        if normalized in _BAZI_MENU_LINES:
            continue
        if current_section == "过三关":
            years = [int(item) for item in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", raw_line)]
            if years and max(years) > datetime.now().year:
                continue
        kept_lines.append(raw_line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()


def _normalize_bazi_protocol_sections(
    sections: list[FeishuCardSection],
) -> list[FeishuCardSection]:
    grouped: dict[str, list[str]] = {}
    extra: list[FeishuCardSection] = []
    for section in sections:
        section_title = _canonical_bazi_section_title(section.title)
        for item in section.items:
            split_items = _split_bazi_markdown_sections(item)
            if split_items:
                for title, content in split_items:
                    if content:
                        grouped.setdefault(title, []).append(content)
                continue
            if section_title:
                grouped.setdefault(section_title, []).append(item)
            else:
                extra.append(FeishuCardSection(title=section.title, items=[item]))
    normalized = [
        FeishuCardSection(
            title=title,
            items=_normalize_bazi_card_items(title, grouped[title]),
        )
        for title in _BAZI_SECTION_ORDER
        if grouped.get(title)
    ]
    return [*normalized, *extra]


def _canonical_bazi_section_title(title: str | None) -> str | None:
    normalized = re.sub(
        r"^[\s#*]*(?:[一二三四五六七八九十]+|\d+)[、.．]\s*",
        "",
        str(title or "").strip(),
    )
    normalized = normalized.strip("*：: ")
    if normalized in _BAZI_ALL_SECTION_ORDER:
        return normalized
    return _BAZI_SECTION_ALIASES.get(normalized)


def _split_bazi_markdown_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    preamble: list[str] = []
    for line in str(text or "").splitlines():
        candidate = re.sub(r"^[\s#*]+", "", line).strip().rstrip("*")
        candidate = re.sub(
            r"^(?:[一二三四五六七八九十]+|\d+)[、.．]\s*",
            "",
            candidate,
        ).strip()
        heading, separator, remainder = candidate.partition("：")
        canonical = _canonical_bazi_section_title(heading)
        if canonical is None and not separator:
            heading, separator, remainder = candidate.partition(":")
            canonical = _canonical_bazi_section_title(heading)
        if canonical is not None:
            if current_title is None and preamble:
                sections.append(("原局格局喜用", preamble))
            if current_title is not None:
                sections.append((current_title, current_lines))
            current_title = canonical
            current_lines = [remainder.strip()] if separator and remainder.strip() else []
            continue
        if current_title is not None:
            current_lines.append(line)
        elif line.strip():
            preamble.append(line)
    if current_title is not None:
        sections.append((current_title, current_lines))
    return [
        (title, "\n".join(lines).strip())
        for title, lines in sections
        if "\n".join(lines).strip()
    ]


def _dedupe_bazi_items(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        normalized = str(item or "").strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _normalize_bazi_card_items(title: str, items: list[str]) -> list[str]:
    deduped = _dedupe_bazi_items(items)
    if title != "过三关":
        return deduped
    normalized: list[str] = []
    for item in deduped:
        normalized.extend(_split_bazi_verification_items(item))
    return _dedupe_bazi_items(normalized)


def _split_bazi_verification_items(text: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    for raw_line in str(text or "").splitlines():
        parts = re.split(
            r"(?<![-*•\s])\s+(?=(?:[-*•]\s+)?\*{0,2}(?:19|20)\d{2}(?:\s*[-—至]\s*(?:19|20)\d{2})?\s*年?\s*[|｜])",
            raw_line.strip(),
        )
        for line in parts:
            if not line:
                continue
            starts_event = re.match(
                r"^(?:[-*•]\s+)?\*{0,2}(?:19|20)\d{2}(?:\s*[-—至]\s*(?:19|20)\d{2})?\s*年?\s*[|｜]",
                line,
            )
            if starts_event and current:
                items.append(_format_bazi_verification_item(" ".join(current)))
                current = []
            current.append(line)
    if current:
        items.append(_format_bazi_verification_item(" ".join(current)))
    return [item for item in items if item]


def _format_bazi_verification_item(text: str) -> str:
    normalized = re.sub(r"^(?:[-*•]\s+)", "", str(text or "").strip())
    normalized = normalized.replace("**", "")
    normalized = re.sub(r"\s*[|｜]\s*", "｜", normalized)
    year_match = re.match(
        r"^(?P<year>(?:19|20)\d{2}(?:\s*[-—至]\s*(?:19|20)\d{2})?\s*年?)｜(?P<body>.+)$",
        normalized,
    )
    if year_match is None:
        return normalized
    year = re.sub(r"\s+", "", year_match.group("year"))
    body_parts = year_match.group("body").strip().split("｜", maxsplit=1)
    event = normalize_verification_event_text(body_parts[0])
    body = "｜".join([event, *body_parts[1:]])
    return f"**{year}**｜{body}"


def _build_bazi_feishu_reply(text: str) -> str:
    split_items = _split_bazi_markdown_sections(text)
    grouped: dict[str, list[str]] = {}
    for title, content in split_items:
        if content:
            grouped.setdefault(title, []).append(content)
    sections = [
        FeishuCardSection(
            title=title,
            items=_normalize_bazi_card_items(title, grouped[title]),
        )
        for title in _BAZI_ALL_SECTION_ORDER
        if grouped.get(title)
    ]
    if not sections:
        sections = [FeishuCardSection(title="原局格局喜用", items=[text])]
    protocol = {
        "title": "八字文化分析",
        "summary": "排盘与解读完成",
        "sections": [section.model_dump(mode="json") for section in sections],
    }
    return (
        "排盘与解读完成。\n\n```feishu_card\n"
        + json.dumps(protocol, ensure_ascii=False)
        + "\n```"
    )


def _strip_internal_bazi_citations(text: str) -> str:
    cleaned_lines: list[str] = []
    field_pattern = re.compile(
        r"(?:source_id|chunk_id)\s*[:=]\s*`?[^\s;,，；|`]+`?",
        re.IGNORECASE,
    )
    id_pattern = re.compile(r"\b(?:ksrc|kchk)_[A-Za-z0-9_-]+\b")
    for raw_line in str(text or "").splitlines():
        line = field_pattern.sub("", raw_line)
        line = id_pattern.sub("", line)
        line = re.sub(r"^[\s*\-•]+(?=$)", "", line)
        line = re.sub(r"\s*[/|;,，；]+\s*(?=$|[。.!！？])", "", line)
        line = re.sub(r"^(?:参考语料|参考资料|参考依据|Theory 引用)\s*[:：]?\s*$", "", line)
        if line.strip():
            cleaned_lines.append(line.rstrip())
    return "\n".join(cleaned_lines).strip()


def finish_run_error(
    *,
    events: list[OutboundEvent],
    session_id: str,
    run_id: str,
    trace_id: str,
    run_started_at: float,
    llm_request_count: int,
    error_code: str,
    error_text: str,
    history: InMemoryRunHistory,
    agent_id: str,
    post_commit_callback=None,
) -> list[OutboundEvent]:
    events.append(
        OutboundEvent(
            session_id=session_id,
            run_id=run_id,
            event_id=f"evt_{uuid4().hex[:8]}",
            event_type="error",
            sequence=2,
            trace_id=trace_id,
            payload={"code": error_code, "text": error_text},
            created_at=datetime.now(timezone.utc),
        )
    )
    history.fail(run_id, error_code=error_code)
    history.finalize_total_timing(run_id, elapsed_ms=elapsed_ms(run_started_at))
    history.set_llm_request_count(run_id, llm_request_count)
    _invoke_post_commit_callback_safely(
        post_commit_callback,
        agent_id=agent_id,
    )
    return events


def record_failure(
    self_improve_recorder: SelfImproveRecorder | None,
    *,
    agent_id: str,
    run_id: str,
    trace_id: str,
    session_id: str,
    error_code: str,
    error_stage: str,
    message: str,
    summary: str,
    tool_name: str | None = None,
    provider_name: str | None = None,
    channel_id: str | None = None,
    observation_policy: str = "standard",
) -> None:
    if self_improve_recorder is None:
        return
    self_improve_recorder.record_failure(
        agent_id=agent_id,
        run_id=run_id,
        trace_id=trace_id,
        session_id=session_id,
        channel_id=channel_id,
        error_code=error_code,
        error_stage=error_stage,
        tool_name=tool_name,
        provider_name=provider_name,
        summary=str(project_text(summary, observation_policy) or ""),
        message=str(project_text(message, observation_policy) or ""),
    )


def record_recovery(
    self_improve_recorder: SelfImproveRecorder | None,
    *,
    agent_id: str,
    run_id: str,
    trace_id: str,
    message: str,
    channel_id: str | None = None,
) -> None:
    if self_improve_recorder is None:
        return
    self_improve_recorder.record_recovery(
        agent_id=agent_id,
        run_id=run_id,
        trace_id=trace_id,
        message=message,
        channel_id=channel_id,
        fix_summary="later successful completion on a compatible request",
        success_evidence="final reply generated",
    )


def append_post_turn_summary(
    *,
    history: InMemoryRunHistory,
    user_message: str,
    tool_history: list[ToolExchange],
    final_text: str,
    combined_summary_draft: ToolEpisodeSummaryDraft | None,
    run_id: str,
    tool_snapshot: ToolSnapshot,
) -> None:
    if not tool_history or not final_text.strip():
        return
    latest = tool_history[-1]
    if _should_skip_post_turn_summary(latest):
        return
    if any(item.tool_name in {"self_improve", "automation"} for item in tool_history):
        return
    summary = summarize_completed_tool_episode(
        user_message=user_message,
        tool_history=tool_history,
        final_text=final_text,
        combined_summary_draft=combined_summary_draft,
        run_id=run_id,
        tool_snapshot=tool_snapshot,
    )
    if summary is not None:
        history.append_tool_outcome_summary(run_id, summary)


def _should_skip_post_turn_summary(latest: ToolExchange) -> bool:
    action = str(
        (latest.tool_result or {}).get("action")
        or (latest.tool_payload or {}).get("action")
        or ""
    ).strip()
    if latest.tool_name == "runtime" and action == "context_status":
        return True
    if latest.tool_name == "session" and action in {"list", "show", "new", "resume"}:
        return True
    if latest.tool_name == "mcp" and action in {"list", "detail"}:
        return True
    return False


def trigger_review_from_success(
    *,
    history: InMemoryRunHistory,
    self_improve_recorder: SelfImproveRecorder | None,
    user_message: str,
    tool_history: list[ToolExchange],
    final_text: str,
    combined_summary_draft: ToolEpisodeSummaryDraft | None,
    run_id: str,
    trace_id: str,
    agent_id: str,
    tool_snapshot: ToolSnapshot,
    channel_id: str | None = None,
) -> None:
    del history
    if self_improve_recorder is None or not tool_history or not final_text.strip():
        return
    summary = summarize_completed_tool_episode(
        user_message=user_message,
        tool_history=tool_history,
        final_text=final_text,
        combined_summary_draft=combined_summary_draft,
        run_id=run_id,
        tool_snapshot=tool_snapshot,
    )
    if summary is None:
        return
    self_improve_recorder.record_successful_tool_episode(
        agent_id=agent_id,
        run_id=run_id,
        trace_id=trace_id,
        message=user_message,
        tool_history=tool_history,
        final_text=final_text,
        summary=summary.summary_text,
        channel_id=channel_id,
    )


def summarize_completed_tool_episode(
    *,
    user_message: str,
    tool_history: list[ToolExchange],
    final_text: str,
    combined_summary_draft: ToolEpisodeSummaryDraft | None,
    run_id: str,
    tool_snapshot: ToolSnapshot,
):
    del user_message
    try:
        fallback_summary = build_fallback_tool_episode_summary(
            run_id=run_id,
            history=tool_history,
            final_text=final_text,
            tool_snapshot=tool_snapshot,
        )
        draft = combined_summary_draft
        if draft is not None and draft.summary.strip():
            return build_combined_tool_episode_summary(
                run_id=run_id,
                history=tool_history,
                tool_snapshot=tool_snapshot,
                draft=draft,
                fallback_summary=fallback_summary,
            )
    except Exception:
        logger.debug("tool episode summary extraction failed", exc_info=True)
    return build_fallback_tool_episode_summary(
        run_id=run_id,
        history=tool_history,
        final_text=final_text,
        tool_snapshot=tool_snapshot,
    )
