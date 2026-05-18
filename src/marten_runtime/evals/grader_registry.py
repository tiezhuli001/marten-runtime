from __future__ import annotations

from collections.abc import Callable

from marten_runtime.evals.family_graders.challenge import grade_challenge_case_result
from marten_runtime.evals.family_graders.main_chain import grade_main_chain_case_result
from marten_runtime.evals.family_graders.memory_long_horizon import (
    grade_memory_long_horizon_case_result,
)
from marten_runtime.evals.family_graders.subagent_task_progress import (
    grade_subagent_task_progress_case_result,
)
from marten_runtime.evals.models import EvalCaseObservation, EvalCaseResult, EvalCaseSpec

CaseGrader = Callable[[EvalCaseSpec, EvalCaseObservation, str], EvalCaseResult]

_REGISTRY: dict[str, CaseGrader] = {
    "main_chain_core": grade_main_chain_case_result,
    "challenge": grade_challenge_case_result,
    "memory_long_horizon": grade_memory_long_horizon_case_result,
    "subagent_task_progress": grade_subagent_task_progress_case_result,
}


def resolve_case_grader(case: EvalCaseSpec) -> CaseGrader:
    grader_id = str(case.grader_id or "").strip() or "main_chain_core"
    return _REGISTRY.get(grader_id, grade_main_chain_case_result)
