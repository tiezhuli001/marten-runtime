from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from marten_runtime.agents.bindings import AgentBindingRegistry
from marten_runtime.agents.registry import AgentRegistry
from marten_runtime.agents.router import AgentRouter
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.apps.bootstrap_prompt import load_bootstrap_prompt
from marten_runtime.apps.manifest import AppManifest, load_app_manifest
from marten_runtime.automation.models import AutomationJob
from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.automation.store import AutomationStore
from marten_runtime.channels.delivery_retry import DeliveryRetryPolicy
from marten_runtime.channels.feishu.delivery import FeishuDeliveryClient
from marten_runtime.channels.feishu.service import FeishuWebsocketService
from marten_runtime.channels.receipts import InMemoryReceiptStore
from marten_runtime.config.agents_loader import load_agent_specs
from marten_runtime.config.automations_loader import load_automations
from marten_runtime.config.bindings_loader import load_agent_bindings
from marten_runtime.config.channels_loader import ChannelsConfig, load_channels_config
from marten_runtime.config.env_loader import EnvLoadResult, load_repo_env
from marten_runtime.config.models import ConfigSnapshot
from marten_runtime.config.models_loader import (
    ModelsConfig,
    load_models_config,
    resolve_model_profile,
)
from marten_runtime.config.platform_loader import PlatformConfig, load_platform_config
from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.mcp.client import MCPClient
from marten_runtime.mcp.discovery import discover_mcp_tools
from marten_runtime.mcp.loader import load_mcp_servers
from marten_runtime.mcp.models import MCPServerSpec
from marten_runtime.runtime.capabilities import (
    get_capability_declarations,
    get_parameters_schema,
    render_capability_catalog,
    render_tool_description,
)
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.lanes import ConversationLaneManager
from marten_runtime.runtime.llm_client import build_llm_client
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.self_improve.service import SelfImproveService, make_default_judge
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.session.store import SessionStore
from marten_runtime.skills.service import SkillService
from marten_runtime.tools.builtins.automation_tool import run_automation_tool
from marten_runtime.tools.builtins.mcp_tool import (
    build_mcp_capability_catalog,
    run_mcp_tool,
)
from marten_runtime.tools.builtins.runtime_tool import run_runtime_tool
from marten_runtime.tools.builtins.self_improve_tool import run_self_improve_tool
from marten_runtime.tools.builtins.skill_tool import run_skill_tool
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.registry import ToolRegistry

TraceIndex = dict[str, dict[str, list[str] | dict[str, str | None]]]


@dataclass
class AppRuntimeAssets:
    manifest: AppManifest
    system_prompt: str


