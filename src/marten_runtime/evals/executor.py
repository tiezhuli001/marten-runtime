from __future__ import annotations

import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from marten_runtime.config.models_loader import resolve_model_profile
from marten_runtime.evals.case_state import seed_case_state
from marten_runtime.evals.models import EvalCaseObservation, EvalRunSummary, EvalSuiteSpec
from marten_runtime.evals.run_metadata import (
    REPO_ROOT,
    build_eval_run_id,
    config_fingerprint,
    git_state,
)
from marten_runtime.evals.scripted_runtime import configure_scripted_runtime
from marten_runtime.evals.subagent_diagnostics import collect_subagent_diagnostics
from marten_runtime.evals.workspace import copy_repo_scaffold
from marten_runtime.interfaces.http.app import create_app
from marten_runtime.subagents.repo_context import repository_context_env

_copy_repo_scaffold = copy_repo_scaffold
_seed_case_state = seed_case_state
_build_eval_run_id = build_eval_run_id
_config_fingerprint = config_fingerprint
_git_state = git_state


def execute_suite(
    suite: EvalSuiteSpec,
    *,
    mode: str,
    profile_name: str,
    repo_root: str | Path | None = None,
) -> tuple[EvalRunSummary, list[EvalCaseObservation]]:
    source_repo_root = Path(repo_root) if repo_root is not None else REPO_ROOT
    include_mcp = "mcp" in set(suite.required_dependencies or [])
    git_branch, git_sha, git_dirty = git_state(source_repo_root)
    resolved_profile_name, profile = resolve_model_profile(
        _load_models_config(source_repo_root), profile_name
    )
    eval_run_id = build_eval_run_id(suite.suite_id, git_sha)
    summary = EvalRunSummary(
        eval_run_id=eval_run_id,
        suite_id=suite.suite_id,
        git_branch=git_branch,
        git_sha=git_sha,
        git_dirty=git_dirty,
        eval_mode=mode,
        agent_id=suite.cases[0].agent_id if suite.cases else "main",
        profile_name=resolved_profile_name,
        provider_ref=profile.provider_ref,
        model_name=profile.model,
        config_fingerprint=config_fingerprint(source_repo_root),
        suite_fingerprint=suite.suite_fingerprint,
        status="running",
        artifact_root=f"reports/evals/{eval_run_id}",
    )
    observations: list[EvalCaseObservation] = []
    for case in suite.cases:
        if not case.enabled:
            continue
        effective_case = case if case.grader_id is not None else case.model_copy(update={"grader_id": suite.grader_id})
        if mode == "scripted":
            observations.append(
                _execute_case_scripted(
                    effective_case,
                    source_repo_root=source_repo_root,
                    effective_profile_name=resolved_profile_name,
                    provider_name=profile.provider_ref,
                    model_name=profile.model,
                    include_mcp=False,
                )
            )
            continue
        observations.append(
            _execute_case_live(
                effective_case,
                source_repo_root=source_repo_root,
                include_mcp=include_mcp,
                profile_name=resolved_profile_name,
            )
        )
    return summary, observations


def _execute_case_scripted(
    case,
    *,
    source_repo_root: Path,
    effective_profile_name: str,
    provider_name: str,
    model_name: str,
    include_mcp: bool,
) -> EvalCaseObservation:
    with TemporaryDirectory(prefix=f"marten_eval_{case.case_id}_") as tmpdir:
        workspace_root = Path(tmpdir)
        copy_repo_scaffold(
            source_repo_root,
            workspace_root,
            include_mcp=include_mcp,
        )
        app = create_app(
            repo_root=workspace_root,
            env={
                "OPENAI_API_KEY": "test-key",
                "MINIMAX_API_KEY": "test-key",
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
                **repository_context_env(source_repo_root),
            },
            load_env_file=False,
        )
        runtime = app.state.runtime
        runtime.channels_config = runtime.channels_config.model_copy(
            update={
                "feishu": runtime.channels_config.feishu.model_copy(
                    update={"enabled": False, "auto_start": False}
                )
            }
        )
        _override_eval_runtime_profiles(
            runtime=runtime,
            agent_id=case.agent_id,
            profile_name=effective_profile_name,
        )
        case_context = seed_case_state(
            runtime,
            case,
            effective_profile_name=effective_profile_name,
        )
        _override_eval_subagent_timeout(
            runtime=runtime,
            case=case,
            mode="scripted",
        )
        configure_scripted_runtime(
            runtime,
            case,
            provider_name=provider_name,
            model_name=model_name,
            context=case_context,
        )
        return _run_case_via_http(app, case)


