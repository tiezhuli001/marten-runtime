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
  <title>评测报告：{html.escape(summary.eval_run_id)}</title>
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
  </style>
</head>
<body>
  <div class="page">
    <h1>评测报告：{html.escape(summary.eval_run_id)}</h1>
    <div class="muted">套件={html.escape(summary.suite_id)} · 模式={html.escape(summary.eval_mode)} · 分支={html.escape(summary.git_branch)} · 提交={html.escape(summary.git_sha)}</div>
    <div class="grid">
      <div class="card"><div class="metric">运行状态</div><div class="metric-value"><span class="status status-{html.escape(summary.status)}">{html.escape(summary.status)}</span></div></div>
      <div class="card"><div class="metric">总分</div><div class="metric-value">{summary.total_score}</div></div>
      <div class="card"><div class="metric">通过率</div><div class="metric-value">{summary.pass_rate}</div></div>
      <div class="card"><div class="metric">模型配置</div><div class="metric-value" style="font-size:18px;">{html.escape(summary.profile_name)}</div></div>
      <div class="card"><div class="metric">提供方</div><div class="metric-value" style="font-size:18px;">{_text(summary.provider_ref)}</div></div>
      <div class="card"><div class="metric">用例数</div><div class="metric-value">{len(case_results)}</div></div>
    </div>
    {blocked_block}
    {compare_block}
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
              <th>case_id</th>
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


def _render_compare_block(compare_result: object) -> str:
    if not isinstance(compare_result, dict):
        return '<div class="panel"><h2>基线对比</h2><div class="muted">baseline=none</div></div>'
    regressions = list(compare_result.get('regressions') or [])
    improvements = list(compare_result.get('improvements') or [])
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
    return f"""
    <div class="panel">
      <h2>基线对比</h2>
      <div class="kv">
        <div>基线运行</div><div>{_text(compare_result.get('baseline_eval_run_id'))}</div>
        <div>基线来源</div><div>{_text(compare_result.get('baseline_source'))}</div>
        <div>总分变化</div><div>{_delta(compare_result.get('total_score_delta'))}</div>
        <div>通过率变化</div><div>{_delta(compare_result.get('pass_rate_delta'))}</div>
        <div>回归用例数</div><div>{len(regressions)}</div>
        <div>改进用例数</div><div>{len(improvements)}</div>
        <div>无变化用例数</div><div>{unchanged}</div>
      </div>
      <h3 style="margin-top:16px;">回归项</h3>
      {_render_compare_list(regressions)}
      <h3 style="margin-top:16px;">改进项</h3>
      {_render_compare_list(improvements)}
      <h3 style="margin-top:16px;">组件汇总</h3>
      {_render_component_summary(component_summary)}
    </div>
    """


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
        return '<div class="panel"><h2>Provider 稳定性</h2><div class="muted">暂无 provider 稳定性摘要。</div></div>'
    latest_runs = [
        item for item in list(provider_reliability.get('latest_runs') or []) if isinstance(item, dict)
    ]
    top_error_kinds = [
        item for item in list(provider_reliability.get('top_error_kinds') or []) if isinstance(item, dict)
    ]
    error_text = ', '.join(
        f"{_text(item.get('error_kind'))}: {_text(item.get('count'))}" for item in top_error_kinds
    )
    return f"""
    <div class="panel">
      <h2>Provider 稳定性</h2>
      <div class="kv">
        <div>窗口大小</div><div>{_text(provider_reliability.get('window_size'))}</div>
        <div>运行数</div><div>{_text(provider_reliability.get('run_count'))}</div>
        <div>重试</div><div>{_text(provider_reliability.get('retry_count'))}</div>
        <div>回退</div><div>{_text(provider_reliability.get('fallback_count'))}</div>
        <div>错误</div><div>{_text(provider_reliability.get('provider_error_count'))}</div>
        <div>空输出</div><div>{_text(provider_reliability.get('empty_output_count'))}</div>
        <div>最近 final provider</div><div>{_text(provider_reliability.get('latest_final_provider_ref'))}</div>
        <div>top error kinds</div><div>{error_text or '-'}</div>
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
        '<th>run_id</th><th>状态</th><th>重试</th><th>回退</th><th>错误</th><th>空输出</th><th>final provider</th>'
        '</tr></thead><tbody>'
    ]
    for item in items:
        rows.append(
            '<tr>'
            f"<td>{_text(item.get('run_id'))}</td>"
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
        rows.append(
            f"<li><strong>{_text(item.get('case_id'))}</strong> · {_text(item.get('change_kind'))} · {_delta(item.get('total_score_delta'))}</li>"
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
        f"<td><a href=\"#case-{html.escape(result.case_id)}\">{html.escape(result.case_id)}</a></td>"
        f"<td><span class=\"status status-{html.escape(result.status)}\">{html.escape(result.status)}</span></td>"
        f"<td>{_text(current_score)}</td>"
        f"<td>{_text(baseline_score)}</td>"
        f"<td>{_delta(delta)}</td>"
        f"<td>{html.escape(change_kind)}</td>"
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
        f"<div class=\"muted\" style=\"margin-top:8px;\">变化类型={_text(comparison.get('change_kind'))} · 分数变化={_delta(delta)}</div>"
        if isinstance(comparison, dict)
        else ""
    )
    component_rows = _render_component_comparisons(
        list(comparison.get("components") or []) if isinstance(comparison, dict) else []
    )
    return f"""
    <details id="case-{html.escape(result.case_id)}">
      <summary>{html.escape(result.case_id)} · {html.escape(result.status)} · score={result.total_score}</summary>
      {compare_meta}
      <div class="kv" style="margin-top:12px;">
        <div>当前分数</div><div>{_text(current_score)}</div>
        <div>基线分数</div><div>{_text(baseline_score)}</div>
        <div>run_id</div><div>{_text(result.run_id)}</div>
        <div>trace_id</div><div>{_text(result.trace_id)}</div>
        <div>llm_request_count</div><div>{result.llm_request_count}</div>
        <div>tool_calls_count</div><div>{result.tool_calls_count}</div>
        <div>duration_ms</div><div>{result.duration_ms}</div>
        <div>artifact</div><div><a href="cases/{html.escape(result.case_id)}.json">cases/{html.escape(result.case_id)}.json</a></div>
      </div>
      <h3 style="margin-top:16px;">组件对比</h3>
      {component_rows}
      <h3 style="margin-top:16px;">最终输出</h3>
      <pre>{html.escape(result.final_text or '')}</pre>
      <h3 style="margin-top:16px;">评分明细</h3>
      <pre>{html.escape(json.dumps(result.score_breakdown_json, ensure_ascii=False, indent=2))}</pre>
      <h3 style="margin-top:16px;">诊断信息</h3>
      <pre>{html.escape(json.dumps(result.diagnostics_json, ensure_ascii=False, indent=2))}</pre>
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
        "<th>case_id</th><th>分数波动</th><th>回退占比</th><th>锚点强度</th><th>原因</th>"
        "</tr></thead><tbody>"
    ]
    for item in items:
        score = item.get("score") if isinstance(item.get("score"), dict) else {}
        rows.append(
            "<tr>"
            f"<td>{_text(item.get('case_id'))}</td>"
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


def _text(value: object) -> str:
    if value in (None, ''):
        return '-'
    return html.escape(str(value))
