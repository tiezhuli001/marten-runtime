from datetime import datetime, timezone

from pydantic import BaseModel, Field

from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.tool_outcome_summary import ToolOutcomeSummary


class SessionMessage(BaseModel):
    role: str
    content: str
    created_at: datetime
    received_at: datetime | None = None
    enqueued_at: datetime | None = None
    started_at: datetime | None = None

    @classmethod
    def system(cls, content: str, *, created_at: datetime | None = None) -> "SessionMessage":
        return cls(role="system", content=content, created_at=created_at or datetime.now(timezone.utc))

    @classmethod
    def user(
        cls,
        content: str,
        *,
        created_at: datetime | None = None,
        received_at: datetime | None = None,
        enqueued_at: datetime | None = None,
        started_at: datetime | None = None,
    ) -> "SessionMessage":
        return cls(
            role="user",
            content=content,
            created_at=created_at or received_at or datetime.now(timezone.utc),
            received_at=received_at,
            enqueued_at=enqueued_at,
            started_at=started_at,
        )

    @classmethod
    def assistant(cls, content: str, *, created_at: datetime | None = None) -> "SessionMessage":
        return cls(role="assistant", content=content, created_at=created_at or datetime.now(timezone.utc))


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
    latest_compacted_context: CompactedContext | None = None
    latest_actual_usage: NormalizedUsage | None = None
    recent_tool_outcome_summaries: list[ToolOutcomeSummary] = Field(default_factory=list)
    tool_call_count: int = 0
    history: list[SessionMessage] = Field(default_factory=list)
