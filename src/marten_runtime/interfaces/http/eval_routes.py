from __future__ import annotations

import html
import json
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field

from marten_runtime.evals.display import (
    format_eval_timestamp as _format_eval_timestamp,
    int_value as _int_value,
    provider_health_status as _base_provider_health_status,
    run_label as _run_label,
    short_id as _short_id,
    suite_label as _suite_label,
)
from marten_runtime.evals.loader import load_suite_spec
from marten_runtime.evals.store import SQLiteEvalStore


class EvalRunHTTPCreateRequest(BaseModel):
    suite_id: str = Field(min_length=1, max_length=128)
    mode: str = "scripted"
    profile: str = "openai_gpt_5_4"
    baseline: str | None = None
    baseline_run: str | None = None
    write_baseline: str | None = None
    case_timeout_seconds: float | None = 120.0


@dataclass
class EvalJob:
    job_id: str
    status: str = "queued"
    suite_id: str = ""
    mode: str = ""
    profile: str = ""
    eval_run_id: str | None = None
    artifact_root: str | None = None
    error_text: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "suite_id": self.suite_id,
            "mode": self.mode,
            "profile": self.profile,
            "eval_run_id": self.eval_run_id,
            "artifact_root": self.artifact_root,
            "error_text": self.error_text,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class EvalJobRegistry:
    def __init__(self, repo_root: Path, env: dict[str, str] | None = None) -> None:
        self.repo_root = repo_root
        self.env = dict(env or {})
        self._lock = threading.RLock()
        self._jobs: dict[str, EvalJob] = {}

    def create(self, request: EvalRunHTTPCreateRequest) -> EvalJob:
        job = EvalJob(
            job_id=f"eval_job_{uuid4().hex[:8]}",
            suite_id=request.suite_id,
            mode=request.mode,
            profile=request.profile,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._prune_locked()
        thread = threading.Thread(
            target=self._run,
            args=(job.job_id, request),
            name=f"marten-{job.job_id}",
            daemon=True,
        )
        thread.start()
        return job

    def get(self, job_id: str) -> EvalJob:
        with self._lock:
            try:
                return self._jobs[job_id]
            except KeyError as exc:
                raise KeyError(job_id) from exc

    def _prune_locked(self) -> None:
        terminal_jobs = [
            job
            for job in self._jobs.values()
            if job.status in {"passed", "failed", "blocked"}
        ]
        if len(self._jobs) <= 100 or not terminal_jobs:
            return
        terminal_jobs.sort(key=lambda item: item.finished_at or item.created_at)
        for job in terminal_jobs[: max(0, len(self._jobs) - 100)]:
            self._jobs.pop(job.job_id, None)

    def _run(self, job_id: str, request: EvalRunHTTPCreateRequest) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
        try:
            from marten_runtime.evals.service import EvalRunRequest, run_eval_suite

            result = run_eval_suite(
                EvalRunRequest(
                    suite_id=request.suite_id,
                    mode=request.mode,
                    profile_name=request.profile,
                    baseline=request.baseline,
                    baseline_run_id=request.baseline_run,
                    write_baseline=request.write_baseline,
                    env=self.env,
                    case_timeout_seconds=request.case_timeout_seconds,
                ),
                repo_root=self.repo_root,
            )
            with self._lock:
                job = self._jobs[job_id]
                job.eval_run_id = result.summary.eval_run_id
                job.artifact_root = str(result.artifact_root)
                job.status = "blocked" if result.blocked_reason else result.summary.status
                job.error_text = result.blocked_reason
                job.finished_at = datetime.now(timezone.utc)
        except Exception as exc:  # pragma: no cover - preserved in job diagnostics
            with self._lock:
                job = self._jobs[job_id]
                job.status = "failed"
                job.error_text = f"{exc}\n{traceback.format_exc()}"
                job.finished_at = datetime.now(timezone.utc)


def build_eval_router(repo_root: Path, *, env: dict[str, str] | None = None) -> APIRouter:
    router = APIRouter()
    store = SQLiteEvalStore(repo_root / "data/evals.sqlite3")
    jobs = EvalJobRegistry(repo_root, env=env)

    @router.get("", response_class=HTMLResponse)
    def eval_home() -> str:
        suites = _suite_items(repo_root)
        runs = [
            _run_item_with_report(repo_root, item.model_dump(mode="json"))
            for item in store.list_runs(limit=20)
        ]
        return _render_home(suites, runs)

    @router.get("/suites")
    def list_suites(request: Request):  # noqa: ANN201
        items = _suite_items(repo_root)
        if _prefers_html(request):
            return HTMLResponse(_render_suites_page(items))
        return {"items": items, "count": len(items)}

    @router.get("/runs")
    def list_runs(request: Request, limit: int = 20, include_report: bool = False):  # noqa: ANN201
        prefers_html = _prefers_html(request)
        raw_items = [item.model_dump(mode="json") for item in store.list_runs(limit=limit)]
        items = [
            _run_item_with_report(repo_root, item)
            for item in raw_items
        ] if include_report or prefers_html else raw_items
        if prefers_html:
            return HTMLResponse(_render_runs_page(items, limit=limit))
        return {"items": items, "count": len(items)}

    @router.post("/runs")
    def create_run(request: EvalRunHTTPCreateRequest) -> dict[str, object]:
        if request.mode not in {"live", "scripted"}:
            raise HTTPException(status_code=422, detail="mode must be live or scripted")
        suite = _resolve_suite_for_request(repo_root, request.suite_id)
        if not suite.scripted_supported and request.mode == "scripted":
            raise HTTPException(status_code=422, detail="EVAL_SCRIPTED_MODE_UNSUPPORTED")
        job = jobs.create(request)
        return job.as_dict()

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, object]:
        try:
            return jobs.get(job_id).as_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="EVAL_JOB_NOT_FOUND") from exc

    @router.get("/runs/{eval_run_id}")
    def get_run(eval_run_id: str) -> dict[str, object]:
        try:
            summary = store.get_run(eval_run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="EVAL_RUN_NOT_FOUND") from exc
        cases = store.list_case_results(eval_run_id)
        artifact_root = _resolve_artifact_root(repo_root, summary.artifact_root)
        report_payload = _load_report_payload(artifact_root)
        return {
            "summary": summary.model_dump(mode="json"),
            "cases": [item.model_dump(mode="json") for item in cases],
            "case_count": len(cases),
            "artifacts": _artifact_links(artifact_root),
            "compare_result": report_payload.get("compare_result"),
            "stability_result": report_payload.get("stability_result"),
            "provider_reliability": report_payload.get("provider_reliability"),
            "blocked_reason": report_payload.get("blocked_reason"),
        }

    @router.get("/runs/{eval_run_id}/view", response_class=HTMLResponse)
    def view_run(eval_run_id: str) -> str:
        try:
            summary = store.get_run(eval_run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="EVAL_RUN_NOT_FOUND") from exc
        artifact_root = _resolve_artifact_root(repo_root, summary.artifact_root)
        report_payload = _load_report_payload(artifact_root)
        return _render_run(
            _run_item_with_report(repo_root, summary.model_dump(mode="json")),
            [item.model_dump(mode="json") for item in store.list_case_results(eval_run_id)],
            report_payload,
        )

    @router.get("/reports/{eval_run_id}", response_class=HTMLResponse)
    def view_report(eval_run_id: str):  # noqa: ANN201
        try:
            summary = store.get_run(eval_run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="EVAL_RUN_NOT_FOUND") from exc
        artifact_root = _resolve_artifact_root(repo_root, summary.artifact_root)
        for name in ("summary.html", "report.html", "index.html"):
            candidate = artifact_root / name
            if candidate.exists():
                return FileResponse(candidate, media_type="text/html")
        artifact_root = _resolve_artifact_root(repo_root, summary.artifact_root)
        report_payload = _load_report_payload(artifact_root)
        return _render_run(
            _run_item_with_report(repo_root, summary.model_dump(mode="json")),
            [item.model_dump(mode="json") for item in store.list_case_results(eval_run_id)],
            report_payload,
        )

    return router


