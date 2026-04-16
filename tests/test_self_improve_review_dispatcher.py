import unittest
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from marten_runtime.self_improve.models import ReviewTrigger, SkillCandidate
from marten_runtime.self_improve.review_dispatcher import SelfImproveReviewDispatcher
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.subagents.models import SubagentTask
from marten_runtime.subagents.store import InMemorySubagentStore


class _FakeSubagentService:
    def __init__(self, *, queue_state: str = "queued") -> None:
        self.calls: list[dict] = []
        self.queue_state = queue_state
        self.store = InMemorySubagentStore()

    def spawn(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        task = self.store.create(
            label=kwargs["label"],
            parent_session_id=kwargs["parent_session_id"],
            parent_run_id=kwargs["parent_run_id"],
            parent_agent_id=kwargs["parent_agent_id"],
            parent_allowed_tools=list(kwargs.get("parent_allowed_tools", [])),
            origin_channel_id=kwargs.get("origin_channel_id"),
            child_session_id="sess_child_review_1",
            app_id=kwargs["app_id"],
            agent_id=kwargs["agent_id"],
            tool_profile=kwargs["requested_tool_profile"],
            effective_tool_profile=kwargs["requested_tool_profile"],
            context_mode=kwargs["context_mode"],
            task_prompt=kwargs["task"],
            notify_on_finish=kwargs["notify_on_finish"],
            include_parent_session_message=kwargs["include_parent_session_message"],
        )
        if self.queue_state == "running":
            self.store.mark_running(task.task_id)
        return {
            "task_id": task.task_id,
            "status": "accepted",
            "queue_state": self.queue_state,
        }


class _FakeDeliveryClient:
    def __init__(self) -> None:
        self.payloads: list[object] = []

    def deliver(self, payload):  # noqa: ANN001
        self.payloads.append(payload)
        return {"ok": True, "message_id": f"om_{len(self.payloads)}"}


class _FailingDeliveryClient:
    def deliver(self, payload):  # noqa: ANN001
        raise RuntimeError("feishu delivery failed")


class _FakeSkillService:
    def build_runtime(self, *, agent_id: str, channel_id: str, env=None, config=None):  # noqa: ANN001
        del agent_id, channel_id, env, config
        return SimpleNamespace(skill_heads_text="visible review skill head")

    def load_skill(self, skill_id: str):  # noqa: ANN001
        if skill_id != "self_improve_review":
            raise KeyError(skill_id)
        return SimpleNamespace(body="Return structured JSON only.")


class SelfImproveReviewDispatcherTests(unittest.TestCase):
    def test_dispatch_pending_triggers_uses_hidden_runtime_owned_spawn(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="lesson_failure_burst",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                payload_json={"seed": "value"},
                semantic_fingerprint="main|failure-burst|timeout",
            )
            store.save_review_trigger(trigger)
            subagent_service = _FakeSubagentService()
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=subagent_service,
                run_history=SimpleNamespace(
                    get=lambda run_id: SimpleNamespace(session_id="sess_parent")
                ),
                skill_service=_FakeSkillService(),
            )

            spawned = dispatcher.dispatch_pending_triggers(agent_id="main")
            updated = store.get_review_trigger("trigger_1")

        self.assertEqual(len(spawned), 1)
        self.assertTrue(spawned[0].startswith("task_"))
        self.assertEqual(len(subagent_service.calls), 1)
        call = subagent_service.calls[0]
        self.assertEqual(call["requested_tool_profile"], "restricted")
        self.assertFalse(call["notify_on_finish"])
        self.assertFalse(call["include_parent_session_message"])
        self.assertIn("lesson_failure_burst", call["task"])
        self.assertEqual(updated.status, "queued")
        self.assertTrue(updated.payload_json["review_subagent_task_id"].startswith("task_"))
        self.assertEqual(updated.payload_json["review_subagent_queue_state"], "queued")

    def test_dispatch_pending_triggers_records_running_state_when_child_starts_immediately(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="lesson_failure_burst",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                payload_json={"seed": "value"},
                semantic_fingerprint="main|failure-burst|timeout",
            )
            store.save_review_trigger(trigger)
            subagent_service = _FakeSubagentService(queue_state="running")
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=subagent_service,
                run_history=SimpleNamespace(
                    get=lambda run_id: SimpleNamespace(session_id="sess_parent")
                ),
                skill_service=_FakeSkillService(),
            )

            spawned = dispatcher.dispatch_pending_triggers(agent_id="main")
            updated = store.get_review_trigger("trigger_1")

        self.assertEqual(len(spawned), 1)
        self.assertEqual(updated.status, "running")
        self.assertEqual(updated.payload_json["review_subagent_queue_state"], "running")

    def test_dispatch_pending_triggers_serializes_concurrent_spawn_for_same_trigger(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="lesson_failure_burst",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                payload_json={"seed": "value"},
                semantic_fingerprint="main|failure-burst|timeout",
            )
            store.save_review_trigger(trigger)
            subagent_service = _FakeSubagentService()
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=subagent_service,
                run_history=SimpleNamespace(
                    get=lambda run_id: SimpleNamespace(session_id="sess_parent")
                ),
                skill_service=_FakeSkillService(),
            )
            spawned_lists: list[list[str]] = []

            def worker() -> None:
                spawned_lists.append(dispatcher.dispatch_pending_triggers(agent_id="main"))

            first = Thread(target=worker)
            second = Thread(target=worker)
            first.start()
            second.start()
            first.join(timeout=1.0)
            second.join(timeout=1.0)
            updated = store.get_review_trigger("trigger_1")

        self.assertEqual(len(subagent_service.calls), 1)
        self.assertEqual(sum(len(item) for item in spawned_lists), 1)
        self.assertEqual(updated.status, "queued")
        self.assertTrue(updated.payload_json["review_subagent_task_id"].startswith("task_"))

    def test_dispatch_pending_triggers_marks_missing_source_run_failed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_missing_run",
                agent_id="main",
                trigger_kind="lesson_failure_burst",
                source_run_id="run_missing",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                payload_json={"seed": "value"},
                semantic_fingerprint="main|failure-burst|timeout",
            )
            store.save_review_trigger(trigger)
            subagent_service = _FakeSubagentService()
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=subagent_service,
                run_history=SimpleNamespace(get=lambda run_id: (_ for _ in ()).throw(KeyError(run_id))),
                skill_service=_FakeSkillService(),
            )

            spawned = dispatcher.dispatch_pending_triggers(agent_id="main")
            updated = store.get_review_trigger("trigger_missing_run")

        self.assertEqual(spawned, [])
        self.assertEqual(len(subagent_service.calls), 0)
        self.assertEqual(updated.status, "failed")
        self.assertEqual(updated.payload_json["dispatch_failure_reason"], "missing_source_run")
        self.assertEqual(updated.payload_json["dispatch_failure_detail"], "run_missing")

    def test_dispatch_pending_triggers_marks_missing_parent_session_failed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_missing_session",
                agent_id="main",
                trigger_kind="lesson_failure_burst",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                payload_json={"seed": "value"},
                semantic_fingerprint="main|failure-burst|timeout",
            )
            store.save_review_trigger(trigger)
            subagent_service = _FakeSubagentService()
            subagent_service.session_store = SimpleNamespace(
                get=lambda session_id: (_ for _ in ()).throw(KeyError(session_id))
            )
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=subagent_service,
                run_history=SimpleNamespace(
                    get=lambda run_id: SimpleNamespace(session_id="sess_missing")
                ),
                skill_service=_FakeSkillService(),
            )

            spawned = dispatcher.dispatch_pending_triggers(agent_id="main")
            updated = store.get_review_trigger("trigger_missing_session")

        self.assertEqual(spawned, [])
        self.assertEqual(len(subagent_service.calls), 0)
        self.assertEqual(updated.status, "failed")
        self.assertEqual(updated.payload_json["dispatch_failure_reason"], "missing_parent_session")
        self.assertEqual(updated.payload_json["dispatch_failure_detail"], "sess_missing")

    def test_handle_terminal_task_persists_review_proposals(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="complex_successful_tool_episode",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                status="queued",
                payload_json={"review_subagent_task_id": "task_expected"},
                semantic_fingerprint="main|episode|timeout",
            )
            store.save_review_trigger(trigger)
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=_FakeSubagentService(),
                run_history=SimpleNamespace(get=lambda run_id: SimpleNamespace(session_id="sess_parent")),
                skill_service=_FakeSkillService(),
            )

            dispatcher.handle_terminal_task(
                SimpleNamespace(
                    task_id="task_expected",
                    label="self-improve-review:trigger_1",
                    parent_run_id="run_source",
                    parent_agent_id="main",
                    agent_id="main",
                    app_id="main_agent",
                    effective_tool_profile="restricted",
                    notify_on_finish=False,
                    include_parent_session_message=False,
                    status="succeeded",
                    result_summary=(
                        '{"lesson_proposals":[{"candidate_text":"Keep the path narrow.","rationale":"Repeated timeout with recovery.","source_fingerprints":["main|timeout"],"score":0.9}],'
                        '"skill_proposals":[{"title":"Provider Timeout Recovery","slug":"provider-timeout-recovery","summary":"Use a narrower path after repeated timeout.","trigger_conditions":["repeated timeout"],"body_markdown":"# Provider Timeout Recovery","rationale":"Observed repeated recovery workflow.","source_run_ids":["run_source"],"source_fingerprints":["main|timeout"],"confidence":0.93}]}'
                    ),
                )
            )

            trigger_after = store.get_review_trigger("trigger_1")
            lessons = store.list_candidates(agent_id="main", limit=10, status="pending")
            skills = store.list_skill_candidates(agent_id="main", limit=10, status="pending")

        self.assertEqual(trigger_after.status, "processed")
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0].candidate_text, "Keep the path narrow.")
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].slug, "provider-timeout-recovery")

    def test_handle_terminal_task_sends_runtime_owned_feishu_notification_for_new_skill_candidate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="complex_successful_tool_episode",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                status="queued",
                payload_json={
                    "source_channel_id": "feishu",
                    "review_subagent_task_id": "task_expected",
                },
                semantic_fingerprint="main|episode|timeout",
            )
            store.save_review_trigger(trigger)
            subagent_service = _FakeSubagentService()
            subagent_service.session_store = SimpleNamespace(
                get=lambda session_id: SimpleNamespace(conversation_id="oc_test_chat")
            )
            delivery = _FakeDeliveryClient()
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=subagent_service,
                run_history=SimpleNamespace(
                    get=lambda run_id: SimpleNamespace(session_id="sess_parent")
                ),
                skill_service=_FakeSkillService(),
                feishu_delivery=delivery,
            )

            dispatcher.handle_terminal_task(
                SimpleNamespace(
                    task_id="task_expected",
                    label="self-improve-review:trigger_1",
                    parent_run_id="run_source",
                    parent_agent_id="main",
                    agent_id="main",
                    app_id="main_agent",
                    effective_tool_profile="restricted",
                    notify_on_finish=False,
                    include_parent_session_message=False,
                    status="succeeded",
                    result_summary=(
                        '{"lesson_proposals":[],"skill_proposals":[{"title":"Provider Timeout Recovery","slug":"provider-timeout-recovery","summary":"Use a narrower path after repeated timeout.","trigger_conditions":["repeated timeout"],"body_markdown":"# Provider Timeout Recovery","rationale":"Observed repeated recovery workflow.","source_run_ids":["run_source"],"source_fingerprints":["main|timeout"],"confidence":0.93}]}'
                    ),
                )
            )

        self.assertEqual(len(delivery.payloads), 1)
        payload = delivery.payloads[0]
        self.assertEqual(payload.chat_id, "oc_test_chat")
        self.assertEqual(payload.event_type, "final")
        self.assertIn("provider-timeout-recovery", payload.text)

    def test_handle_terminal_task_dedupes_notification_for_existing_pending_skill_candidate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            store.save_skill_candidate(
                SkillCandidate(
                    candidate_id="skillcand_existing",
                    agent_id="main",
                    title="Provider Timeout Recovery",
                    slug="provider-timeout-recovery",
                    summary="Use a narrower path after repeated timeout.",
                    trigger_conditions=["repeated timeout"],
                    body_markdown="# Provider Timeout Recovery",
                    rationale="Observed repeated recovery workflow.",
                    source_run_ids=["run_old"],
                    source_fingerprints=["main|timeout"],
                    confidence=0.93,
                    semantic_fingerprint="provider-timeout-recovery",
                )
            )
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="complex_successful_tool_episode",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                status="queued",
                payload_json={
                    "source_channel_id": "feishu",
                    "review_subagent_task_id": "task_expected",
                },
                semantic_fingerprint="main|episode|timeout",
            )
            store.save_review_trigger(trigger)
            subagent_service = _FakeSubagentService()
            subagent_service.session_store = SimpleNamespace(
                get=lambda session_id: SimpleNamespace(conversation_id="oc_test_chat")
            )
            delivery = _FakeDeliveryClient()
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=subagent_service,
                run_history=SimpleNamespace(
                    get=lambda run_id: SimpleNamespace(session_id="sess_parent")
                ),
                skill_service=_FakeSkillService(),
                feishu_delivery=delivery,
            )

            dispatcher.handle_terminal_task(
                SimpleNamespace(
                    task_id="task_expected",
                    label="self-improve-review:trigger_1",
                    parent_run_id="run_source",
                    parent_agent_id="main",
                    agent_id="main",
                    app_id="main_agent",
                    effective_tool_profile="restricted",
                    notify_on_finish=False,
                    include_parent_session_message=False,
                    status="succeeded",
                    result_summary=(
                        '{"lesson_proposals":[],"skill_proposals":[{"title":"Provider Timeout Recovery","slug":"provider-timeout-recovery","summary":"Use a narrower path after repeated timeout.","trigger_conditions":["repeated timeout"],"body_markdown":"# Provider Timeout Recovery","rationale":"Observed repeated recovery workflow.","source_run_ids":["run_source"],"source_fingerprints":["main|timeout"],"confidence":0.93}]}'
                    ),
                )
            )

            skills = store.list_skill_candidates(agent_id="main", limit=10, status="pending")

        self.assertEqual(len(skills), 1)
        self.assertEqual(len(delivery.payloads), 0)

    def test_handle_terminal_task_dedupes_against_promoted_skill_candidate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            store.save_skill_candidate(
                SkillCandidate(
                    candidate_id="skillcand_existing",
                    agent_id="main",
                    status="promoted",
                    title="Provider Timeout Recovery",
                    slug="provider-timeout-recovery",
                    summary="Use a narrower path after repeated timeout.",
                    trigger_conditions=["repeated timeout"],
                    body_markdown="# Provider Timeout Recovery",
                    rationale="Previously promoted",
                    source_run_ids=["run_old"],
                    source_fingerprints=["main|timeout"],
                    confidence=0.95,
                    semantic_fingerprint="provider-timeout-recovery",
                    promoted_skill_id="provider-timeout-recovery",
                )
            )
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="complex_successful_tool_episode",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                status="queued",
                payload_json={"review_subagent_task_id": "task_expected"},
                semantic_fingerprint="main|episode|timeout",
            )
            store.save_review_trigger(trigger)
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=_FakeSubagentService(),
                run_history=SimpleNamespace(
                    get=lambda run_id: SimpleNamespace(session_id="sess_parent")
                ),
                skill_service=_FakeSkillService(),
            )

            dispatcher.handle_terminal_task(
                SimpleNamespace(
                    task_id="task_expected",
                    label="self-improve-review:trigger_1",
                    parent_run_id="run_source",
                    parent_agent_id="main",
                    agent_id="main",
                    app_id="main_agent",
                    effective_tool_profile="restricted",
                    notify_on_finish=False,
                    include_parent_session_message=False,
                    status="succeeded",
                    result_summary=(
                        '{"lesson_proposals":[],"skill_proposals":[{"title":"Provider Timeout Recovery","slug":"provider-timeout-recovery","summary":"Use a narrower path after repeated timeout.","trigger_conditions":["repeated timeout"],"body_markdown":"# Provider Timeout Recovery","rationale":"Observed repeated recovery workflow.","source_run_ids":["run_source"],"source_fingerprints":["main|timeout"],"confidence":0.93}]}'
                    ),
                )
            )

            skills = store.list_skill_candidates(agent_id="main", limit=10, status=None)
            updated = store.get_review_trigger("trigger_1")

        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].candidate_id, "skillcand_existing")
        self.assertEqual(updated.status, "discarded")

    def test_handle_terminal_task_closes_trigger_even_when_notification_fails(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="complex_successful_tool_episode",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                status="queued",
                payload_json={
                    "source_channel_id": "feishu",
                    "review_subagent_task_id": "task_expected",
                },
                semantic_fingerprint="main|episode|timeout",
            )
            store.save_review_trigger(trigger)
            task = SubagentTask(
                task_id="task_expected",
                label="self-improve-review:trigger_1",
                status="succeeded",
                parent_session_id="sess_parent",
                parent_run_id="run_source",
                parent_agent_id="main",
                parent_allowed_tools=["runtime", "skill", "time"],
                origin_channel_id=None,
                child_session_id="sess_child",
                app_id="main_agent",
                agent_id="main",
                tool_profile="restricted",
                effective_tool_profile="restricted",
                context_mode="brief_only",
                task_prompt="review",
                notify_on_finish=False,
                include_parent_session_message=False,
                result_summary=(
                    '{"lesson_proposals":[],"skill_proposals":[{"title":"Provider Timeout Recovery","slug":"provider-timeout-recovery","summary":"Use a narrower path after repeated timeout.","trigger_conditions":["repeated timeout"],"body_markdown":"# Provider Timeout Recovery","rationale":"Observed repeated recovery workflow.","source_run_ids":["run_source"],"source_fingerprints":["main|timeout"],"confidence":0.93}]}'
                ),
            )
            subagent_service = _FakeSubagentService()
            subagent_service.session_store = SimpleNamespace(
                get=lambda session_id: SimpleNamespace(conversation_id="oc_test_chat")
            )
            subagent_service.store.create(**task.model_dump())
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=subagent_service,
                run_history=SimpleNamespace(
                    get=lambda run_id: SimpleNamespace(session_id="sess_parent")
                ),
                skill_service=_FakeSkillService(),
                feishu_delivery=_FailingDeliveryClient(),
            )

            dispatcher.handle_terminal_task(task)
            updated = store.get_review_trigger("trigger_1")
            skills = store.list_skill_candidates(agent_id="main", limit=10, status="pending")
            dispatcher.dispatch_pending_triggers(agent_id="main")
            skills_after = store.list_skill_candidates(agent_id="main", limit=10, status="pending")

        self.assertEqual(updated.status, "processed")
        self.assertTrue(updated.payload_json["notification_failed"])
        self.assertEqual(len(skills), 1)
        self.assertEqual(len(skills_after), 1)

    def test_handle_terminal_task_is_idempotent_after_processed_status(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="complex_successful_tool_episode",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                status="queued",
                payload_json={"review_subagent_task_id": "task_expected"},
                semantic_fingerprint="main|episode|timeout",
            )
            store.save_review_trigger(trigger)
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=_FakeSubagentService(),
                run_history=SimpleNamespace(
                    get=lambda run_id: SimpleNamespace(session_id="sess_parent")
                ),
                skill_service=_FakeSkillService(),
            )
            task = SimpleNamespace(
                task_id="task_expected",
                label="self-improve-review:trigger_1",
                parent_run_id="run_source",
                parent_agent_id="main",
                agent_id="main",
                app_id="main_agent",
                effective_tool_profile="restricted",
                notify_on_finish=False,
                include_parent_session_message=False,
                status="succeeded",
                result_summary=(
                    '{"lesson_proposals":[],"skill_proposals":[{"title":"Provider Timeout Recovery","slug":"provider-timeout-recovery","summary":"Use a narrower path after repeated timeout.","trigger_conditions":["repeated timeout"],"body_markdown":"# Provider Timeout Recovery","rationale":"Observed repeated recovery workflow.","source_run_ids":["run_source"],"source_fingerprints":["main|timeout"],"confidence":0.93}]}'
                ),
            )

            dispatcher.handle_terminal_task(task)
            first = store.get_review_trigger("trigger_1")
            dispatcher.handle_terminal_task(task)
            second = store.get_review_trigger("trigger_1")
            skills = store.list_skill_candidates(agent_id="main", limit=10, status="pending")

        self.assertEqual(first.status, "processed")
        self.assertEqual(second.status, "processed")
        self.assertEqual(len(skills), 1)

    def test_dispatch_pending_triggers_fails_closed_when_review_skill_asset_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="lesson_failure_burst",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                payload_json={"seed": "value"},
                semantic_fingerprint="main|failure-burst|timeout",
            )
            store.save_review_trigger(trigger)
            subagent_service = _FakeSubagentService()
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=subagent_service,
                run_history=SimpleNamespace(
                    get=lambda run_id: SimpleNamespace(session_id="sess_parent")
                ),
                skill_service=None,
            )

            spawned = dispatcher.dispatch_pending_triggers(agent_id="main")
            updated = store.get_review_trigger("trigger_1")

        self.assertEqual(spawned, [])
        self.assertEqual(len(subagent_service.calls), 0)
        self.assertEqual(updated.status, "failed")
        self.assertEqual(updated.payload_json["dispatch_failure_reason"], "missing_review_skill_asset")

    def test_dispatch_pending_triggers_fails_stale_review_trigger_when_task_is_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            store.save_review_trigger(
                ReviewTrigger(
                    trigger_id="trigger_stale",
                    agent_id="main",
                    trigger_kind="lesson_failure_burst",
                    source_run_id="run_source",
                    source_trace_id="trace_source",
                    source_fingerprints=["main|timeout"],
                    status="queued",
                    payload_json={"review_subagent_task_id": "task_missing"},
                    semantic_fingerprint="main|failure-burst|timeout",
                )
            )
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=_FakeSubagentService(),
                run_history=SimpleNamespace(
                    get=lambda run_id: SimpleNamespace(session_id="sess_parent")
                ),
                skill_service=_FakeSkillService(),
            )

            dispatcher.dispatch_pending_triggers(agent_id="main")
            updated = store.get_review_trigger("trigger_stale")

        self.assertEqual(updated.status, "failed")
        self.assertEqual(updated.payload_json["dispatch_failure_reason"], "missing_review_subagent_task")
        self.assertEqual(updated.payload_json["dispatch_failure_detail"], "task_missing")

    def test_handle_terminal_task_ignores_unexpected_terminal_task_identity(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="complex_successful_tool_episode",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                status="running",
                payload_json={"review_subagent_task_id": "task_expected"},
                semantic_fingerprint="main|episode|timeout",
            )
            store.save_review_trigger(trigger)
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=_FakeSubagentService(),
                run_history=SimpleNamespace(get=lambda run_id: SimpleNamespace(session_id="sess_parent")),
                skill_service=_FakeSkillService(),
            )

            dispatcher.handle_terminal_task(
                SimpleNamespace(
                    task_id="task_spoofed",
                    label="self-improve-review:trigger_1",
                    parent_run_id="run_source",
                    parent_agent_id="main",
                    agent_id="main",
                    app_id="main_agent",
                    effective_tool_profile="restricted",
                    notify_on_finish=False,
                    include_parent_session_message=False,
                    status="succeeded",
                    result_summary='{"lesson_proposals":[],"skill_proposals":[]}',
                )
            )

            trigger_after = store.get_review_trigger("trigger_1")
            skills = store.list_skill_candidates(agent_id="main", limit=10, status="pending")

        self.assertEqual(trigger_after.status, "running")
        self.assertEqual(skills, [])

    def test_handle_terminal_task_skips_invalid_skill_slug(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            trigger = ReviewTrigger(
                trigger_id="trigger_1",
                agent_id="main",
                trigger_kind="complex_successful_tool_episode",
                source_run_id="run_source",
                source_trace_id="trace_source",
                source_fingerprints=["main|timeout"],
                status="queued",
                payload_json={"review_subagent_task_id": "task_expected"},
                semantic_fingerprint="main|episode|timeout",
            )
            store.save_review_trigger(trigger)
            dispatcher = SelfImproveReviewDispatcher(
                store=store,
                subagent_service=_FakeSubagentService(),
                run_history=SimpleNamespace(get=lambda run_id: SimpleNamespace(session_id="sess_parent")),
                skill_service=_FakeSkillService(),
            )

            dispatcher.handle_terminal_task(
                SimpleNamespace(
                    task_id="task_expected",
                    label="self-improve-review:trigger_1",
                    parent_run_id="run_source",
                    parent_agent_id="main",
                    agent_id="main",
                    app_id="main_agent",
                    effective_tool_profile="restricted",
                    notify_on_finish=False,
                    include_parent_session_message=False,
                    status="succeeded",
                    result_summary=(
                        '{"lesson_proposals":[],"skill_proposals":[{"title":"Bad","slug":"../escape","summary":"bad","trigger_conditions":[],"body_markdown":"# Bad","rationale":"bad","source_run_ids":["run_source"],"source_fingerprints":["main|timeout"],"confidence":0.2}]}'
                    ),
                )
            )

            trigger_after = store.get_review_trigger("trigger_1")
            skills = store.list_skill_candidates(agent_id="main", limit=10, status="pending")

        self.assertEqual(trigger_after.status, "discarded")
        self.assertEqual(skills, [])


if __name__ == "__main__":
    unittest.main()
