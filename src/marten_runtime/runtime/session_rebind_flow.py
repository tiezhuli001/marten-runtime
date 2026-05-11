from dataclasses import dataclass

from marten_runtime.runtime.context import RuntimeContext, assemble_runtime_context
from marten_runtime.runtime.llm_client import LLMRequest
from marten_runtime.runtime.request_flow import build_request_from_context
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.session.store import SessionStore
from marten_runtime.skills.snapshot import SkillSnapshot
from marten_runtime.tools.registry import ToolSnapshot


@dataclass
class SameTurnSessionContext:
    session_id: str
    session_messages: list[SessionMessage]
    recent_tool_outcome_summaries: list[dict[str, object]]
    compacted_context: CompactedContext | None
    runtime_context: RuntimeContext
    pre_compact_runtime_context: RuntimeContext
    request_base: dict[str, object]
    first_request: LLMRequest
    current_request: LLMRequest
    latest_actual_usage: object | None


def rebind_same_turn_session_context(
    *,
    target_session_id: str,
    current_session_id: str,
    session_messages: list[SessionMessage],
    recent_tool_outcome_summaries: list[dict[str, object]],
    compacted_context: CompactedContext | None,
    runtime_context: RuntimeContext,
    pre_compact_runtime_context: RuntimeContext,
    request_base: dict[str, object],
    first_request: LLMRequest,
    current_request: LLMRequest,
    latest_actual_usage: object | None,
    session_store: SessionStore | None,
    message: str,
    system_prompt: str | None,
    tool_snapshot: ToolSnapshot,
    skill_snapshot: SkillSnapshot | None,
    activated_skill_ids: list[str] | None,
    skill_heads_text: str | None,
    capability_catalog_text: str | None,
    always_on_skill_text: str | None,
    channel_protocol_instruction_text: str | None,
    memory_text: str | None,
    repository_context_text: str | None,
    activated_skill_bodies: list[str] | None,
    session_replay_user_turns: int,
    bootstrap_manifest_id: str,
    prompt_mode: str | None,
    timeout_seconds_override: float | None,
    stop_event: object | None,
    deadline_monotonic: float | None,
) -> SameTurnSessionContext | None:
    normalized_target = str(target_session_id or "").strip()
    if not normalized_target or normalized_target == current_session_id:
        return None
    active_session_id = normalized_target
    active_session_messages = list(session_messages)
    active_recent_tool_outcome_summaries = list(recent_tool_outcome_summaries)
    active_compacted_context = compacted_context
    active_runtime_context = runtime_context
    active_pre_compact_runtime_context = pre_compact_runtime_context
    active_latest_actual_usage = latest_actual_usage
    if session_store is not None:
        target_session = session_store.get(active_session_id)
        active_session_messages = list(target_session.history)
        active_recent_tool_outcome_summaries = list(
            session_store.list_recent_tool_outcome_summaries(
                active_session_id,
                limit=3,
            )
        )
        active_compacted_context = target_session.latest_compacted_context
        active_latest_actual_usage = target_session.latest_actual_usage
        active_runtime_context = assemble_runtime_context(
            session_id=active_session_id,
            current_message=message,
            system_prompt=system_prompt,
            session_messages=active_session_messages,
            tool_snapshot=tool_snapshot,
            compacted_context=active_compacted_context,
            skill_snapshot=skill_snapshot,
            activated_skill_ids=activated_skill_ids,
            skill_heads_text=skill_heads_text,
            capability_catalog_text=capability_catalog_text,
            always_on_skill_text=always_on_skill_text,
            channel_protocol_instruction_text=channel_protocol_instruction_text,
            memory_text=memory_text,
            repository_context_text=repository_context_text,
            activated_skill_bodies=activated_skill_bodies,
            recent_tool_outcome_summaries=active_recent_tool_outcome_summaries,
            replay_user_turns=session_replay_user_turns,
        )
        active_pre_compact_runtime_context = assemble_runtime_context(
            session_id=active_session_id,
            current_message=message,
            system_prompt=system_prompt,
            session_messages=active_session_messages,
            tool_snapshot=tool_snapshot,
            compacted_context=None,
            skill_snapshot=skill_snapshot,
            activated_skill_ids=activated_skill_ids,
            skill_heads_text=skill_heads_text,
            capability_catalog_text=capability_catalog_text,
            always_on_skill_text=always_on_skill_text,
            channel_protocol_instruction_text=channel_protocol_instruction_text,
            memory_text=memory_text,
            repository_context_text=repository_context_text,
            activated_skill_bodies=activated_skill_bodies,
            recent_tool_outcome_summaries=active_recent_tool_outcome_summaries,
            replay_user_turns=session_replay_user_turns,
        )
    next_request_base = dict(request_base)
    next_request_base["session_id"] = active_session_id
    next_first_request = build_request_from_context(
        **next_request_base,
        ctx=active_runtime_context,
        include_available_tools=True,
        bootstrap_manifest_id=bootstrap_manifest_id,
        prompt_mode=prompt_mode,
        timeout_seconds_override=timeout_seconds_override,
        cooperative_stop_event=stop_event,
        cooperative_deadline_monotonic=deadline_monotonic,
    )
    return SameTurnSessionContext(
        session_id=active_session_id,
        session_messages=active_session_messages,
        recent_tool_outcome_summaries=active_recent_tool_outcome_summaries,
        compacted_context=active_compacted_context,
        runtime_context=active_runtime_context,
        pre_compact_runtime_context=active_pre_compact_runtime_context,
        request_base=next_request_base,
        first_request=next_first_request,
        current_request=next_first_request,
        latest_actual_usage=active_latest_actual_usage,
    )
