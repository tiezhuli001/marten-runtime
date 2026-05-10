from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


from marten_runtime.config.agents_loader import load_agent_specs
from marten_runtime.config.models_loader import load_models_config, resolve_model_profile
from marten_runtime.config.providers_loader import load_providers_config
from marten_runtime.evals.compare import (
    build_eval_run_stability_summary,
    compare_eval_runs,
    resolve_compare_baseline,
)
from marten_runtime.evals.executor import execute_suite
from marten_runtime.evals.graders import grade_case_result
from marten_runtime.evals.loader import load_suite_spec
from marten_runtime.evals.models import EvalRunSummary
from marten_runtime.evals.report import (
    resolve_case_artifact_path,
    resolve_report_artifact_root,
    write_eval_report,
)
from marten_runtime.evals.run_metadata import (
    REPO_ROOT,
    build_eval_run_id,
    config_fingerprint,
    git_state,
)
from marten_runtime.evals.store import SQLiteEvalStore
from marten_runtime.mcp.loader import load_mcp_servers

STABILITY_WINDOW = 5


@dataclass(frozen=True)
class EvalRunRequest:
    suite_id: str
    mode: str
    profile_name: str
    baseline: str | None = None
    baseline_run_id: str | None = None
    write_baseline: str | None = None
    db_path: str | Path = "data/evals.sqlite3"
    report_root: str | Path = "reports/evals"
    env: dict[str, str] | None = None


@dataclass(frozen=True)
class EvalRunServiceResult:
    summary: EvalRunSummary
    artifact_root: Path
    blocked_reason: str | None = None
    case_count: int = 0


def list_suite_paths(repo_root: Path) -> list[Path]:
    suites_root = repo_root / "evals" / "suites"
    return sorted(suites_root.glob("*.toml"))


def resolve_suite_path(repo_root: Path, suite_id: str) -> Path:
    normalized_suite_id = str(suite_id or "").strip()
    for path in list_suite_paths(repo_root):
        if path.stem == normalized_suite_id:
            return path
    raise FileNotFoundError((repo_root / "evals" / "suites" / f"{normalized_suite_id}.toml").as_posix())


