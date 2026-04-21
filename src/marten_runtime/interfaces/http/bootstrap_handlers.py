from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from marten_runtime.automation.dispatch import AutomationDispatch, build_dispatch
from marten_runtime.automation.skill_ids import resolve_automation_runtime_skill_id
from marten_runtime.channels.feishu.delivery import FeishuDeliveryPayload
from marten_runtime.channels.feishu.usage import build_usage_summary_from_history
from marten_runtime.channels.feishu.rendering import (
    build_feishu_card_protocol_guard_instruction,
    render_final_reply_card,
)
from marten_runtime.config.models_loader import resolve_model_profile
from marten_runtime.gateway.models import InboundEnvelope
from marten_runtime.session.compaction_trigger import build_compaction_settings
from marten_runtime.session.models import SessionMessage
from marten_runtime.session.title_summary import build_session_title_summary
from marten_runtime.skills.models import SkillSpec
from marten_runtime.skills.selector import select_activated_skills
from marten_runtime.tools.builtins.automation_tool import (
    pop_registration_context,
    push_registration_context,
)

from marten_runtime.interfaces.http.bootstrap_runtime import HTTPRuntimeState
from marten_runtime.interfaces.http.channel_event_serialization import (
    history_visible_text,
    serialize_event_for_channel,
)


def render_metrics(state: HTTPRuntimeState) -> str:
    run_items = state.run_history.list_runs()
    lane_stats = state.lane_manager.stats()
    lines = {
        "session_created_total": state.session_store.count(),
        "active_session_count": state.session_store.count(),
        "provider_request_total": state.runtime_loop.request_count,
        "run_succeeded_total": sum(
            1 for item in run_items if item.status == "succeeded"
        ),
        "run_failed_total": sum(1 for item in run_items if item.status == "failed"),
        "active_lane_count": lane_stats["active_lane_count"],
        "queued_lane_count": lane_stats["queued_lane_count"],
    }
    return "\n".join(f"{key} {value}" for key, value in lines.items())


def _process_inbound_envelope(
    state: HTTPRuntimeState, envelope: InboundEnvelope
) -> dict[str, object]:
    session = state.session_store.get_or_create_for_conversation(
        conversation_id=envelope.conversation_id,
        config_snapshot_id=state.config_snapshot.config_snapshot_id,
        bootstrap_manifest_id=state.app_manifest.bootstrap_manifest_id,
        channel_id=envelope.channel_id,
    )
    routed_agent = state.agent_router.route(
        envelope,
        active_agent_id=session.active_agent_id,
        requested_agent_id=envelope.requested_agent_id,
    )
    app_runtime = state.app_runtimes.get(
        routed_agent.app_id, state.app_runtimes[state.app_manifest.app_id]
    )
    state.session_store.set_active_agent(session.session_id, routed_agent.agent_id)
    _ensure_session_catalog_metadata(
        state=state,
        session_id=session.session_id,
        trace_id=envelope.trace_id,
        app_id=routed_agent.app_id,
        agent_id=routed_agent.agent_id,
        model_profile_name=getattr(routed_agent, "model_profile", None),
        user_id=envelope.user_id,
        user_message=envelope.body,
    )
    state.session_store.set_bootstrap_manifest(
        session.session_id, app_runtime.manifest.bootstrap_manifest_id
    )
    state.session_store.append_message(
        session.session_id,
        SessionMessage.user(
            envelope.body,
            created_at=envelope.received_at,
            received_at=envelope.received_at,
            enqueued_at=envelope.enqueued_at or envelope.received_at,
            started_at=envelope.started_at,
        ),
    )
    skill_runtime = state.skill_service.build_runtime(
        agent_id=routed_agent.agent_id,
        channel_id=envelope.channel_id,
        env=state.env,
        config={},
    )
    token = push_registration_context(
        {
            "channel_id": envelope.channel_id,
            "conversation_id": envelope.conversation_id,
            "app_id": routed_agent.app_id,
            "agent_id": routed_agent.agent_id,
        }
    )
    try:
        events = _run_turn(
            state=state,
            session_id=session.session_id,
            message=envelope.body,
            trace_id=envelope.trace_id,
            agent=routed_agent,
            app_runtime=app_runtime,
            session_messages=session.history,
            skill_runtime=skill_runtime,
            activated_skills=[],
            channel_id=envelope.channel_id,
            conversation_id=envelope.conversation_id,
            user_id=envelope.user_id,
            request_kind="interactive",
        )
    finally:
        pop_registration_context(token)
    return _finalize_session_turn(
        state=state,
        session_id=session.session_id,
        trace_id=envelope.trace_id,
        events=events,
        job_ids=[],
        channel_id=envelope.channel_id,
    )