class CachedLLMClientFactory:
    def __init__(
        self,
        *,
        models_config: ModelsConfig,
        env: Mapping[str, str],
        primary_profile_name: str | None = None,
    ) -> None:
        self.models_config = models_config
        self.env = dict(env)
        self.primary_profile_name = primary_profile_name
        self._cache: dict[str, object] = {}
        self._fallback_client: object | None = None

    def cache_client(self, profile_name: str, client: object) -> None:
        self._cache[profile_name] = client

    def set_fallback_client(self, client: object) -> None:
        self._fallback_client = client

    def get(
        self, profile_name: str | None, *, default_client: object | None = None
    ) -> object:
        resolved_name, profile = resolve_model_profile(self.models_config, profile_name)
        if (
            default_client is not None
            and self.primary_profile_name is not None
            and resolved_name == self.primary_profile_name
        ):
            return default_client
        cached = self._cache.get(resolved_name)
        if cached is not None:
            return cached
        if self._fallback_client is not None:
            return self._fallback_client
        client = build_llm_client(
            profile_name=resolved_name, profile=profile, env=self.env
        )
        self._cache[resolved_name] = client
        return client


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
    app_runtimes: dict[str, AppRuntimeAssets]
    llm_client_factory: CachedLLMClientFactory
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
    resolved_repo_root = (
        Path(repo_root) if repo_root is not None else default_repo_root()
    )
    env_load_result, resolved_env = _resolve_environment(
        resolved_repo_root,
        env=env,
        load_env_file=load_env_file,
    )
    platform_config, models_config, channels_config, mcp_servers = _load_runtime_config(
        resolved_repo_root,
        env=resolved_env,
        use_compat_json=use_compat_json,
    )
    capability_declarations = get_capability_declarations()
    tool_registry = ToolRegistry()
    tool_registry.register(
        "time",
        run_time_tool,
        description=render_tool_description(capability_declarations["time"]),
        parameters_schema=get_parameters_schema(capability_declarations["time"]),
    )
    mcp_client = MCPClient(mcp_servers, env=resolved_env)
    mcp_discovery = discover_mcp_tools(mcp_servers, mcp_client)
    capability_catalog_text = render_capability_catalog(
        capability_declarations,
        mcp_catalog_text=build_mcp_capability_catalog(mcp_servers, mcp_discovery),
    )
    default_app_manifest = load_app_manifest(
        str(resolved_repo_root / "apps/example_assistant/app.toml")
    )
    agent_specs = load_agent_specs(str(resolved_repo_root / "config/agents.toml"))
    app_runtimes = _load_app_runtimes(
        repo_root=resolved_repo_root,
        app_ids={spec.app_id for spec in agent_specs if spec.enabled}
        | {default_app_manifest.app_id},
    )
    agent_registry, binding_registry, agent_router, default_agent = (
        _build_agent_runtime(
            repo_root=resolved_repo_root,
            app_manifest=default_app_manifest,
            agent_specs=agent_specs,
        )
    )
    app_manifest = app_runtimes[default_agent.app_id].manifest
    system_prompt = app_runtimes[default_agent.app_id].system_prompt
    skill_service = SkillService([str(resolved_repo_root / "skills")])
    automation_store, self_improve_store = _build_stateful_stores(resolved_repo_root)
    default_profile_name, default_profile = resolve_model_profile(
        models_config, default_agent.model_profile
    )
    llm_client_factory = CachedLLMClientFactory(
        models_config=models_config,
        env=resolved_env,
        primary_profile_name=default_profile_name,
    )
    default_llm = build_llm_client(
        profile_name=default_profile_name, profile=default_profile, env=resolved_env
    )
    llm_client_factory.cache_client(default_profile_name, default_llm)
    runtime_loop = RuntimeLoop(
        default_llm,
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
        app_runtimes=app_runtimes,
        llm_client_factory=llm_client_factory,
    )
    _register_family_tools(state, capability_declarations)
    from marten_runtime.interfaces.http.bootstrap_handlers import (
        _process_inbound_envelope,
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


def _resolve_environment(
    repo_root: Path,
    *,
    env: Mapping[str, str] | None,
    load_env_file: bool,
) -> tuple[EnvLoadResult, dict[str, str]]:
    env_load_result = EnvLoadResult(loaded=False, path=str(repo_root / ".env"))
    if env is None:
        if load_env_file:
            env_load_result = load_repo_env(repo_root)
        resolved_env = dict(os.environ)
    else:
        resolved_env = dict(env)
    return env_load_result, resolved_env


def _load_runtime_config(
    repo_root: Path,
    *,
    env: dict[str, str],
    use_compat_json: bool,
) -> tuple[PlatformConfig, ModelsConfig, ChannelsConfig, list[MCPServerSpec]]:
    compat_json_path = str(repo_root / "mcps.json") if use_compat_json else None
    platform_config = load_platform_config(
        str(repo_root / "config/platform.toml"), env=env
    )
    models_config = load_models_config(str(repo_root / "config/models.toml"))
    channels_config = load_channels_config(str(repo_root / "config/channels.toml"))
    if not _has_feishu_credentials(env):
        channels_config = channels_config.model_copy(
            update={
                "feishu": channels_config.feishu.model_copy(
                    update={"enabled": False, "auto_start": False}
                )
            }
        )
    mcp_servers = load_mcp_servers(str(repo_root / "config/mcp.toml"), compat_json_path)
    return platform_config, models_config, channels_config, mcp_servers


def _build_agent_runtime(
    *,
    repo_root: Path,
    app_manifest: AppManifest,
    agent_specs: list[AgentSpec],
) -> tuple[AgentRegistry, AgentBindingRegistry, AgentRouter, AgentSpec]:
    agent_registry = AgentRegistry()
    for spec in agent_specs:
        if not spec.enabled:
            continue
        agent_registry.register(spec)
    binding_registry = AgentBindingRegistry(
        load_agent_bindings(str(repo_root / "config/bindings.toml"))
    )
    agent_router = AgentRouter(
        agent_registry,
        default_agent_id=app_manifest.default_agent,
        bindings=binding_registry,
    )
    default_agent = agent_registry.get(app_manifest.default_agent)
    return agent_registry, binding_registry, agent_router, default_agent


def _load_app_runtimes(
    *,
    repo_root: Path,
    app_ids: set[str],
) -> dict[str, AppRuntimeAssets]:
    runtimes: dict[str, AppRuntimeAssets] = {}
    for app_id in sorted(app_ids):
        manifest = load_app_manifest(str(repo_root / "apps" / app_id / "app.toml"))
        runtimes[app_id] = AppRuntimeAssets(
            manifest=manifest,
            system_prompt=load_bootstrap_prompt(repo_root=repo_root, manifest=manifest),
        )
    return runtimes


def _build_stateful_stores(
    repo_root: Path,
) -> tuple[SQLiteAutomationStore, SQLiteSelfImproveStore]:
    automation_store = SQLiteAutomationStore(repo_root / "data" / "automations.sqlite3")
    self_improve_store = SQLiteSelfImproveStore(
        repo_root / "data" / "self_improve.sqlite3"
    )
    for job in load_automations(str(repo_root / "config" / "automations.toml")):
        automation_store.save(job)
    _ensure_self_improve_automation(automation_store)
    return automation_store, self_improve_store


def _register_family_tools(
    state: HTTPRuntimeState,
    capability_declarations: dict[str, object],
) -> None:
    adapter_factory = lambda runtime_state: DomainDataAdapter(
        self_improve_store=runtime_state.self_improve_store,
        automation_store=runtime_state.automation_store,
    )
    state.tool_registry.register(
        "skill",
        lambda payload, runtime_state=state: run_skill_tool(
            payload, runtime_state.skill_service
        ),
        description=render_tool_description(capability_declarations["skill"]),
        parameters_schema=get_parameters_schema(capability_declarations["skill"]),
    )
    state.tool_registry.register(
        "mcp",
        lambda payload, runtime_state=state: run_mcp_tool(
            payload,
            runtime_state.mcp_servers,
            runtime_state.mcp_client,
            runtime_state.mcp_discovery,
        ),
        description=render_tool_description(capability_declarations["mcp"]),
        parameters_schema=get_parameters_schema(capability_declarations["mcp"]),
    )
    state.tool_registry.register(
        "automation",
        lambda payload, runtime_state=state: run_automation_tool(
            payload,
            runtime_state.automation_store,
            adapter_factory(runtime_state),
        ),
        description=render_tool_description(capability_declarations["automation"]),
        parameters_schema=get_parameters_schema(capability_declarations["automation"]),
    )
    state.tool_registry.register(
        "runtime",
        lambda payload, runtime_state=state, *, tool_context=None: run_runtime_tool(
            payload,
            tool_context=tool_context,
            runtime_loop=runtime_state.runtime_loop,
            run_history=runtime_state.run_history,
            latest_checkpoint_available=_runtime_latest_checkpoint_available(
                runtime_state, tool_context
            ),
        ),
        description=render_tool_description(capability_declarations["runtime"]),
        parameters_schema=get_parameters_schema(capability_declarations["runtime"]),
    )
    state.tool_registry.register(
        "self_improve",
        lambda payload, runtime_state=state: run_self_improve_tool(
            payload,
            adapter_factory(runtime_state),
            runtime_state.self_improve_store,
        ),
        description=render_tool_description(capability_declarations["self_improve"]),
        parameters_schema=get_parameters_schema(
            capability_declarations["self_improve"]
        ),
    )
    state.tool_registry.register(
        "mcp",
        lambda payload, runtime_state=state: run_mcp_tool(
            payload,
            runtime_state.mcp_servers,
            runtime_state.mcp_client,
            runtime_state.mcp_discovery,
        ),
        description=render_tool_description(capability_declarations["mcp"]),
    )
    state.tool_registry.register(
        "automation",
        lambda payload, runtime_state=state: run_automation_tool(
            payload,
            runtime_state.automation_store,
            adapter_factory(runtime_state),
        ),
        description=render_tool_description(capability_declarations["automation"]),
    )
    state.tool_registry.register(
        "runtime",
        lambda payload, runtime_state=state, *, tool_context=None: run_runtime_tool(
            payload,
            tool_context=tool_context,
            runtime_loop=runtime_state.runtime_loop,
            run_history=runtime_state.run_history,
            latest_checkpoint_available=_runtime_latest_checkpoint_available(
                runtime_state, tool_context
            ),
        ),
        description=render_tool_description(capability_declarations["runtime"]),
    )
    state.tool_registry.register(
        "self_improve",
        lambda payload, runtime_state=state: run_self_improve_tool(
            payload,
            adapter_factory(runtime_state),
            runtime_state.self_improve_store,
        ),
        description=render_tool_description(capability_declarations["self_improve"]),
    )


def _runtime_latest_checkpoint_available(
    runtime_state: HTTPRuntimeState,
    tool_context: dict | None,
) -> bool:
    session_id = str((tool_context or {}).get("session_id") or "").strip()
    if not session_id:
        return False
    try:
        return (
            runtime_state.session_store.get(session_id).latest_compacted_context
            is not None
        )
    except KeyError:
        return False


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
