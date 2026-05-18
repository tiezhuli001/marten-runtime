from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvalReportRecord:
    run_id: str
    suite_id: str
    mode: str
    status: str
    score: float
    pass_rate: float
    profile: str
    provider: str
    branch: str
    sha: str
    finished_at: str
    summary_path: str
    failed_cases: list[str]
    compare: dict[str, Any] | None


def write_eval_index(report_root: str | Path) -> Path:
    root = Path(report_root)
    root.mkdir(parents=True, exist_ok=True)
    records = _load_records(root)
    latest = _latest_by_suite(records)
    body = render_eval_index_html(records=records, latest=latest)
    output = root / "index.html"
    output.write_text(body, encoding="utf-8")
    return output


def render_eval_index_html(*, records: list[EvalReportRecord], latest: list[EvalReportRecord]) -> str:
    selected = _select_dashboard_records(records)
    challenge = [item for item in selected if item.suite_id.startswith("challenge_")]
    gate = [item for item in selected if not item.suite_id.startswith("challenge_")]
    challenge.sort(key=lambda item: item.suite_id)
    gate.sort(key=lambda item: item.suite_id)
    recent = sorted(records, key=lambda item: (item.finished_at, item.run_id), reverse=True)[:30]
    challenge_score = _mean([item.score for item in challenge])
    gate_score = _mean([item.score for item in gate])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Eval 总览</title>
  <style>
    :root {{
      --bg:#f6f8fb; --panel:#fff; --text:#1f2937; --muted:#667085; --border:#dbe2ea;
      --green:#18794e; --red:#b42318; --amber:#9a6700; --blue:#175cd3;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); line-height:1.5; }}
    .page {{ max-width:1280px; margin:0 auto; padding:24px; }}
    h1,h2,h3 {{ margin:0 0 12px; }}
    .muted {{ color:var(--muted); }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; margin:16px 0 24px; }}
    .suite-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:14px; margin:16px 0 24px; }}
    .card,.panel {{ background:var(--panel); border:1px solid var(--border); border-radius:14px; padding:16px; }}
    .metric {{ color:var(--muted); font-size:12px; margin-bottom:6px; }}
    .metric-value {{ font-size:26px; font-weight:750; }}
    .section {{ margin-top:28px; }}
    table {{ width:100%; border-collapse:collapse; min-width:980px; }}
    th,td {{ padding:12px 14px; border-bottom:1px solid var(--border); text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; }}
    tr:last-child td {{ border-bottom:0; }}
    .table-wrap {{ overflow-x:auto; border:1px solid var(--border); border-radius:14px; background:var(--panel); }}
    a {{ color:var(--blue); text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .status {{ display:inline-flex; padding:2px 10px; border-radius:999px; border:1px solid currentColor; font-size:12px; font-weight:700; }}
    .status-passed {{ color:var(--green); }} .status-failed {{ color:var(--red); }} .status-blocked {{ color:var(--amber); }}
    .delta-up {{ color:var(--green); font-weight:700; }} .delta-down {{ color:var(--red); font-weight:700; }} .delta-flat {{ color:var(--muted); }}
    .suite-card {{ display:grid; gap:12px; min-width:0; }}
    .suite-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }}
    .suite-title {{ font-weight:750; font-size:18px; }}
    .score-line {{ display:grid; grid-template-columns:52px minmax(140px,1fr) 76px; gap:10px; align-items:center; color:var(--muted); font-size:13px; }}
    .track {{ height:12px; border-radius:999px; background:#eef2f6; overflow:hidden; }}
    .fill {{ height:100%; border-radius:999px; background:linear-gradient(90deg,#175cd3,#84caff); }}
    .case-list {{ margin:6px 0 0; padding-left:18px; }}
    .advice {{ border-radius:10px; background:#f8fafc; padding:10px; font-size:13px; overflow-wrap:anywhere; }}
    .pill {{ display:inline-block; border:1px solid var(--border); border-radius:999px; padding:2px 8px; color:var(--muted); font-size:12px; }}
    .meta-row {{ display:flex; flex-wrap:wrap; gap:6px; }}
    @media (max-width:760px) {{ .page {{ padding:14px; }} .suite-grid {{ grid-template-columns:1fr; }} .score-line {{ grid-template-columns:48px minmax(100px,1fr) 70px; }} }}
  </style>
</head>
<body>
  <div class="page">
    <h1>Eval 总览</h1>
    <div class="muted">统一查看 Gate 与 Challenge 的最新结果、分数变化、失败项和基线建议。</div>
    <div class="grid">
      <div class="card"><div class="metric">Challenge 平均分</div><div class="metric-value">{_score(challenge_score)}</div><div class="muted">live 优先</div></div>
      <div class="card"><div class="metric">Gate 平均分</div><div class="metric-value">{_score(gate_score)}</div><div class="muted">scripted 优先</div></div>
      <div class="card"><div class="metric">Challenge 失败套件</div><div class="metric-value">{sum(1 for item in challenge if item.status != 'passed')}</div></div>
      <div class="card"><div class="metric">Gate 失败套件</div><div class="metric-value">{sum(1 for item in gate if item.status != 'passed')}</div></div>
    </div>
    <div class="section">
      <h2>Challenge Eval</h2>
      <div class="suite-grid">{''.join(_suite_card(item) for item in challenge) or '<div class="panel muted">暂无 Challenge 运行。</div>'}</div>
    </div>
    <div class="section">
      <h2>Gate Eval</h2>
      <div class="suite-grid">{''.join(_suite_card(item) for item in gate) or '<div class="panel muted">暂无 Gate 运行。</div>'}</div>
    </div>
    <div class="section">
      <h2>最近运行</h2>
      {_recent_table(recent)}
    </div>
  </div>
</body>
</html>
"""


def _suite_card(item: EvalReportRecord) -> str:
    compare = item.compare or {}
    failed_items = ''.join(f'<li>{_text(_case_name(case_id))}</li>' for case_id in item.failed_cases[:5])
    failed_block = f'<ul class="case-list">{failed_items}</ul>' if failed_items else '<div class="muted">无失败 case</div>'
    advice = _baseline_advice(item)
    return f"""
    <div class="card suite-card">
      <div class="suite-head">
        <div><div class="suite-title">{_text(_suite_label(item.suite_id))}</div><div class="muted">{_text(item.mode)} · {_text(item.profile)} · {_text(item.provider)}</div></div>
        {_status_badge(item.status)}
      </div>
      {_score_bar('总分', item.score)}
      <div class="muted">总分变化 {_delta(compare.get('total_score_delta'))} · 通过率变化 {_delta(compare.get('pass_rate_delta'))}</div>
      <div class="meta-row"><span class="pill">失败 case {len(item.failed_cases)}</span> <span class="pill">{_text(item.mode)}</span> <span class="pill">{_text(item.sha[:7])}</span> <span class="pill">{_text(_short_time(item.finished_at))}</span></div>
      {failed_block}
      <div class="advice">{advice}</div>
      <a href="{_text(item.summary_path)}">查看详情</a>
    </div>
    """


def _recent_table(items: list[EvalReportRecord]) -> str:
    if not items:
        return '<div class="panel muted">暂无运行记录。</div>'
    rows = []
    for item in items:
        compare = item.compare or {}
        rows.append(
            '<tr>'
            f'<td><a href="{_text(item.summary_path)}">{_text(_suite_label(item.suite_id))}</a><div class="muted">{_text(item.run_id)}</div></td>'
            f'<td>{_text(item.mode)}</td>'
            f'<td>{_status_badge(item.status)}</td>'
            f'<td>{_score(item.score)}</td>'
            f'<td>{_delta(compare.get("total_score_delta"))}</td>'
            f'<td>{len(item.failed_cases)}</td>'
            f'<td>{_text(item.profile)}</td>'
            f'<td>{_text(_short_time(item.finished_at))}</td>'
            '</tr>'
        )
    return '<div class="table-wrap"><table><thead><tr><th>套件</th><th>模式</th><th>状态</th><th>总分</th><th>变化</th><th>失败 case</th><th>模型配置</th><th>完成时间</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'


def _baseline_advice(item: EvalReportRecord) -> str:
    if item.status == 'passed':
        baseline_name = 'challenge_current' if item.suite_id.startswith('challenge_') else 'latest_passed'
        return f'基线建议：本次通过，可采纳为 {baseline_name}。命令：scripts/run_eval.py --promote-baseline-run {item.run_id} --baseline-name {baseline_name}'
    if item.suite_id.startswith('challenge_'):
        return '基线建议：Challenge 存在待提升项，保留当前人工确认基线。'
    return '基线建议：Gate 未通过，保留当前通过基线。'


def _score_bar(label: str, value: float) -> str:
    width = max(0.0, min(100.0, float(value)))
    return f'<div class="score-line"><div>{_text(label)}</div><div class="track"><div class="fill" style="width:{width}%"></div></div><div>{_score(value)}</div></div>'


def _load_records(root: Path) -> list[EvalReportRecord]:
    records: list[EvalReportRecord] = []
    for path in sorted(root.glob('eval_*/summary.json')):
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        run_id = str(payload.get('eval_run_id') or path.parent.name)
        cases = [item for item in list(payload.get('case_results') or []) if isinstance(item, dict)]
        records.append(
            EvalReportRecord(
                run_id=run_id,
                suite_id=str(payload.get('suite_id') or ''),
                mode=str(payload.get('eval_mode') or ''),
                status=str(payload.get('status') or ''),
                score=_float(payload.get('total_score')),
                pass_rate=_float(payload.get('pass_rate')),
                profile=str(payload.get('profile_name') or ''),
                provider=str(payload.get('provider_ref') or ''),
                branch=str(payload.get('git_branch') or ''),
                sha=str(payload.get('git_sha') or ''),
                finished_at=str(payload.get('finished_at') or payload.get('started_at') or ''),
                summary_path=f'/evals/reports/{html.escape(run_id)}',
                failed_cases=[str(item.get('case_id') or '') for item in cases if item.get('status') != 'passed'],
                compare=payload.get('compare_result') if isinstance(payload.get('compare_result'), dict) else None,
            )
        )
    return records


def _latest_by_suite(records: list[EvalReportRecord]) -> list[EvalReportRecord]:
    latest: dict[tuple[str, str], EvalReportRecord] = {}
    for item in records:
        key = (item.suite_id, item.mode)
        current = latest.get(key)
        if current is None or (item.finished_at, item.run_id) > (current.finished_at, current.run_id):
            latest[key] = item
    return sorted(latest.values(), key=lambda item: (item.suite_id, item.mode))


def _select_dashboard_records(records: list[EvalReportRecord]) -> list[EvalReportRecord]:
    latest_by_mode = {(item.suite_id, item.mode): item for item in _latest_by_suite(records)}
    suite_ids = sorted({item.suite_id for item in records})
    selected: list[EvalReportRecord] = []
    for suite_id in suite_ids:
        preferred_modes = ("live", "scripted") if suite_id.startswith("challenge_") else ("scripted", "live")
        fallback_modes = tuple(reversed(preferred_modes))
        candidates = [
            *(latest_by_mode.get((suite_id, mode)) for mode in preferred_modes),
            *(latest_by_mode.get((suite_id, mode)) for mode in fallback_modes),
        ]
        non_blocked = [item for item in candidates if item is not None and item.status != "blocked"]
        if non_blocked:
            selected.append(non_blocked[0])
            continue
        blocked = [item for item in candidates if item is not None]
        if blocked:
            selected.append(blocked[0])
    return selected


def _suite_label(value: str) -> str:
    return {
        'main_chain_core': '主链黄金链路',
        'main_chain_mcp': 'MCP 链路',
        'main_chain_subagent': '子代理链路',
        'memory_long_horizon': '记忆链路',
        'subagent_task_progress': '子代理进度链路',
        'subagent_external_mcp_completion': '子代理外部 MCP 完成链路',
        'ops_smoke': '运维冒烟链路',
        'challenge_memory': 'Challenge：记忆',
        'challenge_subagent': 'Challenge：子代理',
        'challenge_mcp': 'Challenge：MCP',
        'challenge_integrated': 'Challenge：集成链路',
    }.get(value, value)


def _case_name(case_id: str) -> str:
    return {
        'memory_interference_recall_cn': '记忆抗临时干扰',
        'memory_scope_isolation_cn': '记忆 scope 隔离',
        'memory_overwrite_conflict_cn': '记忆覆盖冲突处理',
        'memory_should_not_write_cn': '临时指令避免写入记忆',
        'subagent_delegation_boundary_cn': '子代理边界委派',
        'subagent_no_duplicate_dispatch_cn': '子代理避免重复派发',
        'subagent_incomplete_child_handling_cn': '子代理未完成时避免编造',
        'mcp_multi_source_repo_evidence_cn': 'MCP 多来源仓库证据',
        'mcp_empty_result_recovery_cn': 'MCP 空结果恢复',
        'mcp_tool_result_attribution_cn': 'MCP 工具结果归因',
        'integrated_memory_mcp_conflict_resolution_cn': '记忆与 MCP 冲突处理',
        'integrated_subagent_mcp_evidence_boundary_cn': '子代理与 MCP 证据边界',
    }.get(case_id, case_id)


def _status_badge(status: str) -> str:
    label = {'passed': '通过', 'failed': '待提升', 'blocked': '阻塞'}.get(status, status)
    return f'<span class="status status-{html.escape(status)}">{_text(label)}</span>'


def _delta(value: object) -> str:
    if value in (None, ''):
        return '<span class="delta-flat">-</span>'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f'<span class="delta-flat">{_text(value)}</span>'
    if number > 0:
        return f'<span class="delta-up">+{_score(number)}</span>'
    if number < 0:
        return f'<span class="delta-down">{_score(number)}</span>'
    return '<span class="delta-flat">0</span>'


def _score(value: float | None) -> str:
    if value is None:
        return '-'
    number = round(float(value), 4)
    if number.is_integer():
        return str(int(number))
    return str(number)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _short_time(value: str) -> str:
    if not value:
        return '-'
    return value.replace('T', ' ')[:19]


def _text(value: object) -> str:
    if value in (None, ''):
        return '-'
    return html.escape(str(value))
