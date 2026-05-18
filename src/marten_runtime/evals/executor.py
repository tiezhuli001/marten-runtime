from __future__ import annotations

import math
import multiprocessing
import os
import queue
import time
import traceback
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
    case_timeout_seconds: float | None = None,
    progress_printer=None,
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
    live_case_timeout_setting = (
        _resolve_live_case_timeout_setting(case_timeout_seconds)
        if mode == "live"
        else _LiveCaseTimeoutSetting(disabled=False, timeout_seconds=None)
    )
    for case in suite.cases:
        if not case.enabled:
            continue
        effective_case = case if case.grader_id is not None else case.model_copy(update={"grader_id": suite.grader_id})
        _emit_progress(progress_printer, f"case_start case_id={effective_case.case_id} mode={mode}")
        case_started_at = time.perf_counter()
        if mode == "scripted":
            observation = _execute_case_scripted(
                effective_case,
                source_repo_root=source_repo_root,
                effective_profile_name=resolved_profile_name,
                provider_name=profile.provider_ref,
                model_name=profile.model,
                include_mcp=False,
            )
            observations.append(observation)
            _emit_case_done(progress_printer, effective_case, observation, case_started_at)
            continue
        effective_case_timeout_seconds = _effective_live_case_timeout_seconds(
            effective_case,
            live_case_timeout_setting,
        )
        try:
            observation = _execute_case_live_with_timeout(
                effective_case,
                source_repo_root=source_repo_root,
                include_mcp=include_mcp,
                profile_name=resolved_profile_name,
                case_timeout_seconds=effective_case_timeout_seconds,
            )
        except TimeoutError as exc:
            observation = _build_blocked_case_observation(
                effective_case,
                started_at=case_started_at,
                blocked_reason=str(exc),
                error_code="EVAL_CASE_TIMEOUT",
                case_timeout_seconds=effective_case_timeout_seconds,
                exception=exc,
            )
        except Exception as exc:  # noqa: BLE001
            blocked_reason = f"eval case failed: {effective_case.case_id}: {type(exc).__name__}: {exc}"
            observation = _build_blocked_case_observation(
                effective_case,
                started_at=case_started_at,
                blocked_reason=blocked_reason,
                error_code="EVAL_CASE_ERROR",
                case_timeout_seconds=effective_case_timeout_seconds,
                exception=exc,
            )
        observations.append(observation)
        _emit_case_done(progress_printer, effective_case, observation, case_started_at)
    return summary, observations


def _build_blocked_case_observation(
    case,
    *,
    started_at: float,
    blocked_reason: str,
    error_code: str,
    case_timeout_seconds: float | None,
    exception: BaseException,
) -> EvalCaseObservation:  # noqa: ANN001
    return EvalCaseObservation(
        case_id=case.case_id,
        family=case.family,
        duration_ms=int((time.perf_counter() - started_at) * 1000),
        diagnostics_json={
            "blocked_reason": blocked_reason,
            "case_timeout_seconds": case_timeout_seconds,
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            "traceback": traceback.format_exception(
                type(exception),
                exception,
                exception.__traceback__,
                limit=8,
            ),
        },
        blocked_reason=blocked_reason,
        error_code=error_code,
    )


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


def _execute_case_live_with_timeout(
    case,
    *,
    source_repo_root: Path,
    include_mcp: bool,
    profile_name: str,
    case_timeout_seconds: float | None = None,
) -> EvalCaseObservation:
    if case_timeout_seconds is None:
        return _execute_case_live(
            case,
            source_repo_root=source_repo_root,
            include_mcp=include_mcp,
            profile_name=profile_name,
        )
    ctx = multiprocessing.get_context("fork")
    result_queue = ctx.Queue(maxsize=1)
    process = ctx.Process(
        target=_execute_case_live_child,
        kwargs={
            "result_queue": result_queue,
            "case": case,
            "source_repo_root": source_repo_root,
            "include_mcp": include_mcp,
            "profile_name": profile_name,
            "case_timeout_seconds": case_timeout_seconds,
        },
        daemon=True,
    )
    process.start()
    deadline = time.monotonic() + float(case_timeout_seconds)
    while True:
        try:
            kind, payload = result_queue.get_nowait()
            _stop_process_after_result(process)
            if kind == "ok":
                return EvalCaseObservation.model_validate(payload)
            raise RuntimeError(str(payload))
        except queue.Empty:
            pass
        if not process.is_alive():
            break
        if time.monotonic() >= deadline:
            break
        process.join(timeout=min(0.05, max(0.0, deadline - time.monotonic())))
    if process.is_alive():
        process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        raise TimeoutError(f"eval case timed out: {case.case_id}")
    try:
        kind, payload = result_queue.get(timeout=2)
    except queue.Empty as exc:
        raise RuntimeError(f"eval case exited without result: {case.case_id}: exit_code={process.exitcode}") from exc
    if kind == "ok":
        return EvalCaseObservation.model_validate(payload)
    raise RuntimeError(str(payload))


