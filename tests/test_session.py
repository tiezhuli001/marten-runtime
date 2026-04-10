import unittest
from datetime import datetime, timezone

from marten_runtime.config.models import ConfigSnapshot
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compacted_context import CompactedContext
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

    def test_session_store_persists_latest_compacted_context(self) -> None:
        store = SessionStore()
        store.create(
            session_id="sess_compact",
            conversation_id="conv-compact",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )

        compacted = CompactedContext(
            compact_id="cmp_1",
            session_id="sess_compact",
            summary_text="当前进展：已完成 A。",
            source_message_range=[0, 2],
        )
        updated = store.set_compacted_context("sess_compact", compacted)

        self.assertEqual(updated.latest_compacted_context, compacted)
        self.assertEqual(updated.last_compacted_at, compacted.created_at)

    def test_session_store_updates_last_compacted_at_without_clobbering_history(self) -> None:
        store = SessionStore()
        store.create(
            session_id="sess_compact_2",
            conversation_id="conv-compact-2",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        message = SessionMessage.user("hello")
        store.append_message("sess_compact_2", message)

        compacted = CompactedContext(
            compact_id="cmp_2",
            session_id="sess_compact_2",
            summary_text="当前进展：hello 已记录。",
            source_message_range=[0, 1],
        )
        updated = store.set_compacted_context("sess_compact_2", compacted)

        self.assertEqual(updated.history[-1].content, "hello")
        self.assertEqual(updated.last_compacted_at, compacted.created_at)

    def test_session_store_persists_latest_actual_usage(self) -> None:
        store = SessionStore()
        store.create(
            session_id="sess_usage",
            conversation_id="conv-usage",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )

        usage = NormalizedUsage(
            input_tokens=200,
            output_tokens=20,
            total_tokens=220,
            provider_name="openai",
            model_name="gpt-4.1",
            captured_at=datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc),
        )
        updated = store.set_latest_actual_usage("sess_usage", usage)

        self.assertIsNotNone(updated.latest_actual_usage)
        assert updated.latest_actual_usage is not None
        self.assertEqual(updated.latest_actual_usage.total_tokens, 220)

    def test_session_store_persists_recent_tool_outcome_summaries_separately_from_history(self) -> None:
        store = SessionStore()
        store.create(
            session_id="sess_tool_summary",
            conversation_id="conv-tool-summary",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        store.append_message("sess_tool_summary", SessionMessage.user("hello"))

        updated = store.append_tool_outcome_summary(
            "sess_tool_summary",
            {
                "summary_id": "sum_1",
                "run_id": "run_1",
                "source_kind": "mcp",
                "summary_text": "上一轮通过 github MCP 查询了 repo=openai/codex。",
            },
        )

        self.assertEqual(updated.history[-1].content, "hello")
        self.assertEqual(len(updated.recent_tool_outcome_summaries), 1)
        self.assertEqual(updated.recent_tool_outcome_summaries[0].source_kind, "mcp")


if __name__ == "__main__":
    unittest.main()
