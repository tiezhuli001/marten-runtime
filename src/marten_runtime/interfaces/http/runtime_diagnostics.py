from __future__ import annotations

from dataclasses import asdict, is_dataclass
from urllib.parse import urlsplit

from fastapi import Request

from marten_runtime.interfaces.http.bootstrap import HTTPRuntimeState
from marten_runtime.runtime.provider_reliability import build_provider_health_summary
from marten_runtime.runtime.llm_provider_support import resolve_base_url

RECENT_TOOL_OUTCOME_SUMMARY_LIMIT = 3


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
    compaction_jobs = (
        runtime.session_store.list_compaction_jobs()
        if hasattr(runtime.session_store, "list_compaction_jobs")
        else []
    )
    latest_compaction_job = compaction_jobs[-1] if compaction_jobs else None
    queued_compaction_jobs = [
        item for item in compaction_jobs if str(item.get("status") or "").strip() == "queued"
    ]
    worker = getattr(runtime, "compaction_worker", None)
    provider_health_summary = build_provider_health_summary(
        runtime.runtime_loop.history.list_runs(),
        window_size=20,
    )
    return {
        "config_snapshot_id": runtime.config_snapshot.config_snapshot_id,
        "default_agent_id": runtime.default_agent.agent_id,
        "llm_provider": getattr(runtime.runtime_loop.llm, "provider_name", "unknown"),
        "llm_model": getattr(runtime.runtime_loop.llm, "model_name", "unknown"),
        "llm_profile": getattr(runtime.runtime_loop.llm, "profile_name", "unknown"),
        "provider_count": len(runtime.providers_config.providers),
        "providers": [
            {
                "provider_ref": provider_ref,
                "adapter": provider.adapter,
                "base_url": resolve_base_url(
                    provider=provider,
                    env=runtime.env,
                ),
                "configured_base_url": provider.base_url,
                "effective_base_url": resolve_base_url(
                    provider=provider,
                    env=runtime.env,
                ),
                "api_key_env": provider.api_key_env,
            }
            for provider_ref, provider in sorted(runtime.providers_config.providers.items())
        ],
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
        "observability": {
            "langfuse": runtime.langfuse_observer.status(),
        },
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
        "sessions": {
            "store_kind": runtime.session_store.storage_kind(),
            "store_path": runtime.session_store.storage_path(),
            "count": runtime.session_store.count(),
            "binding_count": runtime.session_store.binding_count(),
            "session_replay_user_turns": runtime.platform_config.runtime.session_replay_user_turns,
            "recent_tool_outcome_summary_limit": RECENT_TOOL_OUTCOME_SUMMARY_LIMIT,
        },
        "provider_reliability": provider_health_summary.model_dump(mode="json"),
        "memory": runtime.memory_service.diagnostics_summary(),
        "knowledge": _knowledge_diagnostics(runtime),
        "bazi": runtime.bazi_bridge_manager.diagnostics_summary(),
        "compaction_worker": {
            "enabled": worker is not None,
            "running": bool(
                worker is not None
                and getattr(getattr(worker, "_thread", None), "is_alive", lambda: False)()
            ),
            "queue_depth": len(queued_compaction_jobs),
            "latest_job": latest_compaction_job,
        },
        "latest_session_transition": runtime.latest_session_transition,
        "env_loaded": runtime.env_load_result.loaded,
    }


def _knowledge_diagnostics(runtime: HTTPRuntimeState) -> dict[str, object]:
    service = runtime.knowledge_service
    namespaces = service.store.list_namespace_summaries()
    mismatch_count = sum(
        1
        for item in namespaces
        if item.get("index_embedding_config_hash")
        and item.get("index_embedding_config_hash") != service.embedding_config_hash
    )
    job_counts = service.store.ingest_job_diagnostics()
    model_status = service.model_status()
    configured = bool(str(runtime.env.get("KNOWLEDGE_OPERATOR_TOKEN") or "").strip())
    agent_scope = _knowledge_agent_scope_diagnostics(runtime)
    return {
        "operator_api": {
            "configured": configured,
            "reason": None if configured else "credential_missing",
        },
        "config_source": "config/knowledge.toml",
        "database": "data/knowledge/knowledge.sqlite3",
        "staging": "data/knowledge/uploads",
        "embedding_config_hash": service.embedding_config_hash,
        "namespace_count": len(namespaces),
        "namespace_mismatch_count": mismatch_count,
        "active_job_count": job_counts["active_count"],
        "interrupted_job_count": job_counts["interrupted_count"],
        "sqlite_vec": {"available": service.store.sqlite_vec_available()},
        "embedding": model_status["embedding"],
        "reranker": model_status["reranker"],
        "job_recovery": service.job_recovery_status,
        "agent_scope": agent_scope,
    }


def _knowledge_agent_scope_diagnostics(runtime: HTTPRuntimeState) -> dict[str, object]:
    bazi_namespaces = {"bazi-theory", "bazi-cases"}
    write_actions = {
        "ingest_text",
        "ingest_file",
        "cancel_ingest",
        "delete_source",
        "reindex",
        "unload_models",
    }
    items: list[dict[str, object]] = []
    family_level_agents: list[str] = []
    unsafe_bazi_write_agents: list[str] = []
    for agent_id in sorted(runtime.agent_runtimes):
        spec = runtime.agent_registry.get(agent_id)
        if not spec.enabled or "knowledge" not in spec.allowed_tools:
            continue
        namespaces = spec.allowed_knowledge_namespaces
        actions = spec.allowed_knowledge_actions
        explicit = namespaces is not None and actions is not None
        if not explicit:
            family_level_agents.append(agent_id)
        if bazi_namespaces & set(namespaces or []) and write_actions & set(actions or []):
            unsafe_bazi_write_agents.append(agent_id)
        items.append(
            {
                "agent_id": agent_id,
                "explicit": explicit,
                "namespaces": list(namespaces) if namespaces is not None else None,
                "actions": list(actions) if actions is not None else None,
            }
        )
    bazi = next((item for item in items if item["agent_id"] == "bazi"), None)
    bazi_read_only = bool(
        bazi
        and set(bazi["namespaces"] or []) == bazi_namespaces
        and set(bazi["actions"] or []) == {"search", "get_chunk", "model_status"}
    )
    return {
        "production_ready": not family_level_agents and not unsafe_bazi_write_agents and bazi_read_only,
        "bazi_read_only": bazi_read_only,
        "family_level_agents": family_level_agents,
        "unsafe_bazi_write_agents": unsafe_bazi_write_agents,
        "agents": items,
    }