def _resolve_suite_for_request(repo_root: Path, suite_id: str):  # noqa: ANN201
    normalized_suite_id = str(suite_id or "").strip()
    for path in sorted((repo_root / "evals" / "suites").glob("*.toml")):
        if path.stem == normalized_suite_id:
            return load_suite_spec(path)
    raise HTTPException(status_code=404, detail="EVAL_SUITE_NOT_FOUND")


def _suite_items(repo_root: Path) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for path in sorted((repo_root / "evals" / "suites").glob("*.toml")):
        suite = load_suite_spec(path)
        items.append(
            {
                "suite_id": suite.suite_id,
                "description": suite.description,
                "default_mode": suite.default_mode,
                "scripted_supported": suite.scripted_supported,
                "required_dependencies": list(suite.required_dependencies),
                "case_count": len(suite.cases),
            }
        )
    return items


def _resolve_artifact_root(repo_root: Path, artifact_root: str) -> Path:
    path = Path(artifact_root)
    if path.is_absolute():
        return path
    return repo_root / path


def _artifact_links(artifact_root: Path) -> dict[str, object]:
    html_name = _first_existing_report_name(artifact_root)
    return {
        "artifact_root": str(artifact_root),
        "html_exists": html_name is not None,
        "html_name": html_name,
        "markdown_exists": (artifact_root / "summary.md").exists(),
        "summary_exists": (artifact_root / "summary.json").exists(),
    }


