from __future__ import annotations

from dataclasses import asdict, is_dataclass
from urllib.parse import urlsplit

from fastapi import Request

from marten_runtime.interfaces.http.bootstrap import HTTPRuntimeState


def resolve_runtime_server_surface(
    runtime: HTTPRuntimeState,
    request: Request,
) -> dict[str, object]:
    configured_host = runtime.platform_config.server.host
    configured_port = runtime.platform_config.server.port
    configured_public_base_url = runtime.platform_config.server.public_base_url
    effective_host = configured_host
    effective_port = configured_port
    effective_public_base_url = configured_public_base_url
    observed_base_url = str(request.base_url).rstrip("/")
    if observed_base_url:
        split = urlsplit(observed_base_url)
        if split.hostname:
            effective_host = split.hostname
        if split.port is not None:
            effective_port = split.port
        elif split.scheme == "https":
            effective_port = 443
        elif split.scheme == "http":
            effective_port = 80
        effective_public_base_url = observed_base_url
    return {
        "host": effective_host,
        "port": effective_port,
        "public_base_url": effective_public_base_url,
        "configured_host": configured_host,
        "configured_port": configured_port,
        "configured_public_base_url": configured_public_base_url,
    }


def serialize_runtime_diagnostics(
    runtime: HTTPRuntimeState,
    request: Request,
) -> dict[str, object]:
    retry_policy = getattr(runtime.runtime_loop.llm, "retry_policy", None)
    latest_candidate = runtime.self_improve_store.latest_candidate(
        agent_id=runtime.default_agent.agent_id
    )
    latest_rejected_candidate = runtime.self_improve_store.latest_candidate(
        agent_id=runtime.default_agent.agent_id,
        status="rejected",
    )
    latest_active_lesson = runtime.self_improve_store.latest_active_lesson(
        agent_id=runtime.default_agent.agent_id
    )
    latest_review_trigger = runtime.self_improve_store.latest_review_trigger(
        agent_id=runtime.default_agent.agent_id
    )
    pending_review_triggers = runtime.self_improve_store.list_review_triggers(
        agent_id=runtime.default_agent.agent_id,
        limit=100,
        status="pending",
    )
    queued_review_triggers = runtime.self_improve_store.list_review_triggers(
        agent_id=runtime.default_agent.agent_id,
        limit=100,
        status="queued",
    )
    running_review_triggers = runtime.self_improve_store.list_review_triggers(
        agent_id=runtime.default_agent.agent_id,
        limit=100,
        status="running",
    )
    pending_skill_candidates = runtime.self_improve_store.list_skill_candidates(
        agent_id=runtime.default_agent.agent_id,
        limit=100,
        status="pending",
    )
    latest_skill_candidate = pending_skill_candidates[0] if pending_skill_candidates else None
    server_surface = resolve_runtime_server_surface(runtime, request)
    return {
        "config_snapshot_id": runtime.config_snapshot.config_snapshot_id,
        "app_id": runtime.app_manifest.app_id,
        "default_agent_id": runtime.app_manifest.default_agent,
        "llm_provider": getattr(runtime.runtime_loop.llm, "provider_name", "unknown"),
        "llm_model": getattr(runtime.runtime_loop.llm, "model_name", "unknown"),
        "llm_profile": getattr(runtime.runtime_loop.llm, "profile_name", "unknown"),
        "tool_count": len(runtime.tool_registry.list()),
        "mcp_server_count": len(runtime.mcp_servers),
        "mcp_servers": [
            {
                "server_id": server.server_id,
                "transport": server.transport,
                "enabled": server.enabled,
                "source_layers": server.source_layers,
                "tool_count": len(server.tools),
                "tool_names": [tool.name for tool in server.tools],
                "discovery": runtime.mcp_discovery.get(
                    server.server_id,
                    {"state": "unknown", "tool_count": len(server.tools), "error": None},
                ),
            }
            for server in runtime.mcp_servers
        ],
        "server": server_surface,
        "provider_retry_policy": (
            asdict(retry_policy)
            if retry_policy is not None and is_dataclass(retry_policy)
            else None
        ),
        "self_improve": {
            "enabled": True,
            "agent_id": runtime.default_agent.agent_id,
            "active_lessons_count": len(
                runtime.self_improve_store.list_active_lessons(
                    agent_id=runtime.default_agent.agent_id
                )
            ),
            "latest_candidate_status": (
                latest_candidate.status if latest_candidate is not None else None
            ),
            "latest_candidate_created_at": (
                latest_candidate.created_at.isoformat()
                if latest_candidate is not None
                else None
            ),
            "latest_lesson_created_at": (
                latest_active_lesson.created_at.isoformat()
                if latest_active_lesson is not None
                else None
            ),
            "latest_accepted_lesson_summary": (
                latest_active_lesson.lesson_text
                if latest_active_lesson is not None
                else None
            ),
            "latest_rejected_lesson_summary": (
                latest_rejected_candidate.candidate_text
                if latest_rejected_candidate is not None
                else None
            ),
            "pending_review_triggers_count": len(pending_review_triggers),
            "queued_review_triggers_count": len(queued_review_triggers),
            "running_review_triggers_count": len(running_review_triggers),
            "pending_skill_candidates_count": len(pending_skill_candidates),
            "latest_pending_skill_candidate_slug": (
                latest_skill_candidate.slug if latest_skill_candidate is not None else None
            ),
            "latest_review_trigger_status": (
                latest_review_trigger.status if latest_review_trigger is not None else None
            ),
        },
        "lanes": runtime.lane_manager.stats(),
        "channels": {
            "http": {"enabled": runtime.channels_config.http.enabled},
            "cli": {"enabled": runtime.channels_config.cli.enabled},
            "feishu": {
                "enabled": runtime.channels_config.feishu.enabled,
                "connection_mode": runtime.channels_config.feishu.connection_mode,
                "auto_start": runtime.channels_config.feishu.auto_start,
                "routing_policy": {
                    "allowed_chat_types": runtime.channels_config.feishu.allowed_chat_types,
                    "allowed_chat_ids": runtime.channels_config.feishu.allowed_chat_ids,
                },
                "receipt_store": runtime.feishu_receipts.stats(),
                "delivery_sessions": runtime.feishu_delivery.session_store.stats(),
                "dead_letter": runtime.feishu_delivery.dead_letter_queue.stats(),
                "retry_policy": runtime.feishu_delivery.retry_policy.model_dump(),
                "websocket": runtime.feishu_socket_service.stats(),
            },
        },
        "env_loaded": runtime.env_load_result.loaded,
    }
