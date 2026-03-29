from pydantic import BaseModel, Field

from marten_runtime.session.rehydration import ChildSessionHandoff


class ReviewTarget(BaseModel):
    title: str
    run_id: str
    validation_run_id: str
    diff: str
    changed_files: list[str] = Field(default_factory=list)
    handoff: ChildSessionHandoff | None = None


class ReviewFinding(BaseModel):
    title: str
    body: str
    blocking: bool = False


class ReviewResult(BaseModel):
    review_run_id: str
    review_passed: bool = False
    prompt_mode: str = "child"
    findings: list[ReviewFinding] = Field(default_factory=list)