def _execute_case_live(
    case,
    *,
    source_repo_root: Path,
    include_mcp: bool,
    profile_name: str,
) -> EvalCaseObservation:
    with TemporaryDirectory(prefix=f"marten_eval_live_{case.case_id}_") as tmpdir:
        workspace_root = Path(tmpdir)
        copy_repo_scaffold(
            source_repo_root,
            workspace_root,
            include_mcp=_should_include_live_mcp_scaffold(
                source_repo_root,
                include_mcp=include_mcp,
            ),
        )
        app = create_app(
            repo_root=workspace_root,
            env={
                **dict(os.environ),
                **repository_context_env(source_repo_root),
            },
            load_env_file=False,
        )
        runtime = app.state.runtime
        _override_eval_runtime_profiles(
            runtime=runtime,
            agent_id=case.agent_id,
            profile_name=profile_name,
        )
        _override_eval_subagent_timeout(
            runtime=runtime,
            case=case,
            mode="live",
        )
        seed_case_state(runtime, case, effective_profile_name=profile_name)
        observation = _run_case_via_http(app, case)
        return _retry_live_subagent_case_after_timeout(
            app,
            case=case,
            observation=observation,
        )


def _retry_live_subagent_case_after_timeout(
    app,
    *,
    case,
    observation: EvalCaseObservation,
) -> EvalCaseObservation:  # noqa: ANN001
    if not _is_retryable_live_subagent_timeout(case, observation):
        return observation
    return _run_case_via_http(app, case)


def _is_retryable_live_subagent_timeout(case, observation: EvalCaseObservation) -> bool:  # noqa: ANN001
    grader_id = str(getattr(case, "grader_id", None) or getattr(case, "family", None) or "").strip()
    if grader_id != "subagent_task_progress":
        return False
    subagent = (observation.diagnostics_json or {}).get("subagent") or {}
    if not isinstance(subagent, dict):
        return False
    tasks = subagent.get("tasks") or []
    if not isinstance(tasks, list):
        return False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("status") or "") != "timed_out":
            continue
        child_run = task.get("child_run") or {}
        if isinstance(child_run, dict) and _run_has_retryable_provider_timeout(child_run):
            return True
    return False


def _run_has_retryable_provider_timeout(run_diag: dict[str, object]) -> bool:
    if str(run_diag.get("error_code") or "") != "PROVIDER_TIMEOUT":
        return False
    for call in list(run_diag.get("provider_calls") or []):
        if not isinstance(call, dict):
            continue
        if str(call.get("final_error_code") or "") != "PROVIDER_TIMEOUT":
            continue
        for attempt in list(call.get("attempts") or []):
            if not isinstance(attempt, dict):
                continue
            if bool(attempt.get("retryable")):
                return True
    return False

def _override_eval_runtime_profiles(
    *,
    runtime,
    agent_id: str,
    profile_name: str,
) -> None:  # noqa: ANN001
    requested_agent = runtime.agent_registry.get(agent_id)
    requested_override = requested_agent.model_copy(update={"model_profile": profile_name})
    runtime.agent_registry.register(requested_override)
    default_agent = runtime.default_agent
    if default_agent.agent_id == agent_id:
        runtime.default_agent = requested_override
        return
    default_override = default_agent.model_copy(update={"model_profile": profile_name})
    runtime.agent_registry.register(default_override)
    runtime.default_agent = default_override


def _override_eval_subagent_timeout(
    *,
    runtime,
    case,
    mode: str,
) -> None:  # noqa: ANN001
    grader_id = str(getattr(case, "grader_id", None) or "").strip()
    if grader_id != "subagent_task_progress":
        return
    timeout_ms = int((getattr(case, "grader_case", {}) or {}).get("timeout_ms") or 0)
    if timeout_ms <= 0:
        return
    if mode == "scripted":
        timeout_seconds = 1
    else:
        timeout_seconds = max(1, math.ceil(timeout_ms / 1000))
    current_timeout = int(getattr(runtime.subagent_service, "subagent_timeout_seconds", 0) or 0)
    runtime.subagent_service.subagent_timeout_seconds = min(
        current_timeout if current_timeout > 0 else timeout_seconds,
        timeout_seconds,
    )


