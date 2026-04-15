from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel

from marten_runtime.self_improve.gate import reject_reason
from marten_runtime.self_improve.models import LessonCandidate, SystemLesson
from marten_runtime.runtime.llm_client import LLMClient, LLMRequest
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


class JudgeVerdict(BaseModel):
    accept: bool
    reason: str
    normalized_lesson_text: str
    topic_key: str


class LessonJudge(Protocol):
    def __call__(
        self,
        candidate: LessonCandidate,
        *,
        active_lessons: list[SystemLesson],
    ) -> JudgeVerdict:
        ...


class LLMJudgeReply(BaseModel):
    accept: bool
    reason: str
    normalized_lesson_text: str
    topic_key: str


class SelfImproveService:
    def __init__(
        self,
        store: SQLiteSelfImproveStore,
        *,
        lessons_path: str | Path,
        judge: LessonJudge,
    ) -> None:
        self.store = store
        self.lessons_path = Path(lessons_path)
        self.judge = judge

    def process_pending_candidates(self, *, agent_id: str) -> list[SystemLesson]:
        accepted: list[SystemLesson] = []
        for candidate in self.store.list_candidates(agent_id=agent_id, limit=50):
            if candidate.status != "pending":
                continue
            active_lessons = self.store.list_active_lessons(agent_id=agent_id)
            verdict = self.judge(candidate, active_lessons=active_lessons)
            if not verdict.accept:
                self.store.update_candidate_status(candidate.candidate_id, status="rejected")
                continue
            rejection = reject_reason(
                candidate,
                active_lessons=active_lessons,
                normalized_lesson_text=verdict.normalized_lesson_text,
                topic_key=verdict.topic_key,
            )
            if rejection is not None:
                self.store.update_candidate_status(candidate.candidate_id, status="rejected")
                continue
            lesson = SystemLesson(
                lesson_id=f"lesson_{uuid4().hex[:8]}",
                agent_id=agent_id,
                topic_key=verdict.topic_key,
                lesson_text=verdict.normalized_lesson_text.strip(),
                source_fingerprints=candidate.source_fingerprints,
                active=True,
            )
            self.store.save_lesson(lesson)
            self.store.update_candidate_status(candidate.candidate_id, status="accepted")
            accepted.append(lesson)
        if accepted:
            self.export_active_lessons(agent_id=agent_id)
        return accepted

    def export_active_lessons(self, *, agent_id: str) -> None:
        lessons = self.store.list_active_lessons(agent_id=agent_id)
        if not lessons:
            if self.lessons_path.exists():
                self.lessons_path.unlink()
            return
        lines = [
            "# Runtime Learned Lessons",
            "",
            "<!-- Runtime-managed file. active lessons only. superseded or rejected lessons stay in SQLite, not in this file. -->",
            "",
        ]
        for lesson in lessons:
            lines.append(f"- {lesson.lesson_text}")
        self.lessons_path.parent.mkdir(parents=True, exist_ok=True)
        self.lessons_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def make_default_judge(
    llm: LLMClient | None = None,
    *,
    app_id: str = "main_agent",
    agent_id: str = "main",
    min_score: float = 0.8,
) -> LessonJudge:
    if llm is None:
        return _make_fallback_judge(min_score=min_score)
    return _make_llm_judge(
        llm,
        app_id=app_id,
        agent_id=agent_id,
        min_score=min_score,
    )


def _make_fallback_judge(*, min_score: float = 0.8) -> LessonJudge:
    def judge(candidate: LessonCandidate, *, active_lessons: list[SystemLesson]) -> JudgeVerdict:
        topic_key = (
            candidate.source_fingerprints[0].split("|", 1)[-1].replace(" ", "_")[:80]
            if candidate.source_fingerprints
            else "general"
        )
        accept = candidate.score >= min_score and len(candidate.source_fingerprints) >= 2
        return JudgeVerdict(
            accept=accept,
            reason="score_threshold_met" if accept else "score_too_low_or_insufficient_evidence",
            normalized_lesson_text=candidate.candidate_text.strip(),
            topic_key=topic_key,
        )

    return judge


def _make_llm_judge(
    llm: LLMClient,
    *,
    app_id: str,
    agent_id: str,
    min_score: float,
) -> LessonJudge:
    def judge(candidate: LessonCandidate, *, active_lessons: list[SystemLesson]) -> JudgeVerdict:
        fallback = _make_fallback_judge(min_score=min_score)
        if candidate.score < min_score or len(candidate.source_fingerprints) < 2:
            return fallback(candidate, active_lessons=active_lessons)
        request = LLMRequest(
            session_id=f"self_improve_judge:{candidate.candidate_id}",
            trace_id=f"trace_self_improve_judge_{candidate.candidate_id}",
            message=_build_judge_message(candidate, active_lessons=active_lessons),
            agent_id=agent_id,
            app_id=app_id,
            system_prompt=_judge_system_prompt(),
            prompt_mode="compact",
        )
        try:
            reply = llm.complete(request)
            if reply.final_text is None:
                return JudgeVerdict(
                    accept=False,
                    reason="judge_missing_final_text",
                    normalized_lesson_text="",
                    topic_key="",
                )
            parsed = LLMJudgeReply.model_validate(_parse_judge_payload(reply.final_text))
        except Exception:
            return JudgeVerdict(
                accept=False,
                reason="judge_invalid_payload",
                normalized_lesson_text="",
                topic_key="",
            )
        return JudgeVerdict(
            accept=parsed.accept,
            reason=parsed.reason.strip() or "judge_reason_missing",
            normalized_lesson_text=parsed.normalized_lesson_text.strip(),
            topic_key=parsed.topic_key.strip(),
        )

    return judge


def _judge_system_prompt() -> str:
    return (
        "You are the self-improve lesson gate for marten-runtime.\n"
        "Decide whether one candidate lesson is high-value enough for long-term system prompt inclusion.\n"
        "Rules:\n"
        "- Accept only stable, reusable, high-signal lessons.\n"
        "- Reject one-off incidents, vague reminders, speculative advice, or user-specific details.\n"
        "- Do not use tools.\n"
        "- Return exactly one JSON object with keys: accept, reason, normalized_lesson_text, topic_key.\n"
        "- normalized_lesson_text must be concise, imperative, and <= 200 chars.\n"
        "- topic_key must be a short snake_case topic label.\n"
    )


def _build_judge_message(
    candidate: LessonCandidate,
    *,
    active_lessons: list[SystemLesson],
) -> str:
    active_summary = [
        {
            "topic_key": lesson.topic_key,
            "lesson_text": lesson.lesson_text,
        }
        for lesson in active_lessons
    ]
    payload = {
        "candidate": {
            "candidate_id": candidate.candidate_id,
            "candidate_text": candidate.candidate_text,
            "rationale": candidate.rationale,
            "score": candidate.score,
            "source_fingerprints": candidate.source_fingerprints,
        },
        "active_lessons": active_summary,
        "bootstrap_constraints": [
            "Do not modify AGENTS.md",
            "Only high-value reusable lessons may enter SYSTEM_LESSONS.md",
            "SYSTEM_LESSONS.md is active-lessons-only and runtime-managed",
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_judge_payload(text: str) -> dict[str, object]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("missing_json_object")
    return json.loads(cleaned[start : end + 1])
