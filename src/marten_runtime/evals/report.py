from __future__ import annotations

import json
from pathlib import Path

from marten_runtime.evals.compare import _extract_total_tokens_from_result, _result_used_failover
from marten_runtime.evals.models import EvalCaseResult, EvalRunComparison, EvalRunSummary
from marten_runtime.evals.report_html import render_summary_html
from marten_runtime.evals.report_markdown import build_summary_markdown


def resolve_report_artifact_root(report_root: str | Path, eval_run_id: str) -> Path:
    return Path(report_root) / eval_run_id


def resolve_case_artifact_path(artifact_root: str | Path, case_id: str) -> Path:
    return Path(artifact_root) / "cases" / f"{case_id}.json"


def write_eval_report(
    summary: EvalRunSummary,
    case_results: list[EvalCaseResult],
    *,
    report_root: str | Path,
    compare_result: EvalRunComparison | dict[str, object] | None = None,
    stability_result: dict[str, object] | None = None,
    blocked_reason: str | None = None,
) -> Path:
    root = resolve_report_artifact_root(report_root, summary.eval_run_id)
    cases_root = root / 'cases'
    cases_root.mkdir(parents=True, exist_ok=True)
    resolved_summary = summary.model_copy(update={"artifact_root": str(root)})
    resolved_case_results = [
        item.model_copy(update={"artifact_path": str(resolve_case_artifact_path(root, item.case_id))})
        for item in case_results
    ]

    resolved_compare = (
        compare_result.model_dump(mode='json')
        if isinstance(compare_result, EvalRunComparison)
        else compare_result
    )
    token_values = [
        value
        for value in (_extract_total_tokens_from_result(item) for item in resolved_case_results)
        if value is not None
    ]
    failover_hits = sum(1 for item in resolved_case_results if _result_used_failover(item))
    summary_payload = {
        **resolved_summary.model_dump(mode='json'),
        'token_total': round(sum(token_values), 4) if token_values else None,
        'token_cases': len(token_values),
        'failover_rate': round(failover_hits / max(1, len(resolved_case_results)), 4),
        'case_results': [item.model_dump(mode='json') for item in resolved_case_results],
        'compare_result': resolved_compare,
        'stability_result': stability_result,
        'blocked_reason': blocked_reason,
    }
    (root / 'summary.json').write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    for result in resolved_case_results:
        (cases_root / f'{result.case_id}.json').write_text(
            json.dumps(result.model_dump(mode='json'), ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    (root / 'summary.md').write_text(
        build_summary_markdown(
            resolved_summary,
            resolved_case_results,
            compare_result=resolved_compare,
            stability_result=stability_result,
            blocked_reason=blocked_reason,
        ),
        encoding='utf-8',
    )
    compare_index = {
        str(item.get('case_id')): item
        for item in list((resolved_compare or {}).get('cases') or [])
        if isinstance(item, dict) and item.get('case_id') is not None
    }
    (root / 'summary.html').write_text(
        render_summary_html(
            summary_payload=summary_payload,
            case_results=resolved_case_results,
            compare_index=compare_index,
        ),
        encoding='utf-8',
    )
    return root
