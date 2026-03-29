import subprocess
from uuid import uuid4

from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    run_id: str
    trace_id: str
    ok: bool
    commands: list[str] = Field(default_factory=list)
    output: str = ""
    error_code: str | None = None
    backend_id: str = "subprocess"


class ValidationRunner:
    backend_id: str = "subprocess"

    def run(
        self,
        commands: list[str],
        trace_id: str = "trace_validation",
        cwd: str | None = None,
    ) -> ValidationResult:
        outputs: list[str] = []
        error_code: str | None = None
        ok = True
        for command in commands:
            result = subprocess.run(
                ["/bin/zsh", "-lc", command],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
            outputs.append(f"$ {command}")
            if result.stdout:
                outputs.append(result.stdout.strip())
            if result.stderr:
                outputs.append(result.stderr.strip())
            if result.returncode != 0:
                ok = False
                error_code = "command_failed"
                break
        return ValidationResult(
            run_id=f"run_validation_{uuid4().hex[:8]}",
            trace_id=trace_id,
            ok=ok,
            commands=commands,
            output="\n".join(item for item in outputs if item),
            error_code=error_code,
            backend_id=self.backend_id,
        )
