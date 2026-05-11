from __future__ import annotations

from marten_runtime.evals.models import EvalCaseResult, EvalRunSummary


def build_summary_markdown(
    summary: EvalRunSummary,
    case_results: list[EvalCaseResult],
    *,
    compare_result: dict[str, object] | None = None,
    stability_result: dict[str, object] | None = None,
    blocked_reason: str | None = None,
    provider_reliability: dict[str, object] | None = None,
) -> str:
    md_lines = [
        f'# Eval Report: {summary.eval_run_id}',
        '',
        '## Run Metadata',
        '',
        f'- suite: `{summary.suite_id}`',
        f'- mode: `{summary.eval_mode}`',
        f'- status: `{summary.status}`',
        f'- profile: `{summary.profile_name}`',
        f'- provider_ref: `{summary.provider_ref}`',
        f'- git_branch: `{summary.git_branch}`',
        f'- git_sha: `{summary.git_sha}`',
        '',
    ]
    if blocked_reason:
        md_lines.extend([f'- blocked_reason: `{blocked_reason}`', ''])
    if provider_reliability:
        md_lines.extend(
            [
                '## Provider Stability',
                '',
                f"- window_size: `{provider_reliability.get('window_size')}`",
                f"- run_count: `{provider_reliability.get('run_count')}`",
                f"- retry_count: `{provider_reliability.get('retry_count')}`",
                f"- fallback_count: `{provider_reliability.get('fallback_count')}`",
                f"- provider_error_count: `{provider_reliability.get('provider_error_count')}`",
                f"- empty_output_count: `{provider_reliability.get('empty_output_count')}`",
                f"- latest_final_provider_ref: `{provider_reliability.get('latest_final_provider_ref')}`",
                '',
            ]
        )
    md_lines.extend(
        [
            '## Suite Overview',
            '',
            f'- total_score: `{summary.total_score}`',
            f'- pass_rate: `{summary.pass_rate}`',
            f'- case_count: `{len(case_results)}`',
            '',
            '## Baseline Compare',
            '',
            ]
        )
    if compare_result is None:
        md_lines.extend(['- baseline: `none`', ''])
    else:
        md_lines.extend(
            [
                f"- baseline_eval_run_id: `{compare_result.get('baseline_eval_run_id')}`",
                f"- baseline_source: `{compare_result.get('baseline_source')}`",
                f"- total_score_delta: `{compare_result.get('total_score_delta')}`",
                f"- pass_rate_delta: `{compare_result.get('pass_rate_delta')}`",
                '',
                '## Regressions',
                '',
            ]
        )
        regressions = list(compare_result.get('regressions') or [])
        if regressions:
            for item in regressions:
                md_lines.append(
                    f"- `{item.get('case_id')}` delta `{item.get('total_score_delta')}`"
                )
        else:
            md_lines.append('- none')
        md_lines.extend(['', '## Improvements', ''])
        improvements = list(compare_result.get('improvements') or [])
        if improvements:
            for item in improvements:
                md_lines.append(
                    f"- `{item.get('case_id')}` delta `{item.get('total_score_delta')}`"
                )
        else:
            md_lines.append('- none')
        md_lines.append('')
    _append_stability_section(md_lines, stability_result)
    md_lines.extend(
        [
            '',
            '## Case Evidence',
            '',
            '| case_id | status | total_score | run_id | trace_id |',
            '| --- | --- | --- | --- | --- |',
        ]
    )
    for result in case_results:
        md_lines.append(
            f"| {result.case_id} | {result.status} | {result.total_score} | {result.run_id or '-'} | {result.trace_id or '-'} |"
        )
    return '\n'.join(md_lines)


def _append_stability_section(md_lines: list[str], stability_result: dict[str, object] | None) -> None:
    md_lines.extend(['## Stability', ''])
    if stability_result is None:
        md_lines.extend(['- sample_size: `0`'])
        return
    md_lines.extend(
        [
            f"- sample_size: `{stability_result.get('sample_size')}`",
            f"- window_size: `{stability_result.get('window_size')}`",
            f"- total_score_range: `{((stability_result.get('total_score') or {}).get('range'))}`",
            f"- pass_rate_range: `{((stability_result.get('pass_rate') or {}).get('range'))}`",
            f"- token_total_range: `{((stability_result.get('token_total') or {}).get('range'))}`",
            f"- failover_rate: `{stability_result.get('failover_rate')}`",
            f"- unstable_case_count: `{stability_result.get('unstable_case_count')}`",
            '',
            '### Unstable Cases',
            '',
        ]
    )
    unstable_cases = [
        item
        for item in list(stability_result.get('cases') or [])
        if isinstance(item, dict) and item.get('unstable')
    ]
    if unstable_cases:
        for item in unstable_cases:
            md_lines.append(
                "- `{case_id}` score_range `{score_range}` failover_rate `{failover_rate}` "
                "anchor_strength `{anchor_strength}` reasons `{reasons}`".format(
                    case_id=item.get('case_id'),
                    score_range=((item.get('score') or {}).get('range')),
                    failover_rate=item.get('failover_rate'),
                    anchor_strength=item.get('anchor_strength'),
                    reasons=','.join(list(item.get('unstable_reasons') or [])),
                )
            )
        return
    md_lines.append('- none')
