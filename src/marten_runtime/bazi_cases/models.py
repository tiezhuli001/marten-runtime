from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


EventCategory = Literal[
    "education",
    "career",
    "wealth",
    "marriage",
    "health",
    "family",
    "children",
    "relocation",
    "legal",
    "other",
]
EvidenceType = Literal[
    "user_reported",
    "document_verified",
    "operator_verified",
    "model_inferred",
]
EventSubject = Literal[
    "self", "father", "mother", "spouse", "child", "family",
    "career_platform", "asset", "unknown",
]
SHARED_CASE_OWNER_KEY = "bazi.shared.curated"
SHARED_CASE_NAMESPACE = "bazi-cases-curated"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaziCaseEvent(BaseModel):
    event_id: str
    category: EventCategory
    description: str = Field(min_length=1, max_length=1000)
    outcome: str = Field(default="", max_length=1000)
    time_start: str = ""
    time_end: str = ""
    time_precision: Literal["exact_year", "range", "life_stage", "unknown"] = "unknown"
    evidence_type: EvidenceType
    verification_status: Literal["verified", "reported", "unverified"]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    privacy_redacted: bool = False
    linked_prediction_ids: list[str] = Field(default_factory=list)
    source_excerpt: str = Field(default="", max_length=1000)
    subject: EventSubject = "self"


class BaziCaseInterpretation(BaseModel):
    school: str = Field(default="", max_length=100)
    method: str = Field(default="", max_length=200)
    strength: str = Field(default="", max_length=500)
    pattern: str = Field(default="", max_length=500)
    useful_elements: list[str] = Field(default_factory=list, max_length=10)
    favorable_elements: list[str] = Field(default_factory=list, max_length=10)
    unfavorable_elements: list[str] = Field(default_factory=list, max_length=10)
    basis: list[str] = Field(default_factory=list, max_length=50)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_excerpt: str = Field(default="", max_length=2000)


class BaziTopicConclusion(BaseModel):
    conclusion_id: str
    topic: EventCategory
    conclusion: str = Field(min_length=1, max_length=2000)
    basis: list[str] = Field(default_factory=list, max_length=50)
    applicable_time: str = Field(default="", max_length=200)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    source_excerpt: str = Field(default="", max_length=2000)


class BaziCasePrediction(BaseModel):
    prediction_id: str
    topic: EventCategory
    time_start: str = ""
    time_end: str = ""
    time_precision: Literal["exact_year", "range", "life_stage", "unknown"] = "unknown"
    triggers: list[str] = Field(default_factory=list, max_length=50)
    conclusion: str = Field(min_length=1, max_length=2000)
    status: Literal["pending", "confirmed", "partial", "missed", "unknown"] = "pending"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_excerpt: str = Field(default="", max_length=2000)
    subject: EventSubject = "self"


class BaziCaseReview(BaseModel):
    review_id: str
    prediction_id: str
    event_id: str = ""
    outcome: Literal["confirmed", "partial", "missed", "unknown"]
    notes: str = Field(default="", max_length=2000)
    corrected_conclusion: str = Field(default="", max_length=2000)
    created_at: str


class BaziCaseSourceRef(BaseModel):
    title: str = Field(default="", max_length=500)
    author: str = Field(default="", max_length=200)
    chapter: str = Field(default="", max_length=500)
    uri: str = Field(default="", max_length=2000)
    path: str = Field(default="", max_length=2000)
    line_start: int = Field(default=0, ge=0)
    line_end: int = Field(default=0, ge=0)
    content_sha256: str = Field(default="", max_length=80)


class BaziExtractionQuality(BaseModel):
    extractor_version: str = Field(default="", max_length=100)
    grade: Literal["A", "B", "C", "D", "unknown"] = "unknown"
    completeness: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rejection_reasons: list[str] = Field(default_factory=list, max_length=20)


class BaziCaseRecord(BaseModel):
    case_id: str
    schema_version: str = "bazi.case.v3"
    case_version: int = Field(ge=1)
    owner_key: str
    status: Literal["active_private", "active_shared", "archived", "deleted"] = "active_private"
    visibility: Literal["private", "shared_curated"] = "private"
    source_type: Literal["user_saved", "operator_imported"] = "user_saved"
    source_run_id: str
    source_session_id: str
    input_fingerprint: str
    engine: dict[str, object]
    result_schema_version: str
    time_basis: dict[str, object] | None = None
    chart_snapshot: dict[str, object]
    chart_features: dict[str, object] = Field(default_factory=dict)
    question: str = Field(default="", max_length=2000)
    analysis_summary: str = Field(default="", max_length=4000)
    raw_case_text: str = Field(default="", max_length=50000)
    interpretation: BaziCaseInterpretation = Field(default_factory=BaziCaseInterpretation)
    topic_conclusions: list[BaziTopicConclusion] = Field(default_factory=list)
    predictions: list[BaziCasePrediction] = Field(default_factory=list)
    events: list[BaziCaseEvent] = Field(default_factory=list)
    reviews: list[BaziCaseReview] = Field(default_factory=list)
    source_ref: BaziCaseSourceRef = Field(default_factory=BaziCaseSourceRef)
    extraction_quality: BaziExtractionQuality = Field(default_factory=BaziExtractionQuality)
    projection_namespace: str
    projection_source_id: str
    created_at: str
    updated_at: str