def _run_case_via_http(app, case) -> EvalCaseObservation:  # noqa: ANN001
    conversation_id = f"eval-{case.case_id}"
    user_id = "eval-user"
    final_text = ""
    final_run_id = None
    final_trace_id = None
    final_langfuse_url = None
    combined_tool_calls: list[dict[str, object]] = []
    llm_request_count = 0
    tool_calls_count = 0
    duration_ms = 0
    final_diagnostics: dict[str, object] = {}
    turn_payloads: list[dict[str, object]] = []
    with TestClient(app) as client:
        for index, turn in enumerate(case.turns, start=1):
            response = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "message_id": f"{case.case_id}-{index}",
                    "body": turn.content,
                    "requested_agent_id": case.agent_id,
                },
            )
            if response.status_code != 200:
                return EvalCaseObservation(
                    case_id=case.case_id,
                    family=case.family,
                    final_text="",
                    diagnostics_json={"http_status": response.status_code, "body": response.text},
                    blocked_reason=f"http_status_{response.status_code}",
                )
            payload = response.json()
            final_event = payload["events"][-1]
            final_text = str(final_event.get("payload", {}).get("text") or "")
            final_run_id = str(final_event.get("run_id") or "")
            final_trace_id = str(payload.get("trace_id") or final_event.get("trace_id") or "")
            run_diag = client.get(f"/diagnostics/run/{final_run_id}").json()
            trace_diag = client.get(f"/diagnostics/trace/{final_trace_id}").json()
            llm_request_count += int(run_diag.get("llm_request_count") or 0)
            turn_tool_calls = list(run_diag.get("tool_calls") or [])
            combined_tool_calls.extend(turn_tool_calls)
            tool_calls_count += len(turn_tool_calls)
            duration_ms += int((run_diag.get("timings") or {}).get("total_ms") or 0)
            final_langfuse_url = str(
                ((run_diag.get("external_observability") or {}).get("langfuse_url"))
                or ((trace_diag.get("external_refs") or {}).get("langfuse_url"))
                or ""
            ) or None
            turn_record = {
                "message": turn.content,
                "response": payload,
                "run": run_diag,
                "trace": trace_diag,
            }
            turn_payloads.append(turn_record)
            final_diagnostics = {
                "provider_ref": run_diag.get("provider_ref"),
                "final_provider_ref": run_diag.get("final_provider_ref"),
                "compaction": run_diag.get("compaction") or {},
                "trace": trace_diag,
                "turns": list(turn_payloads),
                "active_session_id": payload.get("active_session_id"),
            }
            if _should_collect_subagent_diagnostics(case, index):
                collect_subagent_diagnostics(
                    client,
                    case=case,
                    active_session_id=str(payload.get("active_session_id") or ""),
                    parent_run_ids=_parent_run_ids(turn_payloads),
                )
        return EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text=final_text,
            llm_request_count=llm_request_count,
            tool_calls_count=tool_calls_count,
            duration_ms=duration_ms,
            run_id=final_run_id,
            trace_id=final_trace_id,
            langfuse_url=final_langfuse_url,
            tool_calls=combined_tool_calls,
            diagnostics_json=_finalize_case_diagnostics(
                client,
                case=case,
                diagnostics=final_diagnostics,
                parent_run_ids=_parent_run_ids(turn_payloads),
            ),
        )


def _should_collect_subagent_diagnostics(case, turn_index: int) -> bool:  # noqa: ANN001
    return (
        str(case.grader_id or "").strip() == "subagent_task_progress"
        and turn_index < len(case.turns)
        and bool(case.grader_case.get("await_child_completion"))
    )


def _parent_run_ids(turn_payloads: list[dict[str, object]]) -> list[str]:
    return [
        str((item.get("run") or {}).get("run_id") or "")
        for item in turn_payloads
        if isinstance(item, dict)
    ]


def _should_include_live_mcp_scaffold(
    source_repo_root: Path,
    *,
    include_mcp: bool,
) -> bool:
    del source_repo_root
    return include_mcp


def _finalize_case_diagnostics(
    client: TestClient,
    *,
    case,
    diagnostics: dict[str, object],
    parent_run_ids: list[str],
) -> dict[str, object]:  # noqa: ANN001
    if str(case.grader_id or "").strip() != "subagent_task_progress":
        return diagnostics
    active_session_id = str(diagnostics.get("active_session_id") or "").strip()
    diagnostics["subagent"] = collect_subagent_diagnostics(
        client,
        case=case,
        active_session_id=active_session_id,
        parent_run_ids=parent_run_ids,
    )
    return diagnostics


def _load_models_config(repo_root: Path):
    from marten_runtime.config.models_loader import load_models_config

    return load_models_config(str(repo_root / "config/models.toml"))
