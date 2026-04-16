from __future__ import annotations

import json

from pydantic import BaseModel, Field, field_validator


def _normalize_confidence(value):  # noqa: ANN001
    if value is None or value == "":
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        label_map = {
            "high": 0.9,
            "medium": 0.6,
            "low": 0.3,
        }
        if lowered in label_map:
            return label_map[lowered]
    return value


class LessonProposal(BaseModel):
    candidate_text: str
    rationale: str
    source_fingerprints: list[str] = Field(default_factory=list)
    score: float = 0.0


class SkillProposal(BaseModel):
    title: str
    slug: str
    summary: str
    trigger_conditions: list[str] = Field(default_factory=list)
    body_markdown: str
    rationale: str
    source_run_ids: list[str] = Field(default_factory=list)
    source_fingerprints: list[str] = Field(default_factory=list)
    confidence: float = 0.0

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value):  # noqa: ANN001
        normalized = _normalize_confidence(value)
        return 0.0 if normalized is None else normalized


class ReviewChildResult(BaseModel):
    lesson_proposals: list[LessonProposal] = Field(default_factory=list)
    skill_proposals: list[SkillProposal] = Field(default_factory=list)
    nothing_to_save_reason: str | None = None
    confidence: float | None = None
    classification_rationale: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value):  # noqa: ANN001
        return _normalize_confidence(value)


def parse_review_child_result(text: str) -> ReviewChildResult:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("missing_json_object")
    payload = json.loads(cleaned[start : end + 1])
    result = ReviewChildResult.model_validate(payload)
    if (
        not result.lesson_proposals
        and not result.skill_proposals
        and not str(result.nothing_to_save_reason or "").strip()
    ):
        raise ValueError("missing_review_decision")
    return result
