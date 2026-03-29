from datetime import datetime, timezone

from pydantic import BaseModel, Field


class SessionMessage(BaseModel):
    role: str
    content: str
    created_at: datetime

    @classmethod
    def system(cls, content: str) -> "SessionMessage":
        return cls(role="system", content=content, created_at=datetime.now(timezone.utc))

    @classmethod
    def user(cls, content: str) -> "SessionMessage":
        return cls(role="user", content=content, created_at=datetime.now(timezone.utc))

    @classmethod
    def assistant(cls, content: str) -> "SessionMessage":
        return cls(role="assistant", content=content, created_at=datetime.now(timezone.utc))


class SessionRecord(BaseModel):
    session_id: str
    conversation_id: str
    state: str = "created"
    created_at: datetime
    updated_at: datetime
    active_agent_id: str = "assistant"
    parent_session_id: str | None = None
    session_kind: str = "main"
    lineage_depth: int = 0
    config_snapshot_id: str = "cfg_bootstrap"
    bootstrap_manifest_id: str = "boot_default"
    context_snapshot_id: str | None = None
    last_run_id: str | None = None
    last_event_at: datetime | None = None
    last_compacted_at: datetime | None = None
    tool_call_count: int = 0
    history: list[SessionMessage] = Field(default_factory=list)
