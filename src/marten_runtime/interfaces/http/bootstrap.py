from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from marten_runtime.apps.bootstrap_prompt import load_bootstrap_prompt
from marten_runtime.agents.bindings import AgentBindingRegistry
from marten_runtime.apps.manifest import AppManifest, load_app_manifest
from marten_runtime.agents.registry import AgentRegistry
from marten_runtime.agents.router import AgentRouter
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.channels.delivery_retry import DeliveryRetryPolicy
from marten_runtime.channels.feishu.delivery import FeishuDeliveryClient
from marten_runtime.channels.feishu.service import FeishuWebsocketService
from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.config.agents_loader import load_agent_specs
from marten_runtime.config.bindings_loader import load_agent_bindings
from marten_runtime.config.channels_loader import ChannelsConfig, load_channels_config
from marten_runtime.config.env_loader import EnvLoadResult, load_repo_env
from marten_runtime.config.models import ConfigSnapshot
from marten_runtime.config.models_loader import ModelsConfig, load_models_config, resolve_model_profile
from marten_runtime.config.platform_loader import PlatformConfig, load_platform_config
from marten_runtime.gateway.models import InboundEnvelope
from marten_runtime.mcp.client import MCPClient
from marten_runtime.mcp.discovery import discover_mcp_tools
from marten_runtime.mcp.loader import load_mcp_servers
from marten_runtime.mcp.models import MCPServerSpec
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import build_llm_client
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.session.store import SessionStore
from marten_runtime.skills.selector import select_activated_skills
from marten_runtime.skills.service import SkillService
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.registry import ToolRegistry


TraceIndex = dict[str, dict[str, list[str] | dict[str, str | None]]]


@dataclass
class HTTPRuntimeState:
    repo_root: Path
    env: dict[str, str]
    env_load_result: EnvLoadResult
    app_manifest: AppManifest
    platform_config: PlatformConfig
    models_config: ModelsConfig
    channels_config: ChannelsConfig
    mcp_servers: list[MCPServerSpec]
    config_snapshot: ConfigSnapshot
    session_store: SessionStore
    run_history: InMemoryRunHistory
    tool_registry: ToolRegistry
    mcp_client: MCPClient
    mcp_discovery: dict[str, dict[str, object]]
    agent_registry: AgentRegistry
    binding_registry: AgentBindingRegistry
    agent_router: AgentRouter
    default_agent: AgentSpec
    skill_service: SkillService
    system_prompt: str
    runtime_loop: RuntimeLoop
    feishu_delivery: FeishuDeliveryClient
    feishu_receipts: InMemoryReceiptStore
    feishu_socket_service: FeishuWebsocketService
    trace_index: TraceIndex = field(default_factory=dict)


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def build_http_runtime(
    *,
    repo_root: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    load_env_file: bool = True,
    use_compat_json: bool = True,
) -> HTTPRuntimeState:
    resolved_repo_root = Path(repo_root) if repo_root is not None else default_repo_root()
    env_load_result = EnvLoadResult(loaded=False, path=str(resolved_repo_root / ".env"))
    if env is None:
        if load_env_file:
            env_load_result = load_repo_env(resolved_repo_root)
        resolved_env = dict(os.environ)
    else:
        resolved_env = dict(env)
    compat_json_path = str(resolved_repo_root / "mcps.json") if use_compat_json else None
    app_manifest = load_app_manifest(str(resolved_repo_root / "apps/example_assistant/app.toml"))
    system_prompt = load_bootstrap_prompt(repo_root=resolved_repo_root, manifest=app_manifest)
    platform_config = load_platform_config(str(resolved_repo_root / "config/platform.toml"), env=resolved_env)
    models_config = load_models_config(str(resolved_repo_root / "config/models.toml"))
    channels_config = load_channels_config(str(resolved_repo_root / "config/channels.toml"))
    mcp_servers = load_mcp_servers(str(resolved_repo_root / "config/mcp.toml"), compat_json_path)

    tool_registry = ToolRegistry()
    tool_registry.register("time", run_time_tool)
    mcp_client = MCPClient(mcp_servers, env=resolved_env)
    mcp_discovery = discover_mcp_tools(mcp_servers, mcp_client)
    for server in mcp_servers:
        for tool in server.tools:
            tool_registry.register(
                tool.name,
                lambda payload, server_id=server.server_id, tool_name=tool.name: mcp_client.call_tool(
                    server_id,
                    tool_name,
                    payload,
                ),
                source_kind="mcp",
                server_id=server.server_id,
                backend_id=server.backend_id,
                description=tool.description,
            )

    agent_registry = AgentRegistry()
    for spec in load_agent_specs(str(resolved_repo_root / "config/agents.toml")):
        agent_registry.register(spec)
    binding_registry = AgentBindingRegistry(
        load_agent_bindings(str(resolved_repo_root / "config/bindings.toml"))
    )
    agent_router = AgentRouter(
        agent_registry,
        default_agent_id=app_manifest.default_agent,
        bindings=binding_registry,
    )
    default_agent = agent_registry.get(app_manifest.default_agent)
    skill_service = SkillService(
        [
            str(resolved_repo_root / "skills/system"),
            str(resolved_repo_root / "skills/shared"),
            str(resolved_repo_root / app_manifest.bootstrap.root / app_manifest.skills.app_dir),
        ]
    )
    model_profile_name, model_profile = resolve_model_profile(models_config, default_agent.model_profile)
    runtime_loop = RuntimeLoop(
        build_llm_client(profile_name=model_profile_name, profile=model_profile, env=resolved_env),
        tool_registry,
        InMemoryRunHistory(),
    )
    feishu_delivery = FeishuDeliveryClient(
        env=resolved_env,
        retry_policy=DeliveryRetryPolicy(
            progress_max_retries=channels_config.feishu.retry.progress_max_retries,
            final_max_retries=channels_config.feishu.retry.final_max_retries,
            error_max_retries=channels_config.feishu.retry.error_max_retries,
            base_backoff_seconds=channels_config.feishu.retry.base_backoff_seconds,
            max_backoff_seconds=channels_config.feishu.retry.max_backoff_seconds,
        ),
    )
    feishu_receipts = InMemoryReceiptStore()
    state = HTTPRuntimeState(
        repo_root=resolved_repo_root,
        env=resolved_env,
        env_load_result=env_load_result,
        app_manifest=app_manifest,
        platform_config=platform_config,
        models_config=models_config,
        channels_config=channels_config,
        mcp_servers=mcp_servers,
        config_snapshot=ConfigSnapshot(),
        session_store=SessionStore(),
        run_history=runtime_loop.history,
        tool_registry=tool_registry,
        mcp_client=mcp_client,
        mcp_discovery=mcp_discovery,
        agent_registry=agent_registry,
        binding_registry=binding_registry,
        agent_router=agent_router,
        default_agent=default_agent,
        skill_service=skill_service,
        system_prompt=system_prompt,
        runtime_loop=runtime_loop,
        feishu_delivery=feishu_delivery,
        feishu_receipts=feishu_receipts,
        feishu_socket_service=None,  # type: ignore[arg-type]
    )
    state.feishu_socket_service = FeishuWebsocketService(
        env=resolved_env,
        receipt_store=feishu_receipts,
        runtime_handler=lambda envelope: _process_inbound_envelope(state, envelope),
        delivery_client=feishu_delivery,
        allowed_chat_types=channels_config.feishu.allowed_chat_types,
        allowed_chat_ids=channels_config.feishu.allowed_chat_ids,
        client_config=channels_config.feishu.websocket.model_copy(
            update={"auto_reconnect": channels_config.feishu.websocket.auto_reconnect}
        ),
    )
    return state


