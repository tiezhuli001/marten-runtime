from __future__ import annotations

import logging
import threading
from copy import deepcopy
from uuid import uuid4

from marten_runtime.channels.feishu.delivery import FeishuDeliveryPayload
from marten_runtime.self_improve.models import LessonCandidate, ReviewTrigger, SkillCandidate
from marten_runtime.self_improve.review_child_contract import parse_review_child_result
from marten_runtime.self_improve.review_payloads import build_review_payload, build_review_prompt
from marten_runtime.self_improve.promotion import _validate_skill_slug
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.skills.service import SkillService

logger = logging.getLogger(__name__)


class SelfImproveReviewDispatcher:
    def __init__(
        self,
        *,
        store: SQLiteSelfImproveStore,
        subagent_service,
        run_history,
        skill_service: SkillService | None = None,
        feishu_delivery=None,
        app_id: str = "main_agent",
        agent_id: str = "main",
    ) -> None:
        self.store = store
        self.subagent_service = subagent_service
        self.run_history = run_history
        self.skill_service = skill_service
        self.feishu_delivery = feishu_delivery
        self.app_id = app_id
        self.agent_id = agent_id
        self._lock = threading.RLock()

    def dispatch_pending_triggers(self, *, agent_id: str) -> list[str]:
        with self._lock:
            spawned: list[str] = []
            self._reconcile_inflight_triggers(agent_id=agent_id)
            for trigger in self.store.list_review_triggers(
                agent_id=agent_id, limit=20, status="pending"
            ):
                source_run = self._get_source_run(trigger)
                if source_run is None:
                    continue
                parent_session_id = self._get_parent_session_id(trigger, source_run)
                if parent_session_id is None:
                    continue
                payload = build_review_payload(
                    trigger=trigger,
                    store=self.store,
                    skill_service=self.skill_service,
                )
                review_skill_text = self._load_review_skill_text()
                if review_skill_text is None:
                    self._mark_trigger_failed(
                        trigger,
                        reason="missing_review_skill_asset",
                        detail="self_improve_review",
                    )
                    continue
                try:
                    accepted = self.subagent_service.spawn(
                        task=build_review_prompt(payload, review_skill_text=review_skill_text),
                        label=self._label(trigger.trigger_id),
                        parent_session_id=parent_session_id,
                        parent_run_id=trigger.source_run_id,
                        parent_agent_id=agent_id,
                        app_id=self.app_id,
                        agent_id=self.agent_id,
                        requested_tool_profile="restricted",
                        parent_allowed_tools=["runtime", "skill", "time"],
                        context_mode="brief_only",
                        notify_on_finish=False,
                        include_parent_session_message=False,
                    )
                except Exception as exc:
                    self._mark_trigger_failed(
                        trigger,
                        reason="review_spawn_failed",
                        detail=str(exc),
                    )
                    continue
                updated = trigger.model_copy(
                    update={
                        "status": accepted.get("queue_state", "queued"),
                        "payload_json": {
                            **deepcopy(trigger.payload_json),
                            "review_subagent_task_id": accepted["task_id"],
                            "review_subagent_queue_state": accepted.get("queue_state", "queued"),
                        },
                    }
                )
                self.store.save_review_trigger(updated)
                spawned.append(accepted["task_id"])
            return spawned

    def handle_terminal_task(self, task) -> None:  # noqa: ANN001
        trigger_id = self._trigger_id_from_label(getattr(task, "label", ""))
        if trigger_id is None:
            return
        with self._lock:
            try:
                trigger = self.store.get_review_trigger(trigger_id)
            except KeyError:
                return
            if trigger.status in {"processed", "discarded", "failed"}:
                return
            if not self._is_expected_review_terminal_task(trigger, task):
                logger.warning(
                    "ignoring unexpected terminal task for self-improve review",
                    extra={
                        "trigger_id": trigger_id,
                        "task_id": getattr(task, "task_id", None),
                        "label": getattr(task, "label", None),
                    },
                )
                return
            if task.status != "succeeded" or not task.result_summary:
                self.store.update_review_trigger_status(trigger_id, status="failed")
                return
            try:
                result = parse_review_child_result(task.result_summary)
            except Exception:
                self.store.update_review_trigger_status(trigger_id, status="failed")
                return
            saved_any = False
            new_skill_candidates: list[SkillCandidate] = []
            for lesson in result.lesson_proposals:
                self.store.save_candidate(
                    LessonCandidate(
                        candidate_id=f"cand_{uuid4().hex[:8]}",
                        agent_id=trigger.agent_id,
                        source_fingerprints=lesson.source_fingerprints or trigger.source_fingerprints,
                        candidate_text=lesson.candidate_text,
                        rationale=lesson.rationale,
                        score=lesson.score,
                    )
                )
                saved_any = True
            for skill in result.skill_proposals:
                try:
                    normalized_slug = _validate_skill_slug(skill.slug)
                except ValueError:
                    continue
                semantic_fingerprint = (
                    normalized_slug
                    or f"{trigger.agent_id}|{trigger.trigger_kind}|{uuid4().hex[:6]}"
                )
                existing = self.store.latest_skill_candidate_by_semantic_fingerprint(
                    agent_id=trigger.agent_id,
                    semantic_fingerprint=semantic_fingerprint,
                )
                if existing is not None and existing.status != "rejected":
                    continue
                self.store.save_skill_candidate(
                    SkillCandidate(
                        candidate_id=f"skillcand_{uuid4().hex[:8]}",
                        agent_id=trigger.agent_id,
                        title=skill.title,
                        slug=normalized_slug,
                        summary=skill.summary,
                        trigger_conditions=skill.trigger_conditions,
                        body_markdown=skill.body_markdown,
                        rationale=skill.rationale,
                        source_run_ids=skill.source_run_ids or [trigger.source_run_id],
                        source_fingerprints=skill.source_fingerprints or trigger.source_fingerprints,
                        confidence=skill.confidence,
                        semantic_fingerprint=semantic_fingerprint,
                    )
                )
                new_skill_candidates.append(
                    self.store.latest_skill_candidate_by_semantic_fingerprint(
                        agent_id=trigger.agent_id,
                        semantic_fingerprint=semantic_fingerprint,
                        status="pending",
                    )
                )
                saved_any = True
            final_status = "processed" if saved_any else "discarded"
            payload = deepcopy(trigger.payload_json)
            try:
                self._notify_new_skill_candidates(
                    trigger,
                    [item for item in new_skill_candidates if item is not None],
                )
            except Exception as exc:
                logger.exception(
                    "skill candidate notification failed",
                    extra={"trigger_id": trigger_id},
                )
                payload["notification_failed"] = True
                payload["notification_failure_detail"] = str(exc)
            self.store.save_review_trigger(
                trigger.model_copy(
                    update={
                        "status": final_status,
                        "payload_json": payload,
                    }
                )
            )

    def _reconcile_inflight_triggers(self, *, agent_id: str) -> None:
        task_store = getattr(self.subagent_service, "store", None)
        if task_store is None:
            return
        inflight = []
        inflight.extend(
            self.store.list_review_triggers(agent_id=agent_id, limit=100, status="queued")
        )
        inflight.extend(
            self.store.list_review_triggers(agent_id=agent_id, limit=100, status="running")
        )
        for trigger in inflight:
            task_id = str(trigger.payload_json.get("review_subagent_task_id") or "").strip()
            if not task_id:
                self._mark_trigger_failed(
                    trigger,
                    reason="missing_review_subagent_task_id",
                    detail=trigger.trigger_id,
                )
                continue
            try:
                task = task_store.get(task_id)
            except KeyError:
                self._mark_trigger_failed(
                    trigger,
                    reason="missing_review_subagent_task",
                    detail=task_id,
                )
                continue
            if getattr(task, "status", "") in {"succeeded", "failed", "cancelled", "timed_out"}:
                self.handle_terminal_task(task)
                continue
            runtime_status = getattr(task, "status", "")
            if runtime_status in {"queued", "running"} and trigger.status != runtime_status:
                self.store.save_review_trigger(
                    trigger.model_copy(
                        update={
                            "status": runtime_status,
                            "payload_json": {
                                **deepcopy(trigger.payload_json),
                                "review_subagent_queue_state": runtime_status,
                            },
                        }
                    )
                )

    @staticmethod
    def _label(trigger_id: str) -> str:
        return f"self-improve-review:{trigger_id}"

    @staticmethod
    def _trigger_id_from_label(label: str) -> str | None:
        prefix = "self-improve-review:"
        if not label.startswith(prefix):
            return None
        return label[len(prefix) :]

    def _get_source_run(self, trigger: ReviewTrigger):  # noqa: ANN202, ANN001
        try:
            return self.run_history.get(trigger.source_run_id)
        except KeyError:
            self._mark_trigger_failed(
                trigger,
                reason="missing_source_run",
                detail=trigger.source_run_id,
            )
            return None

    def _get_parent_session_id(self, trigger: ReviewTrigger, source_run):  # noqa: ANN001, ANN202
        parent_session_id = str(getattr(source_run, "session_id", "") or "").strip()
        if not parent_session_id:
            self._mark_trigger_failed(
                trigger,
                reason="missing_source_session_id",
                detail=trigger.source_run_id,
            )
            return None
        session_store = getattr(self.subagent_service, "session_store", None)
        if session_store is None:
            return parent_session_id
        try:
            session_store.get(parent_session_id)
        except KeyError:
            self._mark_trigger_failed(
                trigger,
                reason="missing_parent_session",
                detail=parent_session_id,
            )
            return None
        return parent_session_id

    def _mark_trigger_failed(
        self,
        trigger: ReviewTrigger,
        *,
        reason: str,
        detail: str,
    ) -> None:
        payload = deepcopy(trigger.payload_json)
        payload["dispatch_failure_reason"] = reason
        payload["dispatch_failure_detail"] = detail
        self.store.save_review_trigger(
            trigger.model_copy(
                update={
                    "status": "failed",
                    "payload_json": payload,
                }
            )
        )

    def _is_expected_review_terminal_task(self, trigger: ReviewTrigger, task) -> bool:  # noqa: ANN001
        expected_task_id = str(trigger.payload_json.get("review_subagent_task_id") or "").strip()
        if not expected_task_id:
            return False
        if str(getattr(task, "task_id", "") or "").strip() != expected_task_id:
            return False
        if str(getattr(task, "parent_run_id", "") or "").strip() != trigger.source_run_id:
            return False
        if str(getattr(task, "parent_agent_id", "") or "").strip() != trigger.agent_id:
            return False
        if str(getattr(task, "agent_id", "") or "").strip() != self.agent_id:
            return False
        if str(getattr(task, "app_id", "") or "").strip() != self.app_id:
            return False
        if str(getattr(task, "effective_tool_profile", "") or "").strip() != "restricted":
            return False
        if bool(getattr(task, "notify_on_finish", True)):
            return False
        if bool(getattr(task, "include_parent_session_message", True)):
            return False
        return True

    def _load_review_skill_text(self) -> str | None:
        if self.skill_service is None:
            return None
        try:
            skill = self.skill_service.load_skill("self_improve_review")
        except KeyError:
            return None
        return skill.body

    def _notify_new_skill_candidates(
        self,
        trigger: ReviewTrigger,
        candidates: list[SkillCandidate],
    ) -> None:
        if not candidates or self.feishu_delivery is None:
            return
        source_channel_id = str(trigger.payload_json.get("source_channel_id") or "").strip()
        if source_channel_id != "feishu":
            return
        try:
            source_run = self.run_history.get(trigger.source_run_id)
            session_store = getattr(self.subagent_service, "session_store", None)
            if session_store is None:
                return
            parent_session = session_store.get(source_run.session_id)
        except KeyError:
            return
        chat_id = str(getattr(parent_session, "conversation_id", "") or "").strip()
        if not chat_id:
            return
        text = self._build_skill_candidate_notification_text(candidates)
        self.feishu_delivery.deliver(
            FeishuDeliveryPayload(
                chat_id=chat_id,
                event_type="final",
                event_id=f"evt_skill_candidate_{candidates[0].candidate_id}",
                run_id=trigger.source_run_id,
                trace_id=trigger.source_trace_id,
                sequence=1,
                text=text,
                dedupe_key=f"skill-candidate:{trigger.agent_id}:{candidates[0].semantic_fingerprint}",
            )
        )

    @staticmethod
    def _build_skill_candidate_notification_text(
        candidates: list[SkillCandidate],
    ) -> str:
        if len(candidates) == 1:
            slug = candidates[0].slug
            return (
                f"我总结了一个新的 skill 候选：`{slug}`。"
                "如果你需要，我可以继续展示详情或帮你确认是否采纳。"
            )
        slugs = ", ".join(f"`{item.slug}`" for item in candidates[:2])
        more = "" if len(candidates) <= 2 else f" 等 {len(candidates)} 个"
        return (
            f"我总结了新的 skill 候选：{slugs}{more}。"
            "如果你需要，我可以继续展示详情或帮你确认是否采纳。"
        )
