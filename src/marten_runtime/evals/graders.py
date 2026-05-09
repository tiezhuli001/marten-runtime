from __future__ import annotations

from marten_runtime.evals.grader_registry import resolve_case_grader
from marten_runtime.evals.models import EvalCaseObservation, EvalCaseResult, EvalCaseSpec


def grade_case_result(
    case: EvalCaseSpec,
    observation: EvalCaseObservation,
    *,
    eval_run_id: str,
) -> EvalCaseResult:
    grader = resolve_case_grader(case)
    return grader(case, observation, eval_run_id)
