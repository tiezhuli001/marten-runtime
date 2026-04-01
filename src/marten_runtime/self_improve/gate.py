from __future__ import annotations

from marten_runtime.self_improve.models import LessonCandidate, SystemLesson


def reject_reason(
    candidate: LessonCandidate,
    *,
    active_lessons: list[SystemLesson],
    normalized_lesson_text: str,
    topic_key: str,
) -> str | None:
    if len(candidate.source_fingerprints) < 2:
        return "insufficient_evidence"
    if not normalized_lesson_text.strip():
        return "empty_lesson"
    if not topic_key.strip():
        return "empty_topic"
    if len(normalized_lesson_text.strip()) > 200:
        return "lesson_too_long"
    for lesson in active_lessons:
        if lesson.topic_key == topic_key:
            return "topic_already_active"
        if lesson.lesson_text.strip() == normalized_lesson_text.strip():
            return "duplicate_lesson"
    return None
