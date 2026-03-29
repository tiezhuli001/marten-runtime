from datetime import datetime, timezone

from pydantic import BaseModel, Field


class JobRecord(BaseModel):
    job_id: str
    job_type: str
    session_id: str
    app_id: str
    agent_id: str
    queue_name: str = "automation"
    state: str = "queued"
    dedupe_key: str
    prompt_mode: str = "full"
    priority: int = 100
    attempt: int = 0
    not_before: int = 0
    lease_expires_at: int = 0
    worker_id: str | None = None
    last_heartbeat_at: int = 0
    active_run_id: str | None = None
    resolved_config_snapshot_id: str | None = None
    resolved_bootstrap_manifest_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
