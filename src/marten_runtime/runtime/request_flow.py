import threading

from marten_runtime.runtime.context import RuntimeContext
from marten_runtime.runtime.llm_client import ConversationMessage, LLMClient, LLMReply, LLMRequest
from marten_runtime.runtime.request_timeout import (
    remaining_timeout_seconds,
    resolve_request_responses_api,
    resolve_request_timeout_seconds,
)
from marten_runtime.tools.registry import ToolSnapshot


def request_for_client(
    request: LLMRequest,
    llm_client: LLMClient,
    *,
    tokenizer_family: str | None,
    timeout_seconds_override: float | None,
    stop_event: threading.Event | None,
    deadline_monotonic: float | None,
) -> LLMRequest:
    return request.model_copy(
        update={
            "model_name": getattr(llm_client, "model_name", None),
            "tokenizer_family": tokenizer_family,
            "timeout_seconds_override": timeout_seconds_override
            if timeout_seconds_override is not None
            else remaining_timeout_seconds(deadline_monotonic),
            "cooperative_stop_event": stop_event,
            "cooperative_deadline_monotonic": deadline_monotonic,
        }
    )


def usage_payload(usage) -> dict[str, int] | None:  # noqa: ANN001
    if usage is None:
        return None
    return {
        "input_tokens": int(usage.input_tokens),
        "output_tokens": int(usage.output_tokens),
        "total_tokens": int(usage.total_tokens),
    }


def cumulative_usage_payload(run) -> dict[str, int] | None:  # noqa: ANN001
    total_tokens = int(run.actual_cumulative_total_tokens)
    if total_tokens <= 0:
        return None
    return {
        "input_tokens": int(run.actual_cumulative_input_tokens),
        "output_tokens": int(run.actual_cumulative_output_tokens),
        "total_tokens": total_tokens,
    }


def generation_input_payload(request: LLMRequest) -> dict[str, object]:
    return {
        "message": request.message,
        "available_tools": list(request.available_tools),
        "requested_tool_name": request.requested_tool_name,
        "tool_history_count": len(request.tool_history),
    }


def generation_output_payload(reply: LLMReply) -> dict[str, object]:
    if reply.tool_name:
        return {
            "tool_name": reply.tool_name,
            "tool_payload": dict(reply.tool_payload),
        }
    return {"final_text": reply.final_text or ""}


def build_request_from_context(
    *,
    session_id: str,
    trace_id: str,
    message: str,
    agent_id: str,
    model_name: str | None,
    tokenizer_family: str | None,
    channel_protocol_instruction_text: str | None,
    tool_snapshot: ToolSnapshot,
    request_kind: str,
    ctx: RuntimeContext,
    include_available_tools: bool = False,
    bootstrap_manifest_id: str | None = None,
    prompt_mode: str | None = None,
    **overrides: object,
) -> LLMRequest:
    fields: dict[str, object] = {
        "session_id": session_id,
        "trace_id": trace_id,
        "message": message,
        "agent_id": agent_id,
        "model_name": model_name,
        "tokenizer_family": tokenizer_family,
        "system_prompt": ctx.system_prompt,
        "conversation_messages": [
            ConversationMessage(role=item.role, content=item.content)
            for item in ctx.conversation_messages
        ],
        "compact_summary_text": ctx.compact_summary_text,
        "tool_outcome_summary_text": ctx.tool_outcome_summary_text,
        "memory_text": ctx.memory_text,
        "repository_context_text": ctx.repository_context_text,
        "working_context_text": ctx.working_context_text,
        "skill_heads_text": ctx.skill_heads_text,
        "capability_catalog_text": ctx.capability_catalog_text,
        "always_on_skill_text": ctx.always_on_skill_text,
        "channel_protocol_instruction_text": channel_protocol_instruction_text,
        "activated_skill_bodies": ctx.activated_skill_bodies,
        "tool_snapshot": tool_snapshot,
        "request_kind": request_kind,
        "cooperative_stop_event": overrides.get("cooperative_stop_event"),
        "cooperative_deadline_monotonic": overrides.get("cooperative_deadline_monotonic"),
    }
    if include_available_tools:
        fields["available_tools"] = tool_snapshot.available_tools()
    if ctx.working_context is not None:
        fields["working_context"] = ctx.working_context
    if ctx.context_snapshot_id:
        fields["context_snapshot_id"] = ctx.context_snapshot_id
    if ctx.skill_snapshot is not None:
        fields["skill_snapshot_id"] = ctx.skill_snapshot.skill_snapshot_id
        fields["activated_skill_ids"] = ctx.activated_skill_ids
    if bootstrap_manifest_id:
        fields["bootstrap_manifest_id"] = bootstrap_manifest_id
    if prompt_mode:
        fields["prompt_mode"] = prompt_mode
    fields.update(overrides)
    return LLMRequest(**fields)
