from uuid import uuid4

from marten_runtime.domains.review.findings import make_blocking_finding
from marten_runtime.domains.review.models import ReviewFinding, ReviewResult, ReviewTarget


class ReviewService:
    def run(self, target: ReviewTarget) -> ReviewResult:
        findings: list[ReviewFinding] = []
        prompt_mode = target.handoff.prompt_mode if target.handoff else "full"
        if target.handoff is None or target.handoff.prompt_mode != "child":
            findings.append(
                make_blocking_finding(
                    "Invalid review handoff",
                    "Isolated review must inherit a compact child handoff.",
                )
            )
        if not target.diff.strip():
            findings.append(
                ReviewFinding(
                    title="Empty diff",
                    body="Review target has no diff content.",
                    blocking=True,
                )
            )
        return ReviewResult(
            review_run_id=f"run_review_{uuid4().hex[:8]}",
            review_passed=not any(item.blocking for item in findings),
            prompt_mode=prompt_mode,
            findings=findings,
        )
