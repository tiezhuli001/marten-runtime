from marten_runtime.domains.review.models import ReviewFinding


def make_blocking_finding(title: str, body: str) -> ReviewFinding:
    return ReviewFinding(title=title, body=body, blocking=True)