def _first_existing_report_name(artifact_root: Path) -> str | None:
    for name in ("summary.html", "report.html", "index.html"):
        if (artifact_root / name).exists():
            return name
    return None


def _load_report_payload(artifact_root: Path) -> dict[str, object]:
    path = artifact_root / "summary.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _run_item_with_report(repo_root: Path, item: dict[str, object]) -> dict[str, object]:
    artifact_root = _resolve_artifact_root(repo_root, str(item.get("artifact_root") or ""))
    report_payload = _load_report_payload(artifact_root)
    compare = report_payload.get("compare_result")
    provider_reliability = report_payload.get("provider_reliability")
    item = dict(item)
    item["report_url"] = f"/evals/reports/{item.get('eval_run_id') or ''}" if _first_existing_report_name(artifact_root) else None
    item["compare_result"] = compare
    item["provider_reliability"] = provider_reliability
    if isinstance(compare, dict):
        item["baseline_eval_run_id"] = compare.get("baseline_eval_run_id")
        item["baseline_source"] = compare.get("baseline_source")
        item["total_score_delta"] = compare.get("total_score_delta")
        item["pass_rate_delta"] = compare.get("pass_rate_delta")
        item["regression_count"] = len(list(compare.get("regressions") or []))
        item["improvement_count"] = len(list(compare.get("improvements") or []))
    if isinstance(provider_reliability, dict):
        item["retry_count"] = provider_reliability.get("retry_count")
        item["fallback_count"] = provider_reliability.get("fallback_count")
        item["provider_error_count"] = provider_reliability.get("provider_error_count")
        item["empty_output_count"] = provider_reliability.get("empty_output_count")
    return item


def _prefers_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return False
    return "text/html" in accept or accept.strip() in {"", "*/*"}


def _render_suites_page(suites: list[dict[str, object]]) -> str:
    suite_rows = "".join(_suite_row(item) for item in suites)
    total_cases = sum(int(item.get("case_count") or 0) for item in suites)
    dependencies = sorted(
        {
            _dependency_label(str(value))
            for item in suites
            for value in (item.get("required_dependencies") or [])
        }
    )
    return _page(
        "评测套件",
        "<h1>评测套件</h1>"
        "<p class=\"lead\">查看当前已注册 suite、默认运行模式、依赖和用例规模。</p>"
        "<div class=\"cards\">"
        f"<div class=\"card\"><div class=\"card-title\">套件数</div><div class=\"card-value\">{len(suites)}</div><div class=\"card-note\">当前可运行</div></div>"
        f"<div class=\"card\"><div class=\"card-title\">用例数</div><div class=\"card-value\">{total_cases}</div><div class=\"card-note\">所有套件合计</div></div>"
        f"<div class=\"card\"><div class=\"card-title\">依赖类型</div><div class=\"card-value small\">{_e(', '.join(dependencies) or '—')}</div><div class=\"card-note\">运行前检查项</div></div>"
        "</div>"
        "<section class=\"panel\"><h2>套件清单</h2>"
        "<table><thead><tr><th>套件</th><th>默认模式</th><th>用例数</th><th>依赖</th><th>说明</th></tr></thead>"
        f"<tbody>{suite_rows}</tbody></table></section>",
    )


