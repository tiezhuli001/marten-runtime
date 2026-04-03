from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from marten_runtime.automation.dispatch import AutomationDispatch, build_dispatch
from marten_runtime.automation.models import AutomationJob
from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.automation.store import AutomationStore
from marten_runtime.apps.bootstrap_prompt import load_bootstrap_prompt
from marten_runtime.agents.bindings import AgentBindingRegistry
from marten_runtime.apps.manifest import AppManifest, load_app_manifest
from marten_runtime.agents.registry import AgentRegistry
from marten_runtime.agents.router import AgentRouter
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.channels.delivery_retry import DeliveryRetryPolicy
from marten_runtime.channels.feishu.delivery import FeishuDeliveryClient, FeishuDeliveryPayload
from marten_runtime.channels.feishu.service import FeishuWebsocketService
from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.config.agents_loader import load_agent_specs
from marten_runtime.config.automations_loader import load_automations
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
from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.runtime.capabilities import (
    get_capability_declarations,
    render_capability_catalog,
    render_tool_description,
)
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.lanes import ConversationLaneManager
from marten_runtime.runtime.llm_client import build_llm_client
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.session.store import SessionStore
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.self_improve.service import SelfImproveService, make_default_judge
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.skills.selector import select_activated_skills
from marten_runtime.skills.models import SkillSpec
from marten_runtime.skills.service import SkillService
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.builtins.automation_tool import run_automation_tool
from marten_runtime.tools.builtins.self_improve_tool import run_self_improve_tool
from marten_runtime.tools.builtins.register_automation_tool import (
    pop_registration_context,
    push_registration_context,
)
from marten_runtime.tools.builtins.mcp_tool import build_mcp_capability_catalog, run_mcp_tool
from marten_runtime.tools.builtins.skill_tool import run_skill_tool
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
    automation_store: AutomationStore
    self_improve_store: SQLiteSelfImproveStore
    self_improve_service: SelfImproveService
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
    capability_catalog_text: str | None
    system_prompt: str
    runtime_loop: RuntimeLoop
    feishu_delivery: FeishuDeliveryClient
    feishu_receipts: InMemoryReceiptStore
    feishu_socket_service: FeishuWebsocketService
    lane_manager: ConversationLaneManager
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
    if not _has_feishu_credentials(resolved_env):
        channels_config = channels_config.model_copy(
            update={
                "feishu": channels_config.feishu.model_copy(
                    update={"enabled": False, "auto_start": False}
                )
            }
        )
    mcp_servers = load_mcp_servers(str(resolved_repo_root / "config/mcp.toml"), compat_json_path)

    tool_registry = ToolRegistry()
    capability_declarations = get_capability_declarations()
    tool_registry.register(
        "time",
        run_time_tool,
        description=render_tool_description(capability_declarations["time"]),
    )
    mcp_client = MCPClient(mcp_servers, env=resolved_env)
    mcp_discovery = discover_mcp_tools(mcp_servers, mcp_client)
    capability_catalog_text = render_capability_catalog(
        capability_declarations,
        mcp_catalog_text=build_mcp_capability_catalog(mcp_servers, mcp_discovery),
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
    default_agent = default_agent.model_copy(
        update={
            "allowed_tools": ["automation", "mcp", "self_improve", "skill", "time"]
        }
    )
    agent_registry.register(default_agent)
    skill_service = SkillService(
        [str(resolved_repo_root / "skills")]
    )
    automation_store = SQLiteAutomationStore(resolved_repo_root / "data" / "automations.sqlite3")
    self_improve_store = SQLiteSelfImproveStore(resolved_repo_root / "data" / "self_improve.sqlite3")
    for job in load_automations(str(resolved_repo_root / "config" / "automations.toml")):
        automation_store.save(job)
    _ensure_self_improve_automation(automation_store)
    model_profile_name, model_profile = resolve_model_profile(models_config, default_agent.model_profile)
    runtime_loop = RuntimeLoop(
        build_llm_client(profile_name=model_profile_name, profile=model_profile, env=resolved_env),
        tool_registry,
        InMemoryRunHistory(),
        self_improve_recorder=SelfImproveRecorder(self_improve_store),
    )
    self_improve_service = SelfImproveService(
        self_improve_store,
        lessons_path=resolved_repo_root / "apps/example_assistant/SYSTEM_LESSONS.md",
        judge=make_default_judge(
            runtime_loop.llm,
            app_id=app_manifest.app_id,
            agent_id=default_agent.agent_id,
        ),
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
        automation_store=automation_store,
        self_improve_store=self_improve_store,
        self_improve_service=self_improve_service,
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
        capability_catalog_text=capability_catalog_text,
        system_prompt=system_prompt,
        runtime_loop=runtime_loop,
        feishu_delivery=feishu_delivery,
        feishu_receipts=feishu_receipts,
        feishu_socket_service=None,  # type: ignore[arg-type]
        lane_manager=ConversationLaneManager(),
    )
    tool_registry.register(
        "skill",
        lambda payload, runtime_state=state: run_skill_tool(payload, runtime_state.skill_service),
        description=render_tool_description(capability_declarations["skill"]),
    )
    tool_registry.register(
        "mcp",
        lambda payload, runtime_state=state: run_mcp_tool(
            payload,
            runtime_state.mcp_servers,
            runtime_state.mcp_client,
            runtime_state.mcp_discovery,
        ),
        description=render_tool_description(capability_declarations["mcp"]),
    )
    tool_registry.register(
        "automation",
        lambda payload, runtime_state=state: run_automation_tool(
            payload,
            runtime_state.automation_store,
            DomainDataAdapter(
                self_improve_store=runtime_state.self_improve_store,
                automation_store=runtime_state.automation_store,
            ),
        ),
        description=render_tool_description(capability_declarations["automation"]),
    )
    tool_registry.register(
        "self_improve",
        lambda payload, runtime_state=state: run_self_improve_tool(
            payload,
            DomainDataAdapter(
                self_improve_store=runtime_state.self_improve_store,
                automation_store=runtime_state.automation_store,
            ),
            runtime_state.self_improve_store,
        ),
        description=render_tool_description(capability_declarations["self_improve"]),
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
        lane_manager=state.lane_manager,
        run_history=state.run_history,
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


def _has_feishu_credentials(env: Mapping[str, str]) -> bool:
    return bool(env.get("FEISHU_APP_ID") and env.get("FEISHU_APP_SECRET"))


def _ensure_self_improve_automation(store: AutomationStore) -> None:
    automation_id = "self_improve_internal"
    try:
        store.get(automation_id)
        return
    except KeyError:
        pass
    store.save(
        AutomationJob(
            automation_id=automation_id,
            name="Internal Self Improve",
            app_id="example_assistant",
            agent_id="assistant",
            prompt_template="Summarize repeated failures and later recoveries into lesson candidates.",
            schedule_kind="daily",
            schedule_expr="03:00",
            timezone="UTC",
            session_target="isolated",
            delivery_channel="http",
            delivery_target="internal",
            skill_id="self_improve",
            enabled=True,
            internal=True,
        )
    )


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
    activated_skills: list[SkillSpec] = []
    turn_agent = routed_agent
    token = push_registration_context(
        {
            "channel_id": envelope.channel_id,
            "conversation_id": envelope.conversation_id,
            "app_id": routed_agent.app_id,
            "agent_id": routed_agent.agent_id,
        }
    )
    try:
        events = state.runtime_loop.run(
            session.session_id,
            envelope.body,
            trace_id=envelope.trace_id,
            system_prompt=state.system_prompt,
            agent=turn_agent,
            config_snapshot_id=state.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=session.bootstrap_manifest_id,
            skill_snapshot_id=skill_runtime.snapshot.skill_snapshot_id,
            session_messages=session.history,
            skill_snapshot=skill_runtime.snapshot,
            skill_heads_text=skill_runtime.skill_heads_text,
            capability_catalog_text=state.capability_catalog_text,
            always_on_skill_text=skill_runtime.always_on_text,
            activated_skill_ids=[item.meta.skill_id for item in activated_skills],
            activated_skill_bodies=[item.body for item in activated_skills],
        )
    finally:
        pop_registration_context(token)
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


def _process_automation_dispatch(
    state: HTTPRuntimeState,
    dispatch: AutomationDispatch,
) -> dict[str, object]:
    session = state.session_store.get_or_create_for_conversation(
        conversation_id=dispatch.session_id,
        config_snapshot_id=state.config_snapshot.config_snapshot_id,
        bootstrap_manifest_id=state.app_manifest.bootstrap_manifest_id,
    )
    routed_agent = state.agent_registry.get(dispatch.agent_id)
    state.session_store.set_active_agent(session.session_id, routed_agent.agent_id)
    from marten_runtime.session.models import SessionMessage

    state.session_store.append_message(session.session_id, SessionMessage.user(dispatch.prompt_template))
    skill_runtime = state.skill_service.build_runtime(
        agent_id=routed_agent.agent_id,
        channel_id=dispatch.delivery_channel,
        env=state.env,
        config={},
    )
    activated_skill: list[SkillSpec] = []
    if dispatch.skill_id:
        activated_skill = select_activated_skills(
            skill_runtime.visible_skills,
            dispatch.prompt_template,
            explicit_skill_ids=[dispatch.skill_id],
        )
        if not activated_skill:
            activated_skill = [state.skill_service.load_skill(dispatch.skill_id)]
    events = state.runtime_loop.run(
        session.session_id,
        dispatch.prompt_template,
        trace_id=dispatch.trace_id,
        system_prompt=state.system_prompt,
        agent=routed_agent,
        config_snapshot_id=state.config_snapshot.config_snapshot_id,
        bootstrap_manifest_id=session.bootstrap_manifest_id,
        skill_snapshot_id=skill_runtime.snapshot.skill_snapshot_id,
        session_messages=session.history,
        skill_snapshot=skill_runtime.snapshot,
        skill_heads_text=skill_runtime.skill_heads_text,
        capability_catalog_text=state.capability_catalog_text,
        always_on_skill_text=skill_runtime.always_on_text,
        activated_skill_ids=[item.meta.skill_id for item in activated_skill],
        activated_skill_bodies=[item.body for item in activated_skill if item.body],
    )
    state.session_store.append_message(session.session_id, SessionMessage.assistant(events[-1].payload["text"]))
    state.session_store.mark_run(session.session_id, events[-1].run_id, events[-1].created_at)
    state.trace_index[dispatch.trace_id] = {
        "run_ids": [events[-1].run_id],
        "job_ids": [dispatch.automation_id],
        "event_ids": [event.event_id for event in events],
        "external_refs": {"langfuse": None, "langsmith": None},
    }
    if dispatch.skill_id == "self_improve":
        state.self_improve_service.process_pending_candidates(agent_id=routed_agent.agent_id)
    _deliver_automation_events(state, dispatch, events)
    return {
        "status": "accepted",
        "automation_id": dispatch.automation_id,
        "scheduled_for": dispatch.scheduled_for,
        "delivery_channel": dispatch.delivery_channel,
        "delivery_target": dispatch.delivery_target,
        "session_id": session.session_id,
        "trace_id": dispatch.trace_id,
        "events": [event.model_dump(mode="json") for event in events],
    }

def build_manual_automation_dispatch(state: HTTPRuntimeState, automation_id: str) -> AutomationDispatch:
    job = state.automation_store.get(automation_id)
    scheduled_for = datetime.now(timezone.utc).astimezone(ZoneInfo(job.timezone)).date().isoformat()
    return build_dispatch(job, scheduled_for=scheduled_for, trace_id=f"trace_auto_{uuid4().hex[:8]}")


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
            )
        )
