from marten_runtime.domains.coding.models import CodingArtifact, CodingRequest
from marten_runtime.domains.coding.validation import ValidationRunner
from marten_runtime.domains.coding.worktree import WorktreeService


class CodingService:
    def __init__(self) -> None:
        self.worktree = WorktreeService()
        self.validation = ValidationRunner()

    def run(self, request: CodingRequest, run_id: str = "run_coding", trace_id: str = "trace_coding") -> CodingArtifact:
        self.worktree.prepare(request.repo)
        result = self.validation.run(request.acceptance, trace_id=trace_id, cwd=request.repo)
        return CodingArtifact(
            run_id=run_id,
            validation_run_id=result.run_id,
            patch_summary=request.title,
            repo=request.repo,
            backend_id=self.worktree.backend_id,
            changed_files=self.worktree.collect_changes(),
            validation_commands=result.commands,
            validation_ok=result.ok,
            validation_summary=result.output,
            validation_error_code=result.error_code,
            trace_id=trace_id,
        )
