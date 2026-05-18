from __future__ import annotations

import html
import json

from marten_runtime.evals.models import EvalCaseResult, EvalRunSummary


def render_summary_html(
    *,
    summary_payload: dict[str, object],
    case_results: list[EvalCaseResult],
    compare_index: dict[str, dict[str, object]],
) -> str:
    summary = EvalRunSummary.model_validate(
        {
            key: value
            for key, value in summary_payload.items()
            if key in EvalRunSummary.model_fields
        }
    )
    compare_result = summary_payload.get('compare_result')
    stability_result = summary_payload.get('stability_result')
    provider_reliability = summary_payload.get('provider_reliability')
    blocked_reason = summary_payload.get('blocked_reason')
    compare_stats = _compare_stats(compare_index, case_results)
    rows = '\n'.join(
        _render_case_row(
            result=result,
            comparison=compare_index.get(result.case_id),
        )
        for result in case_results
    )
    details = '\n'.join(
        _render_case_detail(
            result=result,
            comparison=compare_index.get(result.case_id),
        )
        for result in case_results
    )
    compare_block = _render_compare_block(compare_result)
    challenge_delta_block = _render_challenge_delta_block(summary, compare_result)
    challenge_focus_block = _render_challenge_focus_block(summary, case_results, compare_index, compare_result, stability_result)
    history_block = _render_history_block(stability_result, compare_result)
    stability_block = _render_stability_block(stability_result)
    provider_reliability_block = _render_provider_reliability_block(provider_reliability)
    blocked_block = (
        f'<div class="panel blocked"><strong>blocked_reason</strong><div>{_text(blocked_reason)}</div></div>'
        if blocked_reason
        else ''
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>评测报告：{_text(_run_label(summary.eval_run_id))}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --border: #dbe2ea;
      --passed: #18794e;
      --failed: #b42318;
      --blocked: #9a6700;
      --delta-up: #18794e;
      --delta-down: #b42318;
      --delta-flat: #667085;
      --link: #175cd3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .page {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .muted {{ color: var(--muted); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin: 16px 0 24px;
    }}
    .card, .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
    }}
    .metric {{
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 6px;
      letter-spacing: .02em;
    }}
    .metric-value {{
      font-size: 24px;
      font-weight: 700;
    }}
    .status {{
      display: inline-flex;
      align-items: center;
      padding: 2px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid currentColor;
    }}
    .status-passed {{ color: var(--passed); }}
    .status-failed {{ color: var(--failed); }}
    .status-blocked {{ color: var(--blocked); }}
    .table-wrap {{
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      margin-top: 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1180px;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      font-size: 12px;
      color: var(--muted);
      letter-spacing: .02em;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    a {{ color: var(--link); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .delta-up {{ color: var(--delta-up); font-weight: 700; }}
    .delta-down {{ color: var(--delta-down); font-weight: 700; }}
    .delta-flat {{ color: var(--delta-flat); }}
    details {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px 16px;
      margin-top: 12px;
    }}
    summary {{
      cursor: pointer;
      font-weight: 600;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #0b1020;
      color: #d1e0ff;
      padding: 12px;
      border-radius: 8px;
      overflow-x: auto;
      margin: 8px 0 0;
    }}
    .kv {{
      display: grid;
      grid-template-columns: 180px 1fr;
      gap: 8px 12px;
      font-size: 14px;
    }}
    .section {{ margin-top: 28px; }}
    .compare-list {{
      margin: 8px 0 0;
      padding-left: 18px;
    }}
    .blocked {{
      border-color: #f5d08a;
      background: #fff8eb;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 16px;
    }}
    .chip {{
      display: inline-flex;
      gap: 6px;
      align-items: center;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--text);
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 13px;
      cursor: pointer;
    }}
    .chip.active {{
      border-color: #175cd3;
      color: #175cd3;
      background: #eef4ff;
    }}
    .case-row-hidden {{ display: none; }}
    .change-improvement td:first-child,
    .change-improvement td:nth-child(6) {{ border-left: 3px solid #12b76a; }}
    .change-regression td:first-child,
    .change-regression td:nth-child(6) {{ border-left: 3px solid #f04438; }}
    .change-new_case td:first-child,
    .change-removed_case td:first-child {{ border-left: 3px solid #175cd3; }}
    .change-unchanged {{ opacity: .82; }}

    .case-title {{ font-weight: 700; color: var(--text); }}
    .case-id {{ display: block; margin-top: 3px; font-size: 12px; color: var(--muted); font-weight: 400; }}
    summary .case-id {{ display: inline-block; margin-left: 10px; }}
    .challenge-focus {{ border-color: #b2ccff; box-shadow: 0 12px 28px rgba(16,24,40,.06); }}
    .score-chart {{ display: grid; gap: 14px; margin-top: 10px; }}
    .score-card {{ border: 1px solid var(--border); border-radius: 14px; padding: 14px; background: #fbfcff; }}
    .score-head {{ display: grid; grid-template-columns: minmax(220px, 1fr) auto auto auto; gap: 14px; align-items: center; margin-bottom: 12px; }}
    .score-name {{ font-weight: 700; }}
    .score-chip {{ min-width: 96px; text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }}
    .score-change {{ min-width: 82px; text-align: right; }}
    .score-bars {{ display: grid; gap: 8px; }}
    .score-bar-row {{ display: grid; grid-template-columns: 42px minmax(240px, 1fr) 70px; gap: 12px; align-items: center; font-size: 12px; color: var(--muted); }}
    .score-track {{ height: 16px; border-radius: 999px; background: #eef2f6; overflow: hidden; }}
    .score-fill-current {{ height: 100%; border-radius: 999px; background: linear-gradient(90deg, #175cd3, #84caff); }}
    .score-fill-baseline {{ height: 100%; border-radius: 999px; background: #98a2b3; }}
    .legend {{ display: flex; gap: 14px; align-items: center; margin: 4px 0 12px; color: var(--muted); font-size: 13px; }}
    .legend span {{ display: inline-flex; gap: 6px; align-items: center; }}
    .legend-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 999px; }}
    .case-compact-table table {{ min-width: 760px; }}
    @media (max-width: 760px) {{
      .page {{ padding: 14px; }}
      .score-head {{ grid-template-columns: 1fr; gap: 6px; }}
      .score-chip, .score-change {{ text-align: left; min-width: 0; }}
      .score-bar-row {{ grid-template-columns: 42px minmax(120px, 1fr) 58px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <h1>{_text(_suite_label(summary.suite_id))}</h1>
    <div class="muted">{_text(_run_label(summary.eval_run_id))}</div>
    <details style="margin-top:10px;">
      <summary>运行元信息</summary>
      <div class="kv" style="margin-top:12px;">
        <div>套件</div><div>{html.escape(summary.suite_id)}</div>
        <div>模式</div><div>{html.escape(summary.eval_mode)}</div>
        <div>分支</div><div>{html.escape(summary.git_branch)}</div>
        <div>提交</div><div>{html.escape(summary.git_sha)}</div>
        <div>原始运行 ID</div><div>{html.escape(summary.eval_run_id)}</div>
      </div>
    </details>
    <div class="grid">
      <div class="card"><div class="metric">运行状态</div><div class="metric-value">{_status_badge(summary.status, challenge=str(summary.suite_id or "").startswith("challenge_"))}</div></div>
      <div class="card"><div class="metric">总分</div><div class="metric-value">{summary.total_score}</div></div>
      <div class="card"><div class="metric">通过率</div><div class="metric-value">{summary.pass_rate}</div></div>
      <div class="card"><div class="metric">模型配置</div><div class="metric-value" style="font-size:18px;">{html.escape(summary.profile_name)}</div></div>
      <div class="card"><div class="metric">提供方</div><div class="metric-value" style="font-size:18px;">{_text(summary.provider_ref)}</div></div>
      <div class="card"><div class="metric">用例数</div><div class="metric-value">{len(case_results)}</div></div>
    </div>
    {blocked_block}
    {compare_block}
    {challenge_delta_block}
    {challenge_focus_block}
    {history_block}
    {stability_block}
    {provider_reliability_block}
    <div class="section">
      <h2>用例总览</h2>
      <div class="toolbar">
        <button class="chip active" type="button" data-filter="all">全部 <strong>{compare_stats['all']}</strong></button>
        <button class="chip" type="button" data-filter="changed">仅看变化 <strong>{compare_stats['changed']}</strong></button>
        <button class="chip" type="button" data-filter="regression">回归 <strong>{compare_stats['regression']}</strong></button>
        <button class="chip" type="button" data-filter="improvement">改进 <strong>{compare_stats['improvement']}</strong></button>
        <button class="chip" type="button" data-filter="unchanged">无变化 <strong>{compare_stats['unchanged']}</strong></button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>用例</th>
              <th>状态</th>
              <th>当前分数</th>
              <th>基线分数</th>
              <th>分数变化</th>
              <th>变化类型</th>
              <th>run_id</th>
              <th>trace_id</th>
              <th>工件</th>
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </div>
    </div>
    <div class="section">
      <h2>用例详情</h2>
      {details or '<div class="panel">No case results.</div>'}
    </div>
  </div>
  <script>
    (() => {{
      const buttons = Array.from(document.querySelectorAll('[data-filter]'));
      const rows = Array.from(document.querySelectorAll('tbody tr[data-change-kind]'));
      const applyFilter = (filter) => {{
        for (const button of buttons) {{
          button.classList.toggle('active', button.dataset.filter === filter);
        }}
        for (const row of rows) {{
          const kind = row.dataset.changeKind || 'unchanged';
          const changed = kind !== 'unchanged';
          const visible =
            filter === 'all' ? true :
            filter === 'changed' ? changed :
            filter === kind;
          row.classList.toggle('case-row-hidden', !visible);
        }}
      }};
      for (const button of buttons) {{
        button.addEventListener('click', () => applyFilter(button.dataset.filter || 'all'));
      }}
      applyFilter('all');
    }})();
  </script>
</body>
</html>
"""

def _render_challenge_focus_block(
    summary: EvalRunSummary,
    case_results: list[EvalCaseResult],
    compare_index: dict[str, dict[str, object]],
    compare_result: object,
    stability_result: object,
) -> str:
    if not str(summary.suite_id or "").startswith("challenge_"):
        return ""
    failed_cases = [item for item in case_results if item.status != "passed"]
    changed_cases = [item for item in case_results if str((compare_index.get(item.case_id) or {}).get("change_kind") or "unchanged") != "unchanged"]
    focus_cases = failed_cases or changed_cases or case_results
    component_summary = []
    if isinstance(compare_result, dict):
        component_summary = [item for item in list(compare_result.get("component_summary") or []) if isinstance(item, dict)]
    stability_cases = []
    if isinstance(stability_result, dict):
        stability_cases = [item for item in list(stability_result.get("cases") or []) if isinstance(item, dict) and item.get("unstable")]
    return f"""
    <div class="panel challenge-focus">
      <h2>Challenge 重点视图</h2>
      <div class="muted">优先展示待提升用例、变化用例、组件变化和 rubric 未通过项。</div>
      <div class="grid" style="margin-bottom:16px;">
        <div class="card"><div class="metric">待提升用例</div><div class="metric-value">{len(failed_cases)}</div></div>
        <div class="card"><div class="metric">变化用例</div><div class="metric-value">{len(changed_cases)}</div></div>
        <div class="card"><div class="metric">波动用例</div><div class="metric-value">{len(stability_cases)}</div></div>
        <div class="card"><div class="metric">当前通过率</div><div class="metric-value">{summary.pass_rate}</div></div>
      </div>
      <h3>待提升组件与 rubric</h3>
      {_render_challenge_focus_cases(focus_cases, compare_index)}
      <h3 style="margin-top:16px;">组件变化</h3>
      {_render_component_summary(component_summary)}
      <h3 style="margin-top:16px;">Case 分数对比</h3>
      {_render_case_score_chart(case_results, compare_index)}
      <h3 style="margin-top:16px;">组件分数对比</h3>
      {_render_component_score_chart(component_summary)}
    </div>
    """


def _render_challenge_focus_cases(
    case_results: list[EvalCaseResult],
    compare_index: dict[str, dict[str, object]],
) -> str:
    if not case_results:
        return '<div class="muted">none</div>'
    rows = [
        '<div class="table-wrap"><table><thead><tr>'
        '<th>用例</th><th>状态</th><th>分数</th><th>变化</th><th>待提升组件</th><th>未通过 rubric</th>'
        '</tr></thead><tbody>'
    ]
    for result in case_results:
        comparison = compare_index.get(result.case_id) or {}
        failed_components = _failed_component_labels(result)
        failed_rubrics = _failed_rubric_labels(result)
        rows.append(
            '<tr>'
            f'<td>{_case_link(result)}</td>'
            f'<td>{_status_badge(result.status, challenge=True)}</td>'
            f'<td>{_text(result.total_score)}</td>'
            f'<td>{_delta(comparison.get("total_score_delta"))}</td>'
            f'<td>{_text(", ".join(failed_components) or "-")}</td>'
            f'<td>{_text(", ".join(failed_rubrics[:8]) or "-")}</td>'
            '</tr>'
        )
    rows.append('</tbody></table></div>')
    return ''.join(rows)


def _failed_component_labels(result: EvalCaseResult) -> list[str]:
    labels: list[str] = []
    for item in list((result.score_breakdown_json or {}).get("components") or []):
        if not isinstance(item, dict) or item.get("passed") is True:
            continue
        label = str(item.get("label") or item.get("key") or "").strip()
        if label:
            labels.append(label)
    return labels


def _failed_rubric_labels(result: EvalCaseResult) -> list[str]:
    labels: list[str] = []
    for component in list((result.score_breakdown_json or {}).get("components") or []):
        if not isinstance(component, dict):
            continue
        details = component.get("details") if isinstance(component.get("details"), dict) else {}
        for rubric in list((details or {}).get("rubric_items") or []):
            if not isinstance(rubric, dict) or rubric.get("passed") is True:
                continue
            component_key = str(component.get("key") or "").strip()
            rubric_id = str(rubric.get("id") or "").strip()
            label = f"{component_key}.{rubric_id}" if component_key and rubric_id else rubric_id or component_key
            if label:
                labels.append(label)
    return labels


def _render_history_block(stability_result: object, compare_result: object) -> str:
    run_ids: list[str] = []
    if isinstance(stability_result, dict):
        run_ids.extend(str(item) for item in list(stability_result.get("history_eval_run_ids") or []) if str(item).strip())
    if isinstance(compare_result, dict):
        baseline = str(compare_result.get("baseline_eval_run_id") or "").strip()
        if baseline and baseline not in run_ids:
            run_ids.append(baseline)
    if not run_ids:
        return '<div class="panel"><h2>历史报告</h2><div class="muted">暂无历史评估报告。</div></div>'
    links = ''.join(
        f'<li><a href="/evals/reports/{html.escape(run_id)}">{_text(_run_label(run_id))}</a> <span class="muted">{_text(run_id)}</span></li>'
        for run_id in run_ids
    )
    return f"""
    <div class="panel">
      <h2>历史报告</h2>
      <div class="muted">同套件历史运行和当前基线，可用于查看分数、组件和 case 明细变化。</div>
      <ul class="compare-list">{links}</ul>
    </div>
    """


def _render_challenge_delta_block(summary: EvalRunSummary, compare_result: object) -> str:
    if not str(summary.suite_id or "").startswith("challenge_") or not isinstance(compare_result, dict):
        return ""
    return f"""
    <div class="panel">
      <h2>Challenge Delta</h2>
      <div class="kv">
        <div>total_score_delta</div><div>{_delta(compare_result.get('total_score_delta'))}</div>
        <div>pass_rate_delta</div><div>{_delta(compare_result.get('pass_rate_delta'))}</div>
        <div>token_total_delta</div><div>{_delta(compare_result.get('token_total_delta'))}</div>
        <div>tool_calls_delta</div><div>{_delta(compare_result.get('tool_calls_delta'))}</div>
        <div>llm_requests_delta</div><div>{_delta(compare_result.get('llm_requests_delta'))}</div>
      </div>
    </div>
    """


def _render_compare_block(compare_result: object) -> str:
    if not isinstance(compare_result, dict):
        return '<div class="panel"><h2>基线对比</h2><div class="muted">暂无基线。</div></div>'
    regressions = [item for item in list(compare_result.get('regressions') or []) if isinstance(item, dict)]
    improvements = [item for item in list(compare_result.get('improvements') or []) if isinstance(item, dict)]
    component_summary = [
        item for item in list(compare_result.get('component_summary') or []) if isinstance(item, dict)
    ]
    unchanged = len(
        [
            item
            for item in list(compare_result.get('cases') or [])
            if isinstance(item, dict) and item.get('change_kind') == 'unchanged'
        ]
    )
    same_case_regressions = [item for item in regressions if item.get('change_kind') != 'removed_case']
    same_case_improvements = [item for item in improvements if item.get('change_kind') != 'new_case']
    removed_cases = [item for item in regressions if item.get('change_kind') == 'removed_case']
    new_cases = [item for item in improvements if item.get('change_kind') == 'new_case']
    structure_changed = bool(new_cases or removed_cases)
    headline_metric = (
        f'<div class="card"><div class="metric">对比状态</div><div class="metric-value" style="font-size:18px;">套件结构变化</div></div>'
        if structure_changed
        else f'<div class="card"><div class="metric">总分变化</div><div class="metric-value">{_delta(compare_result.get('total_score_delta'))}</div></div>'
    )
    pass_rate_metric = (
        f'<div class="card"><div class="metric">分数对比</div><div class="metric-value" style="font-size:18px;">看同名 case</div></div>'
        if structure_changed
        else f'<div class="card"><div class="metric">通过率变化</div><div class="metric-value">{_delta(compare_result.get('pass_rate_delta'))}</div></div>'
    )
    dynamic_badge = '<span class="status status-passed">当前基线动态对比</span>' if compare_result.get("compare_mode") == "current_baseline" else ""
    dynamic_note = str(compare_result.get("compare_note") or "")
    return f"""
    <div class="panel">
      <h2>本次结果与基线</h2>
      {dynamic_badge}
      {f'<div class="muted">{_text(dynamic_note)}</div>' if dynamic_note else ''}
      <div class="muted">基线来源：{_text(_baseline_source_label(compare_result.get('baseline_source')))}。新增和移除 case 按套件变化展示；同名 case 用于判断分数升降。</div>
      <div class="muted">当前基线 ID：<code>{_text(compare_result.get('baseline_eval_run_id'))}</code></div>
      <div class="grid" style="margin-bottom:12px;">
        {headline_metric}
        {pass_rate_metric}
        <div class="card"><div class="metric">同名下降</div><div class="metric-value">{len(same_case_regressions)}</div></div>
        <div class="card"><div class="metric">同名提升</div><div class="metric-value">{len(same_case_improvements)}</div></div>
        <div class="card"><div class="metric">新增 / 移除</div><div class="metric-value">{len(new_cases)} / {len(removed_cases)}</div></div>
      </div>
      <details>
        <summary>基线运行信息</summary>
        <div class="kv" style="margin-top:12px;">
          <div>基线运行</div><div>{_text(_run_label(str(compare_result.get('baseline_eval_run_id') or '')))}</div>
          <div>基线原始 ID</div><div>{_text(compare_result.get('baseline_eval_run_id'))}</div>
          <div>基线来源</div><div>{_text(_baseline_source_label(compare_result.get('baseline_source')))}</div>
          <div>无变化用例数</div><div>{unchanged}</div>
          <div>原始总分变化</div><div>{_delta(compare_result.get('total_score_delta'))}</div>
          <div>原始通过率变化</div><div>{_delta(compare_result.get('pass_rate_delta'))}</div>
        </div>
      </details>
      <h3 style="margin-top:16px;">同名下降</h3>
      {_render_compare_list(same_case_regressions)}
      <h3 style="margin-top:16px;">同名提升</h3>
      {_render_compare_list(same_case_improvements)}
      <h3 style="margin-top:16px;">新增用例</h3>
      {_render_case_set_change_list(new_cases, kind='new')}
      <h3 style="margin-top:16px;">移除用例</h3>
      {_render_case_set_change_list(removed_cases, kind='removed')}
      <h3 style="margin-top:16px;">组件汇总</h3>
      {_render_component_summary(component_summary)}
    </div>
    """


def _render_case_set_change_list(items: list[dict[str, object]], *, kind: str) -> str:
    if not items:
        return '<div class="muted">none</div>'
    label = '新增' if kind == 'new' else '移除'
    rows = ['<div class="table-wrap case-compact-table"><table><thead><tr><th>用例</th><th>类型</th><th>分数</th></tr></thead><tbody>']
    for item in items:
        case_id = str(item.get('case_id') or '')
        score = item.get('current_total_score') if kind == 'new' else item.get('baseline_total_score')
        rows.append(
            '<tr>'
            f'<td><div class="case-title">{_text(_case_display_name_from_id(case_id))}</div><div class="case-id">{_text(case_id)}</div></td>'
            f'<td>{label}</td>'
            f'<td>{_text(score)}</td>'
            '</tr>'
        )
    rows.append('</tbody></table></div>')
    return ''.join(rows)

def _render_stability_block(stability_result: object) -> str:
    if not isinstance(stability_result, dict):
        return '<div class="panel"><h2>稳定性观察</h2><div class="muted">sample_size=0</div></div>'
    cases = [item for item in list(stability_result.get('cases') or []) if isinstance(item, dict)]
    unstable_cases = [item for item in cases if item.get('unstable')]
    components = [item for item in list(stability_result.get('components') or []) if isinstance(item, dict)]
    unstable_components = [item for item in components if item.get('unstable')]
    return f"""
    <div class="panel">
      <h2>稳定性观察</h2>
      <div class="kv">
        <div>样本数</div><div>{_text(stability_result.get('sample_size'))}</div>
        <div>窗口大小</div><div>{_text(stability_result.get('window_size'))}</div>
        <div>总分波动</div><div>{_stats_inline(stability_result.get('total_score'))}</div>
        <div>通过率波动</div><div>{_stats_inline(stability_result.get('pass_rate'))}</div>
        <div>总 token 波动</div><div>{_stats_inline(stability_result.get('token_total'))}</div>
        <div>回退占比</div><div>{_text(stability_result.get('failover_rate'))}</div>
        <div>波动用例数</div><div>{len(unstable_cases)}</div>
        <div>波动组件数</div><div>{len(unstable_components)}</div>
      </div>
      <h3 style="margin-top:16px;">波动用例</h3>
      {_render_stability_cases(unstable_cases)}
      <h3 style="margin-top:16px;">稳定性组件</h3>
      {_render_stability_components(components)}
    </div>
    """


def _render_provider_reliability_block(provider_reliability: object) -> str:
    if not isinstance(provider_reliability, dict):
        return '<div class="panel"><h2>Provider 评估</h2><div class="muted">暂无 provider 稳定性摘要。</div></div>'
    latest_runs = [
        item for item in list(provider_reliability.get('latest_runs') or []) if isinstance(item, dict)
    ]
    top_error_kinds = [
        item for item in list(provider_reliability.get('top_error_kinds') or []) if isinstance(item, dict)
    ]
    error_text = ', '.join(
        f"{_text(item.get('error_kind'))}: {_text(item.get('count'))}" for item in top_error_kinds
    )
    retry_count = _int_value(provider_reliability.get('retry_count'))
    fallback_count = _int_value(provider_reliability.get('fallback_count'))
    provider_error_count = _int_value(provider_reliability.get('provider_error_count'))
    empty_output_count = _int_value(provider_reliability.get('empty_output_count'))
    status_label, status_note = _provider_health_status(
        retry_count=retry_count,
        fallback_count=fallback_count,
        provider_error_count=provider_error_count,
        empty_output_count=empty_output_count,
    )
    return f"""
    <div class="panel">
      <h2>Provider 评估</h2>
      <div class="muted">本次评测报告中的模型服务稳定性摘要。</div>
      <div class="kv">
        <div>Provider 状态</div><div>{_text(status_label)} · {_text(status_note)}</div>
        <div>窗口大小</div><div>{_text(provider_reliability.get('window_size'))}</div>
        <div>运行数</div><div>{_text(provider_reliability.get('run_count'))}</div>
        <div>重试</div><div>{retry_count}</div>
        <div>回退</div><div>{fallback_count}</div>
        <div>错误</div><div>{provider_error_count}</div>
        <div>空输出</div><div>{empty_output_count}</div>
        <div>最近最终 provider</div><div>{_text(provider_reliability.get('latest_final_provider_ref'))}</div>
        <div>主要错误类型</div><div>{error_text or '-'}</div>
      </div>
      <h3 style="margin-top:16px;">最近 runs</h3>
      {_render_provider_reliability_runs(latest_runs)}
    </div>
    """


def _render_provider_reliability_runs(items: list[dict[str, object]]) -> str:
    if not items:
        return '<div class="muted">none</div>'
    rows = [
        '<div class="table-wrap"><table><thead><tr>'
        '<th>运行</th><th>状态</th><th>重试</th><th>回退</th><th>错误</th><th>空输出</th><th>最终 provider</th>'
        '</tr></thead><tbody>'
    ]
    for item in items:
        rows.append(
            '<tr>'
            f"<td>{_text(_run_label(str(item.get('run_id') or '')))}</td>"
            f"<td>{_text(item.get('status'))}</td>"
            f"<td>{_text(item.get('retry_count'))}</td>"
            f"<td>{_text(item.get('fallback_count'))}</td>"
            f"<td>{_text(item.get('provider_error_count'))}</td>"
            f"<td>{_text(item.get('empty_output_count'))}</td>"
            f"<td>{_text(item.get('final_provider_ref'))}</td>"
            '</tr>'
        )
    rows.append('</tbody></table></div>')
    return ''.join(rows)


def _render_compare_list(items: list[object]) -> str:
    if not items:
        return '<div class="muted">none</div>'
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get('case_id') or '')
        rows.append(
            f"<li><strong>{_text(_case_display_name_from_id(case_id))}</strong> <span class=\"case-id\">{_text(case_id)}</span> · {_text(_change_kind_label(str(item.get('change_kind') or '')))} · {_delta(item.get('total_score_delta'))}</li>"
        )
    return f"<ul class=\"compare-list\">{''.join(rows) or '<li>none</li>'}</ul>"


def _render_case_row(
    *,
    result: EvalCaseResult,
    comparison: dict[str, object] | None,
) -> str:
    change_kind = str(comparison.get('change_kind') or 'unchanged') if isinstance(comparison, dict) else 'unchanged'
    baseline_score = comparison.get('baseline_total_score') if isinstance(comparison, dict) else None
    current_score = comparison.get('current_total_score') if isinstance(comparison, dict) else result.total_score
    delta = comparison.get('total_score_delta') if isinstance(comparison, dict) else None
    return (
        f"<tr data-change-kind=\"{html.escape(change_kind)}\" class=\"change-{html.escape(change_kind)}\">"
        f"<td>{_case_link(result)}</td>"
        f"<td>{_status_badge(result.status, challenge=_is_challenge_result(result))}</td>"
        f"<td>{_text(current_score)}</td>"
        f"<td>{_text(baseline_score)}</td>"
        f"<td>{_delta(delta)}</td>"
        f"<td>{_text(_change_kind_label(change_kind))}</td>"
        f"<td>{_text(result.run_id)}</td>"
        f"<td>{_text(result.trace_id)}</td>"
        f"<td><a href=\"cases/{html.escape(result.case_id)}.json\">cases/{html.escape(result.case_id)}.json</a></td>"
        "</tr>"
    )


def _render_case_detail(
    *,
    result: EvalCaseResult,
    comparison: dict[str, object] | None,
) -> str:
    delta = comparison.get('total_score_delta') if isinstance(comparison, dict) else None
    baseline_score = comparison.get('baseline_total_score') if isinstance(comparison, dict) else None
    current_score = comparison.get('current_total_score') if isinstance(comparison, dict) else result.total_score
    compare_meta = (
        f"<div class=\"muted\" style=\"margin-top:8px;\">变化类型={_text(_change_kind_label(str(comparison.get('change_kind') or '')))} · 分数变化={_delta(delta)}</div>"
        if isinstance(comparison, dict)
        else ""
    )
    component_rows = _render_component_comparisons(
        list(comparison.get("components") or []) if isinstance(comparison, dict) else []
    )
    return f"""
    <details id="case-{html.escape(result.case_id)}">
      <summary>{_text(_case_display_name(result))} · {_status_label(result.status, challenge=_is_challenge_result(result))} · 分数={result.total_score}<span class="case-id">{html.escape(result.case_id)}</span></summary>
      {compare_meta}
      <div class="kv" style="margin-top:12px;">
        <div>当前分数</div><div>{_text(current_score)}</div>
        <div>基线分数</div><div>{_text(baseline_score)}</div>
        <div>run_id</div><div>{_text(result.run_id)}</div>
        <div>trace_id</div><div>{_text(result.trace_id)}</div>
        <div>LLM 请求数</div><div>{result.llm_request_count}</div>
        <div>工具调用数</div><div>{result.tool_calls_count}</div>
        <div>耗时 ms</div><div>{result.duration_ms}</div>
        <div>工件</div><div><a href="cases/{html.escape(result.case_id)}.json">cases/{html.escape(result.case_id)}.json</a></div>
      </div>
      <h3 style="margin-top:16px;">组件对比</h3>
      {component_rows}
      <h3 style="margin-top:16px;">最终输出</h3>
      <pre>{html.escape(result.final_text or '')}</pre>
      <details style="margin-top:16px;">
        <summary>评分原始 JSON</summary>
        <pre>{html.escape(json.dumps(result.score_breakdown_json, ensure_ascii=False, indent=2))}</pre>
      </details>
      <details>
        <summary>诊断原始 JSON</summary>
        <pre>{html.escape(json.dumps(result.diagnostics_json, ensure_ascii=False, indent=2))}</pre>
      </details>
    </details>
    """


def _compare_stats(
    compare_index: dict[str, dict[str, object]],
    case_results: list[EvalCaseResult],
) -> dict[str, int]:
    stats = {
        'all': len(case_results),
        'changed': 0,
        'regression': 0,
        'improvement': 0,
        'unchanged': 0,
    }
    for result in case_results:
        kind = str((compare_index.get(result.case_id) or {}).get('change_kind') or 'unchanged')
        if kind == 'unchanged':
            stats['unchanged'] += 1
            continue
        stats['changed'] += 1
        if kind == 'regression':
            stats['regression'] += 1
        elif kind == 'improvement':
            stats['improvement'] += 1
    return stats


def _render_component_summary(items: list[dict[str, object]]) -> str:
    if not items:
        return '<div class="muted">none</div>'
    rows = [
        "<div class=\"table-wrap\"><table><thead><tr>"
        "<th>组件</th><th>当前分数</th><th>基线分数</th><th>变化</th><th>覆盖用例数</th>"
        "</tr></thead><tbody>"
    ]
    for item in items:
        rows.append(
            "<tr>"
            f"<td>{_text(item.get('label') or item.get('key'))}</td>"
            f"<td>{_text(item.get('current_score'))}</td>"
            f"<td>{_text(item.get('baseline_score'))}</td>"
            f"<td>{_delta(item.get('delta'))}</td>"
            f"<td>{_text(item.get('case_count'))}</td>"
            "</tr>"
        )
    rows.append("</tbody></table></div>")
    return "".join(rows)


def _render_component_comparisons(items: list[object]) -> str:
    if not items:
        return '<div class="muted">none</div>'
    rows = [
        "<div class=\"table-wrap\"><table><thead><tr>"
        "<th>组件</th><th>当前分数</th><th>基线分数</th><th>变化</th><th>当前通过</th><th>基线通过</th>"
        "</tr></thead><tbody>"
    ]
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_text(item.get('label') or item.get('key'))}</td>"
            f"<td>{_text(item.get('current_score'))}</td>"
            f"<td>{_text(item.get('baseline_score'))}</td>"
            f"<td>{_delta(item.get('delta'))}</td>"
            f"<td>{_text(item.get('current_passed'))}</td>"
            f"<td>{_text(item.get('baseline_passed'))}</td>"
            "</tr>"
        )
    rows.append("</tbody></table></div>")
    return "".join(rows)


def _render_stability_cases(items: list[dict[str, object]]) -> str:
    if not items:
        return '<div class="muted">none</div>'
    rows = [
        "<div class=\"table-wrap\"><table><thead><tr>"
        "<th>用例</th><th>分数波动</th><th>回退占比</th><th>锚点强度</th><th>原因</th>"
        "</tr></thead><tbody>"
    ]
    for item in items:
        score = item.get("score") if isinstance(item.get("score"), dict) else {}
        rows.append(
            "<tr>"
            f"<td><div class=\"case-title\">{_text(_case_display_name_from_id(str(item.get('case_id') or '')))}</div><div class=\"case-id\">{_text(item.get('case_id'))}</div></td>"
            f"<td>{_stats_inline(score)}</td>"
            f"<td>{_text(item.get('failover_rate'))}</td>"
            f"<td>{_text(item.get('anchor_strength'))}</td>"
            f"<td>{_text(', '.join(list(item.get('unstable_reasons') or [])))}</td>"
            "</tr>"
        )
    rows.append("</tbody></table></div>")
    return "".join(rows)


def _render_stability_components(items: list[dict[str, object]]) -> str:
    if not items:
        return '<div class="muted">none</div>'
    rows = [
        "<div class=\"table-wrap\"><table><thead><tr>"
        "<th>组件</th><th>分数波动</th><th>是否波动</th>"
        "</tr></thead><tbody>"
    ]
    for item in items:
        rows.append(
            "<tr>"
            f"<td>{_text(item.get('label') or item.get('key'))}</td>"
            f"<td>{_stats_inline(item.get('score'))}</td>"
            f"<td>{_text(item.get('unstable'))}</td>"
            "</tr>"
        )
    rows.append("</tbody></table></div>")
    return "".join(rows)


def _case_meta(result: EvalCaseResult) -> dict[str, object]:
    raw = (result.score_breakdown_json or {}).get("case_meta")
    return dict(raw) if isinstance(raw, dict) else {}


def _case_display_name(result: EvalCaseResult) -> str:
    meta = _case_meta(result)
    display = str(meta.get("display_name") or "").strip()
    if display:
        return display
    mapped = _case_display_name_from_id(result.case_id)
    if mapped != result.case_id:
        return mapped
    description = str(meta.get("description") or "").strip()
    if description:
        return description
    return result.case_id


def _case_display_name_from_id(case_id: str) -> str:
    return _CASE_DISPLAY_NAMES.get(case_id, case_id)


def _case_link(result: EvalCaseResult) -> str:
    title = _text(_case_display_name(result))
    case_id = html.escape(result.case_id)
    return f'<a href="#case-{case_id}"><div class="case-title">{title}</div><div class="case-id">{case_id}</div></a>'


def _is_challenge_result(result: EvalCaseResult) -> bool:
    return str(result.family or "") == "challenge" or str(result.eval_run_id or "").startswith("eval_challenge_")


def _baseline_source_label(value: object) -> str:
    raw = str(value or "").strip()
    if raw == "latest_passed":
        return "最近一次通过的同套件运行"
    if raw.startswith("named:"):
        return f"命名基线 {raw.removeprefix('named:')}"
    if raw == "explicit_run":
        return "手动指定运行"
    return raw or "-"


def _change_kind_label(change_kind: str) -> str:
    return {
        "improvement": "提升",
        "regression": "下降",
        "unchanged": "持平",
        "new_case": "新增用例",
        "removed_case": "移除用例",
    }.get(str(change_kind), str(change_kind))


def _status_label(status: str, *, challenge: bool = False) -> str:
    if challenge:
        return {"passed": "达标", "failed": "待提升", "blocked": "阻塞"}.get(str(status), str(status))
    return {"passed": "通过", "failed": "待提升", "blocked": "阻塞"}.get(str(status), str(status))


def _status_badge(status: str, *, challenge: bool = False) -> str:
    raw = html.escape(str(status))
    return f'<span class="status status-{raw}">{_text(_status_label(str(status), challenge=challenge))}</span>'


def _render_case_score_chart(
    case_results: list[EvalCaseResult],
    compare_index: dict[str, dict[str, object]],
) -> str:
    comparable: list[tuple[EvalCaseResult, dict[str, object]]] = []
    new_cases: list[EvalCaseResult] = []
    for result in case_results:
        comparison = compare_index.get(result.case_id) or {}
        if comparison and comparison.get("baseline_total_score") is not None:
            comparable.append((result, comparison))
            continue
        new_cases.append(result)
    if not comparable and not new_cases:
        return '<div class="muted">none</div>'
    baseline_id = _baseline_id_from_compare_index(compare_index)
    rows = [
        f'<div class="muted">基线 ID：<code>{_text(baseline_id)}</code></div>',
        _score_chart_legend(),
        '<div class="score-chart">',
    ]
    if comparable:
        for result, comparison in comparable:
            current = _safe_score(comparison.get("current_total_score"), result.total_score)
            baseline = _safe_score(comparison.get("baseline_total_score"), 0.0)
            rows.append(_render_score_card(_case_display_name(result), current, baseline))
    else:
        rows.append('<div class="muted">本次 case 都是新增，暂无同名基线分数。</div>')
    rows.append('</div>')
    if new_cases:
        rows.append('<div class="muted" style="margin-top:10px;">新增 case：')
        rows.append('、'.join(_text(_case_display_name(item)) for item in new_cases))
        rows.append('</div>')
    return ''.join(rows)


def _render_component_score_chart(items: list[dict[str, object]]) -> str:
    comparable = [item for item in items if item.get("current_score") is not None and item.get("baseline_score") is not None]
    if not comparable:
        return '<div class="muted">暂无同名 case 的组件基线，组件对比会在 case 集合稳定后显示。</div>'
    rows = [_score_chart_legend(), '<div class="score-chart">']
    for item in comparable:
        label = str(item.get("label") or item.get("key") or "-")
        rows.append(_render_score_card(label, _safe_score(item.get("current_score"), 0.0), _safe_score(item.get("baseline_score"), 0.0)))
    rows.append('</div>')
    return ''.join(rows)


def _score_chart_legend() -> str:
    return '<div class="legend"><span><i class="legend-dot" style="background:#175cd3"></i>当前</span><span><i class="legend-dot" style="background:#98a2b3"></i>基线</span></div>'


def _baseline_id_from_compare_index(compare_index: dict[str, dict[str, object]]) -> str:
    for item in compare_index.values():
        value = item.get("baseline_eval_run_id")
        if value:
            return str(value)
    return "-"


def _render_score_card(label: str, current: float, baseline: float) -> str:
    delta = round(current - baseline, 4)
    return (
        '<div class="score-card">'
        '<div class="score-head">'
        f'<div class="score-name">{_text(label)}</div>'
        f'<div class="score-chip">当前 {_text(_format_score(current))}</div>'
        f'<div class="score-chip">基线 {_text(_format_score(baseline))}</div>'
        f'<div class="score-change">{_delta(delta)}</div>'
        '</div>'
        '<div class="score-bars">'
        f'{_render_score_bar("当前", current, "score-fill-current")}'
        f'{_render_score_bar("基线", baseline, "score-fill-baseline")}'
        '</div>'
        '</div>'
    )


def _render_score_bar(label: str, score: float, fill_class: str) -> str:
    width = max(0.0, min(100.0, score))
    return (
        '<div class="score-bar-row">'
        f'<div>{_text(label)}</div>'
        f'<div class="score-track"><div class="{html.escape(fill_class)}" style="width:{width}%"></div></div>'
        f'<div>{_text(_format_score(score))}</div>'
        '</div>'
    )


def _format_score(value: float) -> str:
    rounded = round(value, 4)
    if rounded.is_integer():
        return str(int(rounded))
    return str(rounded)


def _safe_score(value: object, fallback: float) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return round(float(fallback), 4)


_CASE_DISPLAY_NAMES = {
    "memory_interference_recall_cn": "记忆抗临时干扰",
    "memory_scope_isolation_cn": "记忆 scope 隔离",
    "memory_overwrite_conflict_cn": "记忆覆盖冲突处理",
    "memory_should_not_write_cn": "临时指令避免写入记忆",
    "subagent_delegation_boundary_cn": "子代理边界委派",
    "subagent_no_duplicate_dispatch_cn": "子代理避免重复派发",
    "subagent_incomplete_child_handling_cn": "子代理未完成时避免编造",
    "subagent_multi_child_synthesis_cn": "旧版：多子代理综合",
    "subagent_should_delegate_complex_task_cn": "旧版：复杂任务委派",
    "subagent_should_stay_main_thread_cn": "旧版：主线程直答",
    "mcp_multi_source_repo_evidence_cn": "MCP 多来源仓库证据",
    "mcp_empty_result_recovery_cn": "MCP 空结果恢复",
    "mcp_tool_result_attribution_cn": "MCP 工具结果归因",
    "integrated_memory_mcp_conflict_resolution_cn": "记忆与 MCP 冲突处理",
    "integrated_subagent_mcp_evidence_boundary_cn": "子代理与 MCP 证据边界",
    "skill_required_multistep_apply_cn": "需要 skill 的多步骤执行",
    "skill_unneeded_complex_direct_cn": "复杂直答避免误用 skill",
}


def _stats_inline(value: object) -> str:
    if not isinstance(value, dict):
        return "-"
    return "mean={mean} · range={range} · stddev={stddev}".format(
        mean=_text(value.get("mean")),
        range=_text(value.get("range")),
        stddev=_text(value.get("stddev")),
    )


def _delta(value: object) -> str:
    if value in (None, ''):
        return '<span class="delta-flat">-</span>'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f'<span class="delta-flat">{_text(value)}</span>'
    if number > 0:
        return f'<span class="delta-up">+{number}</span>'
    if number < 0:
        return f'<span class="delta-down">{number}</span>'
    return '<span class="delta-flat">0.0</span>'


def _run_label(value: str) -> str:
    if not value or value == '-':
        return '-'
    if value == 'latest_passed':
        return '最近通过基线'
    if value.startswith('named:'):
        return f"命名基线 {value.removeprefix('named:')}"
    if value == 'explicit_run':
        return '指定基线'
    if value.startswith('eval_'):
        parts = value.split('_')
        if len(parts) >= 5 and parts[-1].isdigit() and parts[-3].isdigit():
            suite = '_'.join(parts[1:-3])
            timestamp = parts[-3]
            sha = parts[-2]
            sequence = parts[-1]
            return f"{_suite_label(suite)} · {_format_eval_timestamp(timestamp)} · {sha[:7]} · 第{int(sequence) + 1}次"
    return _short_id(value)


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


def _format_eval_timestamp(value: str) -> str:
    if len(value) < 14 or not value[:14].isdigit():
        return value
    return f"{value[:4]}-{value[4:6]}-{value[6:8]} {value[8:10]}:{value[10:12]}:{value[12:14]}"


def _short_id(value: str) -> str:
    if len(value) <= 34:
        return value
    return f"{value[:18]}…{value[-10:]}"


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _provider_health_status(
    *,
    retry_count: int,
    fallback_count: int,
    provider_error_count: int,
    empty_output_count: int,
) -> tuple[str, str]:
    if provider_error_count > 0 or empty_output_count > 0:
        return ('有错误', '存在 provider 错误或空输出')
    if retry_count > 0 or fallback_count > 0:
        return ('有波动', '出现重试或 provider 回退')
    return ('健康', '无重试、无回退、无错误、无空输出')


def _text(value: object) -> str:
    if value in (None, ''):
        return '-'
    return html.escape(str(value))