def _render_runs_page(runs: list[dict[str, object]], *, limit: int) -> str:
    run_rows = "".join(_run_row(item) for item in runs)
    return _page(
        "历史运行记录",
        "<h1>历史运行记录</h1>"
        "<p class=\"lead\">按最新时间展示 eval 运行记录，包含状态、分数、基线对比、Provider 评估和报告入口。</p>"
        f"{_overview_cards(runs)}"
        f"{_provider_eval_overview(runs)}"
        "<section class=\"panel\"><h2>运行记录</h2>"
        f"<p class=\"muted\">当前显示最近 {limit} 条。JSON API 可通过 Accept: application/json 获取原始数据。</p>"
        "<table><thead><tr><th>运行</th><th>套件</th><th>状态</th><th>总分</th><th>通过率</th><th>Provider 重试</th><th>Provider 回退</th><th>Provider 错误</th><th>空输出</th><th>对比基线</th><th>总分变化</th><th>通过率变化</th><th>变化用例</th><th>模型配置</th><th>开始时间</th><th>报告</th></tr></thead>"
        f"<tbody>{run_rows}</tbody></table></section>",
    )


def _render_home(suites: list[dict[str, object]], runs: list[dict[str, object]]) -> str:
    suite_rows = "".join(_suite_row(item) for item in suites)
    run_rows = "".join(_run_row(item) for item in runs)
    return _page(
        "Eval 运维面",
        "<h1>评测总览</h1>"
        "<p class=\"lead\">同服务 eval 运维面：查看当前评测链路状态、历史记录、基线分数变化和报告入口。</p>"
        f"{_overview_cards(runs)}"
        f"{_provider_eval_overview(runs)}"
        "<section class=\"panel\"><h2>评测套件</h2>"
        "<table><thead><tr><th>套件</th><th>默认模式</th><th>用例数</th><th>依赖</th><th>说明</th></tr></thead>"
        f"<tbody>{suite_rows}</tbody></table></section>"
        "<section class=\"panel\"><h2>运行记录</h2>"
        "<p class=\"muted\">总分变化与通过率变化来自该次运行的基线对比；红色代表回退，绿色代表提升。</p>"
        "<table><thead><tr><th>运行</th><th>套件</th><th>状态</th><th>总分</th><th>通过率</th><th>Provider 重试</th><th>Provider 回退</th><th>Provider 错误</th><th>空输出</th><th>对比基线</th><th>总分变化</th><th>通过率变化</th><th>变化用例</th><th>模型配置</th><th>开始时间</th><th>报告</th></tr></thead>"
        f"<tbody>{run_rows}</tbody></table></section>",
    )


def _suite_row(item: dict[str, object]) -> str:
    dependencies = ", ".join(_dependency_label(str(value)) for value in item.get("required_dependencies") or [])
    return (
        "<tr>"
        f"<td><code>{_e(item['suite_id'])}</code></td>"
        f"<td>{_e(_mode_label(item.get('default_mode')))}</td>"
        f"<td>{item['case_count']}</td>"
        f"<td>{_e(dependencies)}</td>"
        f"<td>{_e(item['description'])}</td>"
        "</tr>"
    )


def _overview_cards(runs: list[dict[str, object]]) -> str:
    latest = runs[0] if runs else {}
    status_counts = _status_counts(runs)
    latest_status = _status_label(latest.get("status")) if latest else "暂无运行"
    latest_score = _format_number(latest.get("total_score")) if latest else "—"
    latest_delta = _delta_cell(latest.get("total_score_delta")) if latest else "—"
    baseline = latest.get("baseline_eval_run_id") or latest.get("baseline_source") or "—"
    cards = [
        ("最近运行", str(len(runs)), f"通过 {status_counts.get('passed', 0)} · 失败 {status_counts.get('failed', 0)} · 阻塞 {status_counts.get('blocked', 0)}"),
        ("最新状态", latest_status, f"总分 {latest_score}"),
        ("最新分数变化", latest_delta, "相对本次基线"),
        ("最新基线", _run_label(str(baseline)), "用于判断提升或回退"),
    ]
    return '<div class="cards">' + ''.join(
        f'<div class="card"><div class="card-title">{_e(title)}</div><div class="card-value">{value}</div><div class="card-note">{_e(note)}</div></div>'
        for title, value, note in cards
    ) + '</div>'


