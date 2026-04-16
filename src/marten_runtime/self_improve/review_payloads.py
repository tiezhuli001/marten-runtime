from __future__ import annotations

import json

from marten_runtime.self_improve.models import ReviewTrigger
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.skills.service import SkillService

MAX_FAILURES = 3
MAX_RECOVERIES = 3
MAX_LESSON_CANDIDATES = 3
MAX_SKILL_CANDIDATES = 3
MAX_SKILL_HEAD_CHARS = 600


def build_review_payload(
    *,
    trigger: ReviewTrigger,
    store: SQLiteSelfImproveStore,
    skill_service: SkillService | None,
) -> dict[str, object]:
    relevant_fingerprints = set(trigger.source_fingerprints)
    failures = [
        item.model_dump(mode="json")
        for item in store.list_recent_failures(agent_id=trigger.agent_id, limit=20)
        if not relevant_fingerprints or item.fingerprint in relevant_fingerprints
    ][:MAX_FAILURES]
    recoveries = [
        item.model_dump(mode="json")
        for item in store.list_recent_recoveries(agent_id=trigger.agent_id, limit=20)
        if not relevant_fingerprints
        or item.related_failure_fingerprint in relevant_fingerprints
    ][:MAX_RECOVERIES]
    lesson_candidates = [
        item.model_dump(mode="json")
        for item in store.list_candidates(
            agent_id=trigger.agent_id,
            limit=MAX_LESSON_CANDIDATES,
            status="pending",
        )
    ]
    skill_candidates = [
        item.model_dump(mode="json")
        for item in store.list_skill_candidates(
            agent_id=trigger.agent_id,
            limit=MAX_SKILL_CANDIDATES,
            status="pending",
        )
    ]
    active_lessons = [
        item.model_dump(mode="json")
        for item in store.list_active_lessons(agent_id=trigger.agent_id)[:MAX_LESSON_CANDIDATES]
    ]
    skill_heads_text = None
    if skill_service is not None:
        runtime = skill_service.build_runtime(
            agent_id=trigger.agent_id,
            channel_id="self_improve_review",
        )
        if runtime.skill_heads_text:
            skill_heads_text = runtime.skill_heads_text[:MAX_SKILL_HEAD_CHARS]
    return {
        "trigger": trigger.model_dump(mode="json"),
        "recent_failures": failures,
        "recent_recoveries": recoveries,
        "active_lessons": active_lessons,
        "pending_lesson_candidates": lesson_candidates,
        "pending_skill_candidates": skill_candidates,
        "visible_skill_heads_text": skill_heads_text,
    }


def build_review_prompt(
    payload: dict[str, object],
    *,
    review_skill_text: str,
) -> str:
    return (
        "Review the following self-improve evidence and return exactly one JSON object.\n"
        "Classify only high-signal reusable lessons or skills.\n"
        "Do not suggest AGENTS/bootstrap edits. Do not suggest direct user notification.\n"
        "Use the following internal review skill instructions as the narrow reasoning contract.\n"
        f"{review_skill_text.strip()}\n"
        "JSON keys: lesson_proposals, skill_proposals, nothing_to_save_reason, confidence, classification_rationale.\n"
        "Each lesson proposal should use keys: candidate_text, rationale, source_fingerprints, score.\n"
        "Each skill proposal should use keys: title, slug, summary, trigger_conditions, body_markdown, rationale, source_run_ids, source_fingerprints, confidence.\n"
        f"Payload:\n{json.dumps(payload, ensure_ascii=False)}"
    )
