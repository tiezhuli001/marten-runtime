from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FailureEvent(BaseModel):
    failure_id: str
    agent_id: str
    run_id: str
    trace_id: str
    session_id: str
    error_code: str
    error_stage: str
    tool_name: str | None = None
    provider_name: str | None = None
    summary: str
    fingerprint: str
    created_at: datetime = Field(default_factory=_utc_now)


class RecoveryEvent(BaseModel):
    recovery_id: str
    agent_id: str
    run_id: str
    trace_id: str
    related_failure_fingerprint: str
    recovery_kind: str
    fix_summary: str
    success_evidence: str
    created_at: datetime = Field(default_factory=_utc_now)


class LessonCandidate(BaseModel):
    candidate_id: str
    agent_id: str
    source_fingerprints: list[str]
    candidate_text: str
    rationale: str
    status: str = "pending"
    score: float = 0.0
    created_at: datetime = Field(default_factory=_utc_now)


class ReviewTrigger(BaseModel):
    trigger_id: str
    agent_id: str
    trigger_kind: str
    source_run_id: str
    source_trace_id: str
    source_fingerprints: list[str]
    status: str = "pending"
    payload_json: dict[str, object] = Field(default_factory=dict)
    semantic_fingerprint: str
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class SkillCandidate(BaseModel):
    candidate_id: str
    agent_id: str
    status: str = "pending"
    title: str
    slug: str
    summary: str
    trigger_conditions: list[str] = Field(default_factory=list)
    body_markdown: str
    rationale: str
    source_run_ids: list[str] = Field(default_factory=list)
    source_fingerprints: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    semantic_fingerprint: str
    created_at: datetime = Field(default_factory=_utc_now)
    reviewed_at: datetime | None = None
    promoted_skill_id: str | None = None


class SystemLesson(BaseModel):
    lesson_id: str
    agent_id: str
    topic_key: str
    lesson_text: str
    source_fingerprints: list[str]
    active: bool = True
    created_at: datetime = Field(default_factory=_utc_now)
    superseded_at: datetime | None = None
