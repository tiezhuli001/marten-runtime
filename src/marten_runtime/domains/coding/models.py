from pydantic import BaseModel, Field


class CodingRequest(BaseModel):
    title: str
    body: str
    repo: str
    acceptance: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class CodingArtifact(BaseModel):
    run_id: str
    validation_run_id: str
    patch_summary: str
    repo: str = ""
    backend_id: str = "subprocess"
    changed_files: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    validation_ok: bool = False
    validation_summary: str = ""
    validation_error_code: str | None = None
    trace_id: str = "trace_coding"