def render_metrics(state: HTTPRuntimeState) -> str:
    run_items = state.run_history.list_runs()
    lines = {
        "session_created_total": state.session_store.count(),
        "active_session_count": state.session_store.count(),
        "provider_request_total": state.runtime_loop.request_count,
        "run_succeeded_total": sum(1 for item in run_items if item.status == "succeeded"),
        "run_failed_total": sum(1 for item in run_items if item.status == "failed"),
        "queue_depth": 0,
        "context_compaction_total": 0,
    }
    return "\n".join(f"{key} {value}" for key, value in lines.items())


def _process_inbound_envelope(state: HTTPRuntimeState, envelope: InboundEnvelope) -> dict[str, object]:
    session = state.session_store.get_or_create_for_conversation(
        conversation_id=envelope.conversation_id,
        config_snapshot_id=state.config_snapshot.config_snapshot_id,
        bootstrap_manifest_id=state.app_manifest.bootstrap_manifest_id,
    )
    routed_agent = state.agent_router.route(envelope, active_agent_id=session.active_agent_id)
    state.session_store.set_active_agent(session.session_id, routed_agent.agent_id)
    from marten_runtime.session.models import SessionMessage

    state.session_store.append_message(session.session_id, SessionMessage.user(envelope.body))
    skill_runtime = state.skill_service.build_runtime(
        agent_id=routed_agent.agent_id,
        channel_id=envelope.channel_id,
        env=state.env,
        config={},
    )
    activated_skills = select_activated_skills(skill_runtime.visible_skills, envelope.body)
    events = state.runtime_loop.run(
        session.session_id,
        envelope.body,
        trace_id=envelope.trace_id,
        system_prompt=state.system_prompt,
        agent=routed_agent,
        config_snapshot_id=state.config_snapshot.config_snapshot_id,
        bootstrap_manifest_id=session.bootstrap_manifest_id,
        skill_snapshot_id=skill_runtime.snapshot.skill_snapshot_id,
        session_messages=session.history,
        skill_snapshot=skill_runtime.snapshot,
        skill_heads_text=skill_runtime.skill_heads_text,
        always_on_skill_text=skill_runtime.always_on_text,
        activated_skill_ids=[item.meta.skill_id for item in activated_skills],
        activated_skill_bodies=[item.body for item in activated_skills],
    )
    state.session_store.append_message(session.session_id, SessionMessage.assistant(events[-1].payload["text"]))
    state.session_store.mark_run(session.session_id, events[-1].run_id, events[-1].created_at)
    state.trace_index[envelope.trace_id] = {
        "run_ids": [events[-1].run_id],
        "job_ids": [],
        "event_ids": [event.event_id for event in events],
        "external_refs": {"langfuse": None, "langsmith": None},
    }
    return {
        "status": "accepted",
        "session_id": session.session_id,
        "trace_id": envelope.trace_id,
        "events": [event.model_dump(mode="json") for event in events],
    }
