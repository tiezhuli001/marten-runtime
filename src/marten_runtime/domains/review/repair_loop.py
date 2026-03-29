from marten_runtime.domains.review.models import ReviewResult


class RepairLoop:
    def should_retry(self, result: ReviewResult, max_rounds: int, current_round: int) -> bool:
        has_blocking = any(item.blocking for item in result.findings)
        return has_blocking and current_round < max_rounds
