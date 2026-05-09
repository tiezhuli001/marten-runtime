import unittest
from pathlib import Path
from types import SimpleNamespace

from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.session.sqlite_store import SQLiteSessionStore
from marten_runtime.session.transition import execute_session_transition
from tests.support.session_store_fixtures import temporary_sqlite_session_store


class _QueueingStore(SQLiteSessionStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.enqueued_jobs: list[dict[str, object]] = []
        self.fail_enqueue = False

    def enqueue_compaction_job(self, **payload):  # noqa: ANN003
        if self.fail_enqueue:
            raise RuntimeError("enqueue failed")
        job = super().enqueue_compaction_job(**payload)
        self.enqueued_jobs.append(job)
        return job


class SessionTransitionTests(unittest.TestCase):
    def _store(self):
        return self.enterContext(temporary_sqlite_session_store())

    def _queueing_store(self):
        return self.enterContext(temporary_sqlite_session_store(store_cls=_QueueingStore))

    def test_session_new_defers_source_compaction_when_history_exceeds_replay_tail(self) -> None:
        store = self._queueing_store()
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
            llm=SimpleNamespace(profile_name="minimax_m2_7_highspeed"),
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
        self.assertEqual(result.compaction_job["compaction_profile_name"], "minimax_m2_7_highspeed")
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
        store = self._queueing_store()
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
        self.assertEqual(
            result.compaction_job["snapshot_message_count"],
            len(store.get(source.session_id).history),
        )
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
        store = self._queueing_store()
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
        store = self._store()
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
        store = self._store()
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

    def test_session_new_carryover_ignores_last_control_message_via_current_message_only(self) -> None:
        store = self._store()
        source = store.create(
            session_id="sess_source_anchor",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            source.session_id,
            user_id="user-a",
            agent_id="coding",
            session_title="部署告警排查",
            session_preview="排查部署告警",
        )
        store.append_message(source.session_id, SessionMessage.user("排查部署告警，先看最近部署记录。"))
        store.append_message(source.session_id, SessionMessage.assistant("已定位到最近一次部署。"))
        store.append_message(source.session_id, SessionMessage.user("切换到新会话。"))

        result = execute_session_transition(
            action="new",
            session_store=store,
            source_session_id=source.session_id,
            channel_id="http",
            conversation_id="conv-current",
            current_user_id="user-a",
            current_message="切换到新会话。",
            llm=None,
            replay_user_turns=1,
        )

        carried = store.get(result.session.session_id).latest_compacted_context
        self.assertIsNotNone(carried)
        self.assertIn("排查部署告警，先看最近部署记录。", carried.summary_text)
        self.assertNotIn("切换到新会话。", carried.summary_text)


    def test_replay_keeps_subagent_completion_system_messages_visible(self) -> None:
        from marten_runtime.session.replay import replay_session_messages

        history = [
            SessionMessage.user("把 README 结构梳理放后台。"),
            SessionMessage.assistant("已受理，后台执行。"),
            SessionMessage.system("subagent task completed: README 结构梳理\nsummary: README 包含快速开始、配置和评测入口。"),
            SessionMessage.user("子任务完成了吗？"),
        ]

        replay = replay_session_messages(
            history,
            current_message="子任务完成了吗？",
            user_turns=2,
        )

        self.assertIn("subagent task completed", "\n".join(item.content for item in replay))

    def test_session_transition_skips_compaction_when_existing_checkpoint_is_up_to_date(self) -> None:
        store = self._store()
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


    def test_replay_omits_generic_system_messages(self) -> None:
        from marten_runtime.session.replay import replay_session_messages

        history = [
            SessionMessage.system("created"),
            SessionMessage.user("继续"),
        ]

        replay = replay_session_messages(
            history,
            current_message="继续",
            user_turns=2,
        )

        self.assertNotIn("created", "\n".join(item.content for item in replay))

    def test_session_new_carries_task_anchor_checkpoint_into_target_session(self) -> None:
        store = self._store()
        source = store.create(
            session_id="sess_source",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
            user_id="user-a",
        )
        store.set_catalog_metadata(
            source.session_id,
            user_id="user-a",
            agent_id="main",
            session_title="部署告警排查",
            session_preview="当前目标：排查部署告警。",
        )
        store.append_message(
            source.session_id,
            SessionMessage.user("我正在排查部署告警，请记住这个任务。"),
        )
        store.append_message(
            source.session_id,
            SessionMessage.assistant("已记住，当前目标：排查部署告警。"),
        )

        result = execute_session_transition(
            action="new",
            session_store=store,
            source_session_id=source.session_id,
            channel_id="http",
            conversation_id="conv-current",
            current_user_id="user-a",
            current_message="切换到新会话",
            llm=None,
            replay_user_turns=8,
        )

        target = store.get(result.target_session_id)
        self.assertIsNotNone(target.latest_compacted_context)
        assert target.latest_compacted_context is not None
        self.assertIn("当前目标：排查部署告警。", target.latest_compacted_context.summary_text)
        self.assertIn("在新会话里继续", target.latest_compacted_context.next_step or "")
        self.assertIn("部署告警排查", target.latest_compacted_context.next_step or "")
        self.assertIn("部署告警排查", target.latest_compacted_context.open_todos)


if __name__ == "__main__":
    unittest.main()