def _process_automation_dispatch(
    state: HTTPRuntimeState,
    dispatch: AutomationDispatch,
) -> dict[str, object]:
    session = state.session_store.get_or_create_for_conversation(
        conversation_id=dispatch.session_id,
        config_snapshot_id=state.config_snapshot.config_snapshot_id,
        bootstrap_manifest_id=state.app_manifest.bootstrap_manifest_id,
        channel_id=dispatch.delivery_channel,
    )
    routed_agent = state.agent_registry.get(dispatch.agent_id)
    app_runtime = state.app_runtimes.get(
        routed_agent.app_id, state.app_runtimes[state.app_manifest.app_id]
    )
    state.session_store.set_active_agent(session.session_id, routed_agent.agent_id)
    _ensure_session_catalog_metadata(
        state=state,
        session_id=session.session_id,
        trace_id=dispatch.trace_id,
        app_id=routed_agent.app_id,
        agent_id=routed_agent.agent_id,
        model_profile_name=getattr(routed_agent, "model_profile", None),
        user_id="",
        user_message=dispatch.prompt_template,
    )
    state.session_store.set_bootstrap_manifest(
        session.session_id, app_runtime.manifest.bootstrap_manifest_id
    )
    state.session_store.append_message(
        session.session_id, SessionMessage.user(dispatch.prompt_template)
    )
    skill_runtime = state.skill_service.build_runtime(
        agent_id=routed_agent.agent_id,
        channel_id=dispatch.delivery_channel,
        env=state.env,
        config={},
    )
    activated_skills = _resolve_automation_skills(
        state, skill_runtime.visible_skills, dispatch
    )
    events = _run_turn(
        state=state,
        session_id=session.session_id,
        message=dispatch.prompt_template,
        trace_id=dispatch.trace_id,
        agent=routed_agent,
        app_runtime=app_runtime,
        session_messages=session.history,
        skill_runtime=skill_runtime,
        activated_skills=activated_skills,
        channel_id=dispatch.delivery_channel,
        request_kind="automation",
    )
    if dispatch.skill_id == "self_improve":
        state.self_improve_service.process_pending_candidates(
            agent_id=routed_agent.agent_id
        )
    _deliver_automation_events(state, dispatch, events)
    response = _finalize_session_turn(
        state=state,
        session_id=session.session_id,
        trace_id=dispatch.trace_id,
        events=events,
        job_ids=[dispatch.automation_id],
        channel_id=dispatch.delivery_channel,
    )
    response.update(
        {
            "automation_id": dispatch.automation_id,
            "scheduled_for": dispatch.scheduled_for,
            "delivery_channel": dispatch.delivery_channel,
            "delivery_target": dispatch.delivery_target,
        }
    )
    return response


def build_manual_automation_dispatch(
    state: HTTPRuntimeState, automation_id: str
) -> AutomationDispatch:
    job = state.automation_store.get(automation_id)
    scheduled_for = (
        datetime.now(timezone.utc).astimezone(ZoneInfo(job.timezone)).date().isoformat()
    )
    return build_dispatch(
        job, scheduled_for=scheduled_for, trace_id=f"trace_auto_{uuid4().hex[:8]}"
    )


def _deliver_automation_events(
    state: HTTPRuntimeState,
    dispatch: AutomationDispatch,
    events: list,
) -> None:
    if dispatch.delivery_channel != "feishu":
        return
    for event in events:
        state.feishu_delivery.deliver(
            FeishuDeliveryPayload(
                chat_id=dispatch.delivery_target,
                event_type=event.event_type,
                event_id=event.event_id,
                run_id=event.run_id,
                trace_id=event.trace_id,
                sequence=event.sequence,
                text=str(event.payload.get("text", "")),
                dedupe_key=(
                    f"feishu:{dispatch.delivery_target}:{dispatch.scheduled_for}"
                    if event.event_type == "final"
                    else None
                ),
                usage_summary=(
                    build_usage_summary_from_history(state.run_history, event.run_id)
                    if event.event_type in {"final", "error"}
                    else None
                ),
            )
        )


