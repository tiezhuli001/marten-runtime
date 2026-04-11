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
from marten_runtime.apps.runtime_defaults import (
    DEFAULT_AGENT_ID,
    DEFAULT_APP_ID,
    default_app_manifest_path,
    default_lessons_path,
)
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
from marten_runtime.mcp.client import MCPClient
from marten_runtime.mcp.discovery import discover_mcp_tools
from marten_runtime.mcp.loader import load_mcp_servers
from marten_runtime.mcp.models import MCPServerSpec
from marten_runtime.interfaces.http.feishu_runtime_services import (
    build_feishu_delivery_client,
    build_feishu_websocket_service,
)
from marten_runtime.interfaces.http.runtime_tool_registration import (
    register_builtin_time_tool,
    register_family_tools,
)
from marten_runtime.runtime.capabilities import (
    get_capability_declarations,
    render_capability_catalog,
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
from marten_runtime.tools.builtins.mcp_tool import build_mcp_capability_catalog
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
    register_builtin_time_tool(tool_registry, capability_declarations)
    mcp_client = MCPClient(mcp_servers, env=resolved_env)
    mcp_discovery = discover_mcp_tools(mcp_servers, mcp_client)
    capability_catalog_text = render_capability_catalog(
        capability_declarations,
        mcp_catalog_text=build_mcp_capability_catalog(mcp_servers, mcp_discovery),
    )
    default_app_manifest = load_app_manifest(
        str(default_app_manifest_path(resolved_repo_root))
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
        lessons_path=default_lessons_path(resolved_repo_root),
        judge=make_default_judge(
            runtime_loop.llm,
            app_id=app_manifest.app_id,
            agent_id=default_agent.agent_id,
        ),
    )
    feishu_delivery = build_feishu_delivery_client(
        env=resolved_env,
        channels_config=channels_config,
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
    register_family_tools(state, capability_declarations)
    from marten_runtime.interfaces.http.bootstrap_handlers import (
        _process_inbound_envelope,
    )

    state.feishu_socket_service = build_feishu_websocket_service(
        env=resolved_env,
        channels_config=channels_config,
        receipt_store=feishu_receipts,
        runtime_handler=lambda envelope: _process_inbound_envelope(state, envelope),
        delivery_client=feishu_delivery,
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
            app_id=DEFAULT_APP_ID,
            agent_id=DEFAULT_AGENT_ID,
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