def _resolve_repo_relative_path(repo_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def run_eval_suite(
    request: EvalRunRequest,
    *,
    repo_root: Path | None = None,
) -> EvalRunServiceResult:
    resolved_repo_root = Path(repo_root or REPO_ROOT)
    resolved_report_root = _resolve_repo_relative_path(resolved_repo_root, request.report_root)
    suite = load_suite_spec(resolve_suite_path(resolved_repo_root, request.suite_id))
    store = SQLiteEvalStore(_resolve_repo_relative_path(resolved_repo_root, request.db_path))
    baseline_eval_run_id, baseline_source = resolve_compare_baseline(
        store,
        suite_id=suite.suite_id,
        baseline_name=request.baseline,
        baseline_run_id=request.baseline_run_id,
    )
    blocked_reason = resolve_suite_dependency_block(
        repo_root=resolved_repo_root,
        suite=suite,
        mode=request.mode,
        profile_name=request.profile_name,
        env=request.env,
    )
    if blocked_reason is not None:
        blocked_summary = build_blocked_summary(
            repo_root=resolved_repo_root,
            suite_id=suite.suite_id,
            mode=request.mode,
            profile_name=request.profile_name,
            baseline_eval_run_id=baseline_eval_run_id,
            report_root=resolved_report_root,
        ).model_copy(
            update={"status": "blocked", "finished_at": datetime.now(timezone.utc)}
        )
        store.record_run_start(blocked_summary)
        store.record_run_finish(
            blocked_summary.eval_run_id,
            total_score=blocked_summary.total_score,
            pass_rate=blocked_summary.pass_rate,
            status=blocked_summary.status,
        )
        artifact_root = write_eval_report(
            blocked_summary,
            [],
            report_root=resolved_report_root,
            blocked_reason=blocked_reason,
        )
        return EvalRunServiceResult(
            summary=blocked_summary,
            artifact_root=Path(artifact_root),
            blocked_reason=blocked_reason,
            case_count=0,
        )

    summary, observations = execute_suite(
        suite,
        mode=request.mode,
        profile_name=request.profile_name,
        repo_root=resolved_repo_root,
    )
    resolved_artifact_root = resolve_report_artifact_root(
        resolved_report_root,
        summary.eval_run_id,
    )
    summary = summary.model_copy(
        update={
            "baseline_eval_run_id": baseline_eval_run_id,
            "artifact_root": str(resolved_artifact_root),
        }
    )
    store.record_run_start(summary)
    case_results = [
        grade_case_result(case, observation, eval_run_id=summary.eval_run_id)
        for case, observation in zip(suite.cases, observations, strict=False)
    ]
    case_results = [
        result.model_copy(
            update={
                "artifact_path": str(
                    resolve_case_artifact_path(resolved_artifact_root, result.case_id)
                )
            }
        )
        for result in case_results
    ]
    for result in case_results:
        store.record_case_result(result)

    passed_count = sum(1 for item in case_results if item.status == "passed")
    total_score = round(
        sum(item.total_score for item in case_results) / max(1, len(case_results)),
        4,
    )
    pass_rate = round(passed_count / max(1, len(case_results)), 4)
    final_status = "passed" if passed_count == len(case_results) else "failed"
    finished = summary.model_copy(
        update={
            "total_score": total_score,
            "pass_rate": pass_rate,
            "status": final_status,
            "finished_at": datetime.now(timezone.utc),
        }
    )
    store.record_run_finish(
        finished.eval_run_id,
        total_score=finished.total_score,
        pass_rate=finished.pass_rate,
        status=finished.status,
    )
    compare_result = None
    if baseline_eval_run_id is not None:
        baseline_summary = store.get_run(baseline_eval_run_id)
        baseline_case_results = store.list_case_results(baseline_eval_run_id)
        compare_result = compare_eval_runs(
            finished,
            case_results,
            baseline_summary,
            baseline_case_results,
            baseline_source=baseline_source or "unknown",
        )
    recent_runs = store.list_recent_runs(
        suite_id=finished.suite_id,
        profile_name=finished.profile_name,
        eval_mode=finished.eval_mode,
        git_sha=finished.git_sha,
        config_fingerprint=finished.config_fingerprint,
        suite_fingerprint=finished.suite_fingerprint,
        limit=STABILITY_WINDOW,
    )
    stability_result = None
    if recent_runs:
        stability_result = build_eval_run_stability_summary(
            suite_id=finished.suite_id,
            profile_name=finished.profile_name,
            eval_mode=finished.eval_mode,
            run_summaries=recent_runs,
            case_results_by_run_id={
                item.eval_run_id: store.list_case_results(item.eval_run_id)
                for item in recent_runs
            },
            case_specs=suite.cases,
            window_size=STABILITY_WINDOW,
        )
    if finished.status == "passed":
        store.write_baseline(suite.suite_id, "latest_passed", finished.eval_run_id)
    if request.write_baseline and finished.status == "passed":
        store.write_baseline(suite.suite_id, request.write_baseline, finished.eval_run_id)
    artifact_root = write_eval_report(
        finished,
        case_results,
        report_root=resolved_report_root,
        compare_result=compare_result,
        stability_result=(
            stability_result.model_dump(mode="json")
            if stability_result is not None
            else None
        ),
    )
    return EvalRunServiceResult(
        summary=finished,
        artifact_root=Path(artifact_root),
        case_count=len(case_results),
    )


def build_blocked_summary(
    *,
    repo_root: Path,
    suite_id: str,
    mode: str,
    profile_name: str,
    baseline_eval_run_id: str | None,
    report_root: Path,
) -> EvalRunSummary:
    models_config = load_models_config(str(repo_root / "config/models.toml"))
    resolved_profile_name, profile = resolve_model_profile(models_config, profile_name)
    git_branch, git_sha, git_dirty = git_state(repo_root)
    eval_run_id = build_eval_run_id(suite_id, git_sha)
    return EvalRunSummary(
        eval_run_id=eval_run_id,
        suite_id=suite_id,
        git_branch=git_branch,
        git_sha=git_sha,
        git_dirty=git_dirty,
        eval_mode=mode,
        agent_id="main",
        profile_name=resolved_profile_name,
        provider_ref=profile.provider_ref,
        model_name=profile.model,
        config_fingerprint=config_fingerprint(repo_root),
        suite_fingerprint="blocked",
        baseline_eval_run_id=baseline_eval_run_id,
        total_score=0.0,
        pass_rate=0.0,
        status="blocked",
        artifact_root=str(resolve_report_artifact_root(report_root, eval_run_id)),
        finished_at=datetime.now(timezone.utc),
    )


def resolve_suite_dependency_block(
    *,
    repo_root: Path,
    suite,
    mode: str,
    profile_name: str,
    env: dict[str, str] | None = None,
) -> str | None:
    if mode == "scripted":
        return None
    resolved_env = dict(env or {})
    dependencies = list(getattr(suite, "required_dependencies", []) or [])
    if "mcp" in dependencies:
        mcps_path = repo_root / "mcps.json"
        if not mcps_path.exists():
            mcps_path = repo_root / "mcps.example.json"
        if not mcps_path.exists():
            return "mcp dependency missing: mcps.json or mcps.example.json"
        if not load_mcp_servers(str(mcps_path)):
            return "mcp dependency missing: empty server list"
    if "subagent" in dependencies:
        agents = {
            item.agent_id: item
            for item in load_agent_specs(str(repo_root / "config/agents.toml"))
        }
        main_agent = agents.get("main")
        if main_agent is None or not {"spawn_subagent", "cancel_subagent"}.issubset(
            set(main_agent.allowed_tools)
        ):
            return "subagent dependency missing: spawn_subagent/cancel_subagent surface"
    if "provider" in dependencies:
        models_config = load_models_config(str(repo_root / "config/models.toml"))
        providers_config = load_providers_config(str(repo_root / "config/providers.toml"))
        _, profile = resolve_model_profile(models_config, profile_name)
        provider = providers_config.providers.get(profile.provider_ref)
        if provider is None:
            return f"provider dependency missing: {profile.provider_ref}"
        api_key_env = str(provider.api_key_env or "").strip()
        if api_key_env and not resolved_env.get(api_key_env):
            return f"provider dependency missing: {api_key_env}"
    return None