def _run_turn(
    *,
    state: HTTPRuntimeState,
    session_id: str,
    message: str,
    trace_id: str,
    agent,
    app_runtime,
    session_messages,
    skill_runtime,
    activated_skills: list[SkillSpec],
    channel_id: str,
    conversation_id: str | None = None,
    user_id: str | None = None,
    request_kind: str = "interactive",
):
    resolved_profile_name = getattr(agent, "model_profile", None)
    resolved_llm = state.llm_client_factory.get(
        resolved_profile_name,
        default_client=state.runtime_loop.llm,
    )
    _, profile = resolve_model_profile(state.models_config, resolved_profile_name)
    events = state.runtime_loop.run(
        session_id,
        message,
        trace_id=trace_id,
        llm_client=resolved_llm,
        system_prompt=app_runtime.system_prompt,
        agent=agent,
        config_snapshot_id=state.config_snapshot.config_snapshot_id,
        bootstrap_manifest_id=app_runtime.manifest.bootstrap_manifest_id,
        model_profile_name=resolved_profile_name,
        tokenizer_family=profile.tokenizer_family,
        skill_snapshot_id=skill_runtime.snapshot.skill_snapshot_id,
        session_messages=session_messages,
        recent_tool_outcome_summaries=state.session_store.list_recent_tool_outcome_summaries(
            session_id, limit=3
        ),
        compacted_context=state.session_store.get(session_id).latest_compacted_context,
        compact_llm_client=resolved_llm,
        on_compacted=lambda item: state.session_store.set_compacted_context(
            session_id, item
        ),
        skill_snapshot=skill_runtime.snapshot,
        skill_heads_text=skill_runtime.skill_heads_text,
        capability_catalog_text=state.capability_catalog_text,
        always_on_skill_text=skill_runtime.always_on_text,
        activated_skill_ids=[item.meta.skill_id for item in activated_skills],
        activated_skill_bodies=[item.body for item in activated_skills if item.body],
        channel_protocol_instruction_text=(
            build_feishu_card_protocol_guard_instruction()
            if channel_id == "feishu"
            else None
        ),
        memory_text=state.memory_service.render_prompt_memory(user_id or ""),
        compact_settings=build_compaction_settings(profile),
        request_kind=request_kind,
        channel_id=channel_id,
        conversation_id=conversation_id,
        user_id=user_id,
    )
    try:
        run = state.run_history.get(events[-1].run_id)
    except KeyError:
        run = None
    if run is not None and run.latest_actual_usage is not None:
        state.session_store.set_latest_actual_usage(session_id, run.latest_actual_usage)
    if run is not None:
        for summary in run.tool_outcome_summaries:
            state.session_store.append_tool_outcome_summary(session_id, summary)
    return events


def _finalize_session_turn(
    *,
    state: HTTPRuntimeState,
    session_id: str,
    trace_id: str,
    events: list,
    job_ids: list[str],
    channel_id: str,
) -> dict[str, object]:
    state.session_store.append_message(
        session_id,
        SessionMessage.assistant(
            history_visible_text(str(events[-1].payload.get("text", "")))
        ),
    )
    state.session_store.mark_run(session_id, events[-1].run_id, events[-1].created_at)
    try:
        run = state.run_history.get(events[-1].run_id)
    except KeyError:
        run = None
    external_refs = {
        "langfuse_trace_id": (
            run.external_observability.langfuse_trace_id if run is not None else None
        ),
        "langfuse_url": (
            run.external_observability.langfuse_url if run is not None else None
        ),
    }
    state.trace_index[trace_id] = {
        "run_ids": [events[-1].run_id],
        "job_ids": job_ids,
        "event_ids": [event.event_id for event in events],
        "external_refs": external_refs,
    }
    terminal_event = events[-1]
    terminal_text = str(terminal_event.payload.get("text", ""))
    return {
        "status": "accepted",
        "session_id": session_id,
        "trace_id": trace_id,
        "result": terminal_text,
        "final_text": terminal_text,
        "text": terminal_text,
        "card": (
            render_final_reply_card(
                terminal_text,
                event_type=terminal_event.event_type,
                usage_summary=build_usage_summary_from_history(
                    state.run_history,
                    terminal_event.run_id,
                ),
            )
            if channel_id == "feishu" and terminal_event.event_type in {"final", "error"}
            else None
        ),
        "error_code": (
            str(terminal_event.payload.get("code", ""))
            if terminal_event.event_type == "error"
            else None
        ),
        "events": [
            serialize_event_for_channel(
                event,
                channel_id=channel_id,
                run_history=state.run_history,
            )
            for event in events
        ],
    }


def _ensure_session_catalog_metadata(
    *,
    state: HTTPRuntimeState,
    session_id: str,
    trace_id: str,
    app_id: str,
    agent_id: str,
    model_profile_name: str | None,
    user_id: str,
    user_message: str,
) -> None:
    session = state.session_store.get(session_id)
    if session.session_title:
        if session.user_id != user_id or session.agent_id != agent_id:
            state.session_store.set_catalog_metadata(
                session_id,
                user_id=user_id,
                agent_id=agent_id,
                session_title=session.session_title,
                session_preview=session.session_preview,
            )
        return
    llm_client = state.llm_client_factory.get(
        model_profile_name,
        default_client=state.runtime_loop.llm,
    )
    title, preview = build_session_title_summary(
        llm_client=llm_client,
        session_id=session_id,
        trace_id=trace_id,
        app_id=app_id,
        agent_id=agent_id,
        user_message=user_message,
    )
    state.session_store.set_catalog_metadata(
        session_id,
        user_id=user_id,
        agent_id=agent_id,
        session_title=title,
        session_preview=preview,
    )


def _resolve_automation_skills(
    state: HTTPRuntimeState,
    visible_skills: list[SkillSpec],
    dispatch: AutomationDispatch,
) -> list[SkillSpec]:
    runtime_skill_id = resolve_automation_runtime_skill_id(dispatch.skill_id)
    if not runtime_skill_id:
        return []
    activated_skill = select_activated_skills(
        visible_skills,
        dispatch.prompt_template,
        explicit_skill_ids=[runtime_skill_id],
    )
    if activated_skill:
        return activated_skill
    return [state.skill_service.load_skill(runtime_skill_id)]