def _provider_eval_overview(runs: list[dict[str, object]]) -> str:
    retry_count = sum(_int_value(item.get("retry_count")) for item in runs)
    fallback_count = sum(_int_value(item.get("fallback_count")) for item in runs)
    provider_error_count = sum(_int_value(item.get("provider_error_count")) for item in runs)
    empty_output_count = sum(_int_value(item.get("empty_output_count")) for item in runs)
    latest_provider = _latest_provider_ref(runs)
    status_label, status_note, status_css = _provider_health_status(
        retry_count=retry_count,
        fallback_count=fallback_count,
        provider_error_count=provider_error_count,
        empty_output_count=empty_output_count,
    )
    return (
        '<section class="panel"><h2>Provider 评估</h2>'
        '<p class="muted">统计最近运行中的模型服务稳定性：重试、回退、错误、空输出和最终 provider。</p>'
        '<div class="cards">'
        f'<div class="card"><div class="card-title">Provider 状态</div><div class="card-value"><span class="badge {status_css}">{_e(status_label)}</span></div><div class="card-note">{_e(status_note)}</div></div>'
        f'<div class="card"><div class="card-title">Provider 重试</div><div class="card-value">{retry_count}</div><div class="card-note">最近 runs 合计</div></div>'
        f'<div class="card"><div class="card-title">Provider 回退</div><div class="card-value">{fallback_count}</div><div class="card-note">profile/provider 切换次数</div></div>'
        f'<div class="card"><div class="card-title">Provider 错误</div><div class="card-value">{provider_error_count}</div><div class="card-note">provider 调用失败次数</div></div>'
        f'<div class="card"><div class="card-title">空输出</div><div class="card-value">{empty_output_count}</div><div class="card-note">模型无有效最终输出</div></div>'
        '</div>'
        f'<p class="muted">最近最终 provider：<strong>{_e(latest_provider)}</strong></p>'
        '</section>'
    )


