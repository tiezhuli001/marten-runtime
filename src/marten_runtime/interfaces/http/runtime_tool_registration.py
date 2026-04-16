from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.runtime.capabilities import get_parameters_schema, render_tool_description
from marten_runtime.tools.builtins.automation_tool import run_automation_tool
from marten_runtime.tools.builtins.mcp_tool import run_mcp_tool
from marten_runtime.tools.builtins.runtime_tool import run_runtime_tool
from marten_runtime.tools.builtins.self_improve_tool import run_self_improve_tool
from marten_runtime.tools.builtins.spawn_subagent_tool import run_spawn_subagent_tool
from marten_runtime.tools.builtins.cancel_subagent_tool import run_cancel_subagent_tool
from marten_runtime.tools.builtins.skill_tool import run_skill_tool
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from marten_runtime.interfaces.http.bootstrap_runtime import HTTPRuntimeState


def register_builtin_time_tool(
    tool_registry: ToolRegistry,
    capability_declarations: Mapping[str, object],
) -> None:
    tool_registry.register(
        "time",
        run_time_tool,
        description=render_tool_description(capability_declarations["time"]),
        parameters_schema=get_parameters_schema(capability_declarations["time"]),
    )


def register_family_tools(
    state: HTTPRuntimeState,
    capability_declarations: Mapping[str, object],
) -> None:
    def adapter_factory(runtime_state: HTTPRuntimeState) -> DomainDataAdapter:
        return DomainDataAdapter(
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
        lambda payload, runtime_state=state, *, tool_context=None: run_mcp_tool(
            payload,
            runtime_state.mcp_servers,
            runtime_state.mcp_client,
            runtime_state.mcp_discovery,
            tool_context=tool_context,
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
            latest_checkpoint_available=runtime_latest_checkpoint_available(
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
            repo_root=runtime_state.repo_root,
        ),
        description=render_tool_description(capability_declarations["self_improve"]),
        parameters_schema=get_parameters_schema(
            capability_declarations["self_improve"]
        ),
    )
    state.tool_registry.register(
        "spawn_subagent",
        lambda payload, runtime_state=state, *, tool_context=None: run_spawn_subagent_tool(
            payload,
            subagent_service=runtime_state.subagent_service,
            session_store=runtime_state.session_store,
            tool_context=tool_context,
        ),
        description="Spawn a background subagent task with isolated child session execution.",
        parameters_schema={
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "label": {"type": "string"},
                "tool_profile": {"type": "string"},
                "context_mode": {"type": "string"},
                "notify_on_finish": {"type": "boolean"},
                "agent_id": {"type": "string"}
            },
            "required": ["task"],
        },
    )
    state.tool_registry.register(
        "cancel_subagent",
        lambda payload, *, tool_context=None, runtime_state=state: run_cancel_subagent_tool(
            payload,
            subagent_service=runtime_state.subagent_service,
            tool_context=tool_context,
        ),
        description="Cancel a background subagent task by task id.",
        parameters_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"}
            },
            "required": ["task_id"],
        },
    )


def runtime_latest_checkpoint_available(
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
