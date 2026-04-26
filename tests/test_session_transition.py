import unittest
from types import SimpleNamespace

from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.session.store import SessionStore
from marten_runtime.session.transition import execute_session_transition


class _QueueingStore(SessionStore):
    def __init__(self) -> None:
        super().__init__()
        self.enqueued_jobs: list[dict[str, object]] = []
        self.fail_enqueue = False

    def enqueue_compaction_job(self, **payload):  # noqa: ANN003
        if self.fail_enqueue:
            raise RuntimeError("enqueue failed")
        job = {
            "job_id": f"job_{len(self.enqueued_jobs) + 1}",
            "enqueue_status": "queued",
            **payload,
        }
        self.enqueued_jobs.append(job)
        return job


class SessionTransitionTests(unittest.TestCase):
    def test_session_new_defers_source_compaction_when_history_exceeds_replay_tail(self) -> None:
        store = _QueueingStore()
        source = store.create(
            session_id="sess_source",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_active_agent(source.session_id, "coding")
        store.set_catalog_metadata(
            source.session_id,
            user_id="user-a",
            agent_id="coding",
            session_title="source",
            session_preview="source preview",
        )
        store.append_message(source.session_id, SessionMessage.user("历史 1"))
        store.append_message(source.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(source.session_id, SessionMessage.user("历史 2"))
        store.append_message(source.session_id, SessionMessage.assistant("历史 2 完成"))
        store.append_message(source.session_id, SessionMessage.user("切到新会话"))

        result = execute_session_transition(
            action="new",
            session_store=store,
            source_session_id=source.session_id,
            channel_id="http",
            conversation_id="conv-current",
            current_user_id="user-a",
            current_message="切到新会话",
            llm=SimpleNamespace(profile_name="minimax_m25"),
            replay_user_turns=1,
        )

        self.assertNotEqual(result.session.session_id, source.session_id)
        self.assertTrue(result.compaction_attempted)
        self.assertFalse(result.compaction_succeeded)
        self.assertEqual(result.compaction_reason, "deferred")
        self.assertEqual(result.compaction_job["enqueue_status"], "queued")
        self.assertEqual(result.compaction_job["source_session_id"], source.session_id)
        self.assertEqual(result.compaction_job["current_message"], "切到新会话")
        self.assertEqual(result.compaction_job["preserved_tail_user_turns"], 1)
        self.assertEqual(result.compaction_job["compaction_profile_name"], "minimax_m25")
        self.assertEqual(
            store.resolve_session_for_conversation(
                channel_id="http",
                conversation_id="conv-current",
                user_id="user-a",
            ),
            result.session.session_id,
        )
        self.assertEqual(store.get(result.session.session_id).active_agent_id, "coding")
        self.assertIsNone(store.get(source.session_id).latest_compacted_context)
        self.assertEqual(len(store.enqueued_jobs), 1)

    def test_session_resume_defers_source_compaction_after_rebinding(self) -> None:
        store = _QueueingStore()
        source = store.create(
            session_id="sess_source",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        target = store.create(
            session_id="sess_target",
            conversation_id="conv-old",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.append_message(source.session_id, SessionMessage.user("历史 1"))
        store.append_message(source.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(source.session_id, SessionMessage.user("历史 2"))
        store.append_message(source.session_id, SessionMessage.assistant("历史 2 完成"))
        store.append_message(source.session_id, SessionMessage.user("恢复旧会话"))

        result = execute_session_transition(
            action="resume",
            session_store=store,
            source_session_id=source.session_id,
            target_session_id=target.session_id,
            channel_id="http",
            conversation_id="conv-current",
            current_user_id="user-a",
            current_message="恢复旧会话",
            llm=None,
            replay_user_turns=1,
        )

        self.assertEqual(result.session.session_id, target.session_id)
        self.assertTrue(result.compaction_attempted)
        self.assertFalse(result.compaction_succeeded)
        self.assertEqual(result.compaction_reason, "deferred")
        self.assertEqual(result.compaction_job["enqueue_status"], "queued")
        self.assertEqual(result.compaction_job["source_session_id"], source.session_id)
        self.assertEqual(result.compaction_job["snapshot_message_count"], len(source.history))
        self.assertEqual(
            store.resolve_session_for_conversation(
                channel_id="http",
                conversation_id="conv-current",
                user_id="user-a",
            ),
            target.session_id,
        )
        self.assertIsNone(
            store.resolve_session_for_conversation(
                channel_id="http",
                conversation_id="conv-old",
                user_id="user-a",
            )
        )
        self.assertIsNone(store.get(source.session_id).latest_compacted_context)
        self.assertEqual(len(store.enqueued_jobs), 1)

    def test_session_transition_keeps_existing_checkpoint_when_enqueue_fails(self) -> None:
        store = _QueueingStore()
        source = store.create(
            session_id="sess_source",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        target = store.create(
            session_id="sess_target",
            conversation_id="conv-old",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        old_compacted = CompactedContext(
            compact_id="cmp_old",
            session_id=source.session_id,
            summary_text="旧摘要",
            source_message_range=[0, 2],
            preserved_tail_user_turns=1,
        )
        store.set_compacted_context(source.session_id, old_compacted)
        store.append_message(source.session_id, SessionMessage.user("历史 1"))
        store.append_message(source.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(source.session_id, SessionMessage.user("历史 2"))
        store.append_message(source.session_id, SessionMessage.assistant("历史 2 完成"))
        store.append_message(source.session_id, SessionMessage.user("恢复旧会话"))
        store.fail_enqueue = True

        result = execute_session_transition(
            action="resume",
            session_store=store,
            source_session_id=source.session_id,
            target_session_id=target.session_id,
            channel_id="http",
            conversation_id="conv-current",
            current_user_id="user-a",
            current_message="恢复旧会话",
            llm=None,
            replay_user_turns=1,
        )

        self.assertEqual(result.session.session_id, target.session_id)
        self.assertTrue(result.compaction_attempted)
        self.assertFalse(result.compaction_succeeded)
        self.assertEqual(result.compaction_reason, "enqueue_failed")
        self.assertEqual(result.compaction_job["enqueue_status"], "failed")
        self.assertEqual(
            store.get(source.session_id).latest_compacted_context.compact_id,
            old_compacted.compact_id,
        )

    def test_session_transition_skips_compaction_when_target_session_is_unchanged(self) -> None:
        store = SessionStore()
        source = store.create(
            session_id="sess_source",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.append_message(source.session_id, SessionMessage.user("历史 1"))
        store.append_message(source.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(source.session_id, SessionMessage.user("历史 2"))
        store.append_message(source.session_id, SessionMessage.assistant("历史 2 完成"))
        store.append_message(source.session_id, SessionMessage.user("恢复当前会话"))
        result = execute_session_transition(
            action="resume",
            session_store=store,
            source_session_id=source.session_id,
            target_session_id=source.session_id,
            channel_id="http",
            conversation_id="conv-current",
            current_user_id="user-a",
            current_message="恢复当前会话",
            llm=None,
            replay_user_turns=1,
        )

        self.assertEqual(result.session.session_id, source.session_id)
        self.assertFalse(result.compaction_attempted)
        self.assertFalse(result.compaction_succeeded)
        self.assertEqual(result.compaction_reason, "same_session")
        self.assertIsNone(result.compaction_job)

    def test_session_transition_skips_compaction_when_history_fits_replay_tail(self) -> None:
        store = SessionStore()
        source = store.create(
            session_id="sess_source",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.append_message(source.session_id, SessionMessage.user("历史 1"))
        store.append_message(source.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(source.session_id, SessionMessage.user("切到新会话"))
        result = execute_session_transition(
            action="new",
            session_store=store,
            source_session_id=source.session_id,
            channel_id="http",
            conversation_id="conv-current",
            current_user_id="user-a",
            current_message="切到新会话",
            llm=None,
            replay_user_turns=1,
        )

        self.assertFalse(result.compaction_attempted)
        self.assertFalse(result.compaction_succeeded)
        self.assertEqual(result.compaction_reason, "no_prefix")
        self.assertIsNone(result.compaction_job)

    def test_session_transition_skips_compaction_when_existing_checkpoint_is_up_to_date(self) -> None:
        store = SessionStore()
        source = store.create(
            session_id="sess_source",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_compacted_context(
            source.session_id,
            CompactedContext(
                compact_id="cmp_current",
                session_id=source.session_id,
                summary_text="当前摘要",
                source_message_range=[0, 3],
                preserved_tail_user_turns=1,
            ),
        )
        store.append_message(source.session_id, SessionMessage.user("历史 1"))
        store.append_message(source.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(source.session_id, SessionMessage.user("历史 2"))
        store.append_message(source.session_id, SessionMessage.assistant("历史 2 完成"))
        store.append_message(source.session_id, SessionMessage.user("切到新会话"))
        result = execute_session_transition(
            action="new",
            session_store=store,
            source_session_id=source.session_id,
            channel_id="http",
            conversation_id="conv-current",
            current_user_id="user-a",
            current_message="切到新会话",
            llm=None,
            replay_user_turns=1,
        )

        self.assertFalse(result.compaction_attempted)
        self.assertFalse(result.compaction_succeeded)
        self.assertEqual(result.compaction_reason, "up_to_date")
        self.assertIsNone(result.compaction_job)


if __name__ == "__main__":
    unittest.main()