def _status_counts(runs: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in runs:
        status = str(item.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _render_run(
    summary: dict[str, object],
    cases: list[dict[str, object]],
    report_payload: dict[str, object] | None = None,
) -> str:
    case_rows = "".join(
        "<tr>"
        f"<td><code>{_e(item['case_id'])}</code></td>"
        f"<td>{_status_badge(item.get('status'))}</td>"
        f"<td>{_format_number(item.get('total_score'))}</td>"
        f"<td>{item['llm_request_count']}</td>"
        f"<td>{item['tool_calls_count']}</td>"
        f"<td>{_e(item.get('run_id') or '')}</td>"
        f"<td>{_e((item.get('final_text') or '')[:180])}</td>"
        "</tr>"
        for item in cases
    )
    report_payload = report_payload or {}
    compare_block = _render_compare_block(summary, report_payload.get("compare_result"))
    stability_block = _render_stability_block(report_payload.get("stability_result"))
    provider_reliability_block = _render_provider_reliability_block(
        report_payload.get("provider_reliability")
    )
    blocked_block = _render_blocked_reason(report_payload.get("blocked_reason"))
    report_link = (
        f'<p><a class="button" href="/evals/reports/{_e(summary["eval_run_id"])}">查看完整报告</a></p>'
        if summary.get("report_url")
        else ""
    )
    return _page(
        f"Eval {_run_label(str(summary['eval_run_id']))}",
        "<h1>评测详情</h1>"
        "<section class=\"panel\"><h2>本次运行</h2>"
        "<div class=\"kv\">"
        f"<div>运行</div><div>{_e(_run_label(str(summary['eval_run_id'])))}</div>"
        f"<div>原始 ID</div><div><code>{_e(summary['eval_run_id'])}</code></div>"
        f"<div>套件</div><div><code>{_e(summary['suite_id'])}</code></div>"
        f"<div>状态</div><div>{_status_badge(summary.get('status'))}</div>"
        f"<div>总分</div><div>{_format_number(summary.get('total_score'))}</div>"
        f"<div>通过率</div><div>{_format_percent(summary.get('pass_rate'))}</div>"
        f"<div>模型配置</div><div>{_e(summary['profile_name'])}</div>"
        f"<div>工件目录</div><div><code>{_e(summary['artifact_root'])}</code></div>"
        "</div>"
        f"{report_link}</section>"
        f"{blocked_block}"
        f"{compare_block}"
        f"{stability_block}"
        f"{provider_reliability_block}"
        "<section class=\"panel\"><h2>用例明细</h2>"
        "<table><thead><tr><th>用例</th><th>状态</th><th>分数</th><th>LLM 请求</th><th>工具调用</th><th>链路 run_id</th><th>最终回复片段</th></tr></thead>"
        f"<tbody>{case_rows}</tbody></table></section>",
    )


def _run_row(item: dict[str, object]) -> str:
    run_id = str(item.get("eval_run_id") or "")
    report_url = str(item.get("report_url") or "")
    report_link = f'<a href="{_e(report_url)}">查看报告</a>' if report_url else ""
    baseline = item.get("baseline_eval_run_id") or item.get("baseline_source") or ""
    return (
        "<tr>"
        f'<td><a href="/evals/runs/{_e(run_id)}/view">{_e(_run_label(run_id))}</a></td>'
        f"<td><code>{_e(item.get('suite_id') or '')}</code></td>"
        f"<td>{_status_badge(item.get('status'))}</td>"
        f"<td>{_format_number(item.get('total_score'))}</td>"
        f"<td>{_format_percent(item.get('pass_rate'))}</td>"
        f"<td>{_e(item.get('retry_count') or 0)}</td>"
        f"<td>{_e(item.get('fallback_count') or 0)}</td>"
        f"<td>{_e(item.get('provider_error_count') or 0)}</td>"
        f"<td>{_e(item.get('empty_output_count') or 0)}</td>"
        f"<td>{_e(_run_label(str(baseline)))}</td>"
        f"<td>{_delta_cell(item.get('total_score_delta'))}</td>"
        f"<td>{_delta_cell(item.get('pass_rate_delta'), percent=True)}</td>"
        f"<td>{_e(_format_changes(item))}</td>"
        f"<td>{_e(item.get('profile_name') or '')}</td>"
        f"<td>{_e(_format_timestamp(item.get('started_at')))}</td>"
        f"<td>{report_link}</td>"
        "</tr>"
    )


def _format_changes(item: dict[str, object]) -> str:
    regressions = item.get("regression_count")
    improvements = item.get("improvement_count")
    if regressions is None and improvements is None:
        return "—"
    return f"回退 {regressions or 0} · 提升 {improvements or 0}"


def _render_blocked_reason(blocked_reason: object) -> str:
    if not blocked_reason:
        return ""
    return f'<section class="panel warning"><h2>阻塞原因</h2><p>{_e(blocked_reason)}</p></section>'


def _render_provider_reliability_block(provider_reliability: object) -> str:
    if not isinstance(provider_reliability, dict):
        return '<section class="panel"><h2>Provider 评估</h2><p class="muted">暂无 provider 稳定性摘要。</p></section>'
    top_error_kinds = list(provider_reliability.get("top_error_kinds") or [])
    latest_runs = list(provider_reliability.get("latest_runs") or [])
    error_kind_text = ", ".join(
        f"{item.get('error_kind')}: {item.get('count')}"
        for item in top_error_kinds
        if isinstance(item, dict)
    )
    retry_count = _int_value(provider_reliability.get("retry_count"))
    fallback_count = _int_value(provider_reliability.get("fallback_count"))
    provider_error_count = _int_value(provider_reliability.get("provider_error_count"))
    empty_output_count = _int_value(provider_reliability.get("empty_output_count"))
    status_label, status_note, status_css = _provider_health_status(
        retry_count=retry_count,
        fallback_count=fallback_count,
        provider_error_count=provider_error_count,
        empty_output_count=empty_output_count,
    )
    return (
        "<section class=\"panel\"><h2>Provider 评估</h2>"
        "<p class=\"muted\">本次评测报告中的 provider 可靠性摘要。</p>"
        "<div class=\"kv\">"
        f"<div>Provider 状态</div><div><span class=\"badge {status_css}\">{_e(status_label)}</span> <span class=\"muted\">{_e(status_note)}</span></div>"
        f"<div>窗口大小</div><div>{_e(provider_reliability.get('window_size') or 0)}</div>"
        f"<div>运行数</div><div>{_e(provider_reliability.get('run_count') or 0)}</div>"
        f"<div>重试</div><div>{retry_count}</div>"
        f"<div>回退</div><div>{fallback_count}</div>"
        f"<div>错误</div><div>{provider_error_count}</div>"
        f"<div>空输出</div><div>{empty_output_count}</div>"
        f"<div>最近最终 provider</div><div>{_e(provider_reliability.get('latest_final_provider_ref') or '—')}</div>"
        f"<div>主要错误类型</div><div>{_e(error_kind_text or '—')}</div>"
        "</div>"
        f"<h3 style=\"margin-top:16px;\">最近 runs</h3>{_render_provider_reliability_runs(latest_runs)}"
        "</section>"
    )


def _render_provider_reliability_runs(runs: list[object]) -> str:
    if not runs:
        return '<p class="muted">无</p>'
    rows = "".join(
        "<tr>"
        f"<td>{_e(_run_label(str(item.get('run_id') or '')))}</td>"
        f"<td>{_e(item.get('status') or '')}</td>"
        f"<td>{_e(item.get('retry_count') or 0)}</td>"
        f"<td>{_e(item.get('fallback_count') or 0)}</td>"
        f"<td>{_e(item.get('provider_error_count') or 0)}</td>"
        f"<td>{_e(item.get('empty_output_count') or 0)}</td>"
        f"<td>{_e(item.get('final_provider_ref') or '—')}</td>"
        "</tr>"
        for item in runs
        if isinstance(item, dict)
    )
    return (
        "<table><thead><tr><th>运行</th><th>状态</th><th>重试</th><th>回退</th><th>错误</th><th>空输出</th><th>最终 provider</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _render_compare_block(summary: dict[str, object], compare: object) -> str:
    if not isinstance(compare, dict):
        return '<section class="panel"><h2>对比结果</h2><p class="muted">本次运行暂无基线对比记录。</p></section>'
    baseline = compare.get("baseline_eval_run_id") or summary.get("baseline_eval_run_id") or ""
    source = compare.get("baseline_source") or ""
    regressions = list(compare.get("regressions") or [])
    improvements = list(compare.get("improvements") or [])
    return (
        "<section class=\"panel\"><h2>对比结果</h2>"
        "<div class=\"kv\">"
        f"<div>对比基线</div><div>{_e(_run_label(str(baseline)))}</div>"
        f"<div>基线原始 ID</div><div><code>{_e(baseline or '—')}</code></div>"
        f"<div>基线来源</div><div>{_e(source)}</div>"
        f"<div>总分变化</div><div>{_delta_cell(compare.get('total_score_delta'))}</div>"
        f"<div>通过率变化</div><div>{_delta_cell(compare.get('pass_rate_delta'), percent=True)}</div>"
        f"<div>回退用例</div><div>{len(regressions)}</div>"
        f"<div>提升用例</div><div>{len(improvements)}</div>"
        "</div>"
        f"{_render_compare_list('回退项', regressions)}"
        f"{_render_compare_list('提升项', improvements)}"
        "</section>"
    )


def _render_compare_list(title: str, items: list[object]) -> str:
    if not items:
        return f'<h3>{_e(title)}</h3><p class="muted">无</p>'
    rows = "".join(
        "<tr>"
        f"<td><code>{_e(item.get('case_id') if isinstance(item, dict) else '')}</code></td>"
        f"<td>{_e(item.get('baseline_status') if isinstance(item, dict) else '')}</td>"
        f"<td>{_e(item.get('current_status') if isinstance(item, dict) else '')}</td>"
        f"<td>{_delta_cell(item.get('total_score_delta') if isinstance(item, dict) else None)}</td>"
        "</tr>"
        for item in items
    )
    return (
        f"<h3>{_e(title)}</h3>"
        "<table><thead><tr><th>用例</th><th>基线状态</th><th>当前状态</th><th>分数变化</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _render_stability_block(stability: object) -> str:
    if not isinstance(stability, dict):
        return '<section class="panel"><h2>稳定性</h2><p class="muted">暂无稳定性采样记录。</p></section>'
    return (
        "<section class=\"panel\"><h2>稳定性</h2>"
        "<div class=\"kv\">"
        f"<div>样本数</div><div>{_e(stability.get('sample_size') or '')}</div>"
        f"<div>波动用例</div><div>{_e(stability.get('unstable_case_count') or 0)}</div>"
        f"<div>波动组件</div><div>{_e(stability.get('unstable_component_count') or 0)}</div>"
        f"<div>回退占比</div><div>{_e(stability.get('failover_rate') or 0)}</div>"
        "</div></section>"
    )


def _status_badge(value: object) -> str:
    status = str(value or "")
    css = {
        "passed": "ok",
        "failed": "bad",
        "blocked": "warn",
        "running": "info",
        "queued": "info",
    }.get(status, "neutral")
    return f'<span class="badge {css}">{_e(_status_label(status))}</span>'


def _status_label(value: object) -> str:
    return {
        "passed": "通过",
        "failed": "失败",
        "blocked": "阻塞",
        "running": "运行中",
        "queued": "排队中",
    }.get(str(value or ""), str(value or "—"))


def _provider_health_status(
    *,
    retry_count: int,
    fallback_count: int,
    provider_error_count: int,
    empty_output_count: int,
) -> tuple[str, str, str]:
    if provider_error_count > 0 or empty_output_count > 0:
        return ("有错误", "存在 provider 错误或空输出", "bad")
    if retry_count > 0 or fallback_count > 0:
        return ("有波动", "出现重试或 provider 回退", "warn")
    return ("健康", "无重试、无回退、无错误、无空输出", "ok")


def _mode_label(value: object) -> str:
    return {
        "live": "真实链路",
        "scripted": "脚本回放",
    }.get(str(value or ""), str(value or ""))


def _dependency_label(value: str) -> str:
    return {
        "provider": "模型服务",
        "mcp": "MCP",
        "subagent": "子代理",
    }.get(value, value)



def _provider_health_status(
    *,
    retry_count: int,
    fallback_count: int,
    provider_error_count: int,
    empty_output_count: int,
) -> tuple[str, str, str]:
    status_label, status_note = _base_provider_health_status(
        retry_count=retry_count,
        fallback_count=fallback_count,
        provider_error_count=provider_error_count,
        empty_output_count=empty_output_count,
    )
    css = {"有错误": "bad", "有波动": "warn"}.get(status_label, "ok")
    return status_label, status_note, css


def _latest_provider_ref(runs: list[dict[str, object]]) -> str:
    for item in runs:
        provider_reliability = item.get("provider_reliability")
        if isinstance(provider_reliability, dict):
            value = provider_reliability.get("latest_final_provider_ref")
            if value:
                return str(value)
    return "—"


def _format_timestamp(value: object) -> str:
    text = str(value or "")
    if len(text) >= 19 and "T" in text:
        return text[:19].replace("T", " ")
    return text


def _format_percent(value: object) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return _e(value or "—")


def _format_number(value: object) -> str:
    try:
        return f"{float(value):.4g}"
    except (TypeError, ValueError):
        return _e(value or "—")


def _delta_cell(value: object, *, percent: bool = False) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _e(value)
    css = "delta-up" if number > 0 else "delta-down" if number < 0 else "delta-flat"
    prefix = "+" if number > 0 else ""
    rendered = f"{prefix}{number * 100:.1f}%" if percent else f"{prefix}{number:g}"
    return f'<span class="{css}">{rendered}</span>'


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head>"
        f"<title>{_e(title)}</title>"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:24px;color:#172033;background:#fafafa;}"
        "h1{margin-bottom:4px}.lead,.muted{color:#667085}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0;}"
        ".card,.panel{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px;margin:14px 0;box-shadow:0 1px 2px rgba(16,24,40,.04)}"
        ".card-title{color:#667085;font-size:13px}.card-value{font-size:22px;font-weight:700;margin-top:6px;overflow:hidden;text-overflow:ellipsis}.card-note{color:#667085;font-size:12px;margin-top:4px}"
        "table{border-collapse:collapse;width:100%;margin:12px 0;background:#fff;}th,td{border-bottom:1px solid #eee;padding:7px;text-align:left;vertical-align:top;font-size:13px;}"
        "th{background:#f6f8fa;color:#475467;}code{background:#f6f8fa;padding:2px 4px;border-radius:4px;}a{color:#175cd3;text-decoration:none}.button{display:inline-block;background:#175cd3;color:white;padding:8px 10px;border-radius:6px;}"
        ".kv{display:grid;grid-template-columns:140px 1fr;gap:8px 12px}.kv>div:nth-child(odd){color:#667085}.warning{border-color:#fedf89;background:#fffbeb}"
        ".badge{display:inline-block;border-radius:999px;padding:2px 8px;font-size:12px;font-weight:700}.badge.ok{background:#ecfdf3;color:#067647}.badge.bad{background:#fef3f2;color:#b42318}.badge.warn{background:#fffaeb;color:#b54708}.badge.info{background:#eff8ff;color:#175cd3}.badge.neutral{background:#f2f4f7;color:#475467}"
        ".delta-up{color:#18794e;font-weight:700}.delta-down{color:#b42318;font-weight:700}.delta-flat{color:#667085;font-weight:700}@media(max-width:1100px){.cards{grid-template-columns:repeat(2,minmax(0,1fr));}}</style>"
        "</head><body>"
        f"{body}</body></html>"
    )


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
