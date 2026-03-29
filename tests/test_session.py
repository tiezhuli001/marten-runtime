import unittest

from marten_runtime.config.models import ConfigSnapshot
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.session.models import SessionMessage
from marten_runtime.session.store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_create_session_freezes_snapshot_ids(self) -> None:
        store = SessionStore()
        snapshot = ConfigSnapshot()

        record = store.create(
            session_id="sess_1",
            conversation_id="conv-1",
            config_snapshot_id=snapshot.config_snapshot_id,
            bootstrap_manifest_id="boot_default",
        )

        self.assertEqual(record.session_id, "sess_1")
        self.assertEqual(record.conversation_id, "conv-1")
        self.assertEqual(record.config_snapshot_id, snapshot.config_snapshot_id)
        self.assertEqual(record.bootstrap_manifest_id, "boot_default")

    def test_append_message_and_mark_run_updates_session(self) -> None:
        store = SessionStore()
        record = store.create(
            session_id="sess_1",
            conversation_id="conv-1",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )

        message = SessionMessage.user("hello")
        store.append_message("sess_1", message)
        run = InMemoryRunHistory().start(
            session_id=record.session_id,
            trace_id="trace_1",
            config_snapshot_id=record.config_snapshot_id,
            bootstrap_manifest_id=record.bootstrap_manifest_id,
        )
        updated = store.mark_run("sess_1", run.run_id, message.created_at)

        self.assertEqual(updated.last_run_id, run.run_id)
        self.assertEqual(updated.last_event_at, message.created_at)
        self.assertEqual(updated.history[-1].content, "hello")

    def test_get_or_create_by_conversation_reuses_session(self) -> None:
        store = SessionStore()

        first = store.get_or_create_for_conversation(
            conversation_id="conv-1",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        second = store.get_or_create_for_conversation(
            conversation_id="conv-1",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )

        self.assertEqual(first.session_id, second.session_id)


if __name__ == "__main__":
    unittest.main()