def _stop_process_after_result(process) -> None:  # noqa: ANN001
    process.join(timeout=2)
    if not process.is_alive():
        return
    process.terminate()
    process.join(timeout=2)
    if process.is_alive():
        process.kill()
        process.join(timeout=2)


def _execute_case_live_child(
    *,
    result_queue,
    case,
    source_repo_root: Path,
    include_mcp: bool,
    profile_name: str,
    case_timeout_seconds: float | None,
) -> None:  # noqa: ANN001
    try:
        observation = _execute_case_live(
            case,
            source_repo_root=source_repo_root,
            include_mcp=include_mcp,
            profile_name=profile_name,
            case_timeout_seconds=case_timeout_seconds,
        )
        result_queue.put(("ok", observation.model_dump(mode="json")))
    except BaseException as exc:  # noqa: BLE001
        result_queue.put(
            (
                "error",
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exception(
                        type(exc),
                        exc,
                        exc.__traceback__,
                        limit=8,
                    ),
                },
            )
        )


def _execute_case_live(
    case,
    *,
    source_repo_root: Path,
    include_mcp: bool,
    profile_name: str,
    case_timeout_seconds: float | None = None,
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
        deadline_monotonic = (
            time.monotonic() + float(case_timeout_seconds)
            if case_timeout_seconds is not None
            else None
        )
        observation = (
            _run_case_via_http(app, case, deadline_monotonic=deadline_monotonic)
            if deadline_monotonic is not None
            else _run_case_via_http(app, case)
        )
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
    if not _case_requires_subagent_diagnostics(case):
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
    if str(getattr(case, "grader_id", None) or "").strip() != "subagent_task_progress":
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


def _run_case_via_http(app, case, *, deadline_monotonic: float | None = None) -> EvalCaseObservation:  # noqa: ANN001
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
            _raise_if_case_deadline_expired(deadline_monotonic, case.case_id)
            response = client.post(
                "/messages",
                json={
                    "channel_id": case.channel_id,
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
            _raise_if_case_deadline_expired(deadline_monotonic, case.case_id)
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


class _LiveCaseTimeoutSetting:
    def __init__(self, *, disabled: bool, timeout_seconds: float | None) -> None:
        self.disabled = disabled
        self.timeout_seconds = timeout_seconds


def _resolve_live_case_timeout_setting(value: float | None) -> _LiveCaseTimeoutSetting:
    if value is None:
        return _LiveCaseTimeoutSetting(disabled=False, timeout_seconds=None)
    if float(value) <= 0:
        return _LiveCaseTimeoutSetting(disabled=True, timeout_seconds=None)
    return _LiveCaseTimeoutSetting(disabled=False, timeout_seconds=float(value))


def _effective_live_case_timeout_seconds(case, setting: _LiveCaseTimeoutSetting) -> float | None:  # noqa: ANN001
    if setting.disabled:
        return None
    grader_case = getattr(case, "grader_case", {}) or {}
    timeout_ms = int(grader_case.get("timeout_ms") or 0)
    case_timeout_seconds = (timeout_ms / 1000.0) if timeout_ms > 0 else None
    global_timeout_seconds = setting.timeout_seconds
    if global_timeout_seconds is None:
        return case_timeout_seconds
    if case_timeout_seconds is None:
        return global_timeout_seconds
    return max(float(global_timeout_seconds), float(case_timeout_seconds))


def _emit_progress(progress_printer, message: str) -> None:  # noqa: ANN001
    if progress_printer is None:
        return
    progress_printer(message)


def _emit_case_done(progress_printer, case, observation: EvalCaseObservation, started_at: float) -> None:  # noqa: ANN001
    elapsed = time.perf_counter() - started_at
    status = "blocked" if observation.blocked_reason else "done"
    _emit_progress(
        progress_printer,
        f"case_done case_id={case.case_id} status={status} elapsed_seconds={elapsed:.2f}",
    )


def _raise_if_case_deadline_expired(deadline_monotonic: float | None, case_id: str) -> None:
    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
        raise TimeoutError(f"eval case timed out: {case_id}")


def _should_collect_subagent_diagnostics(case, turn_index: int) -> bool:  # noqa: ANN001
    if not _case_requires_subagent_diagnostics(case):
        return False
    if bool(case.grader_case.get("await_child_completion")):
        return turn_index < len(case.turns)
    return turn_index == len(case.turns)


def _case_requires_subagent_diagnostics(case) -> bool:  # noqa: ANN001
    grader_id = str(getattr(case, "grader_id", None) or getattr(case, "family", None) or "").strip()
    if grader_id == "subagent_task_progress":
        return True
    grader_case = getattr(case, "grader_case", {}) or {}
    if not isinstance(grader_case, dict):
        return False
    if grader_case.get("timeout_ms") is not None:
        return True
    state_rules = grader_case.get("state_continuity")
    if not isinstance(state_rules, dict):
        return False
    return bool(
        state_rules.get("required_subagent_labels")
        or state_rules.get("require_subagent_completion")
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
    if not _case_requires_subagent_diagnostics(case):
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
