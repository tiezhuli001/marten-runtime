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

    def test_get_or_create_by_conversation_does_not_cross_bind_channels(self) -> None:
        store = SessionStore()

        http_session = store.get_or_create_for_conversation(
            conversation_id="conv-1",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        feishu_session = store.get_or_create_for_conversation(
            conversation_id="conv-1",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="feishu",
        )

        self.assertNotEqual(http_session.session_id, feishu_session.session_id)

    def test_bind_conversation_moves_session_to_new_conversation_exclusively(self) -> None:
        store = SessionStore()
        current = store.create(
            session_id="sess_current",
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

        store.bind_conversation(
            channel_id="http",
            conversation_id=current.conversation_id,
            session_id=target.session_id,
        )

        self.assertEqual(
            store.resolve_session_for_conversation(
                channel_id="http",
                conversation_id="conv-current",
            ),
            target.session_id,
        )
        self.assertIsNone(
            store.resolve_session_for_conversation(
                channel_id="http",
                conversation_id="conv-old",
            )
        )
        rebound = store.get(target.session_id)
        self.assertEqual(rebound.conversation_id, "conv-current")
        self.assertEqual(rebound.channel_id, "http")

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

    def test_create_child_session_preserves_parent_lineage(self) -> None:
        store = SessionStore()
        parent = store.create(
            session_id="sess_parent",
            conversation_id="conv-parent",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )

        child = store.create_child_session(
            parent_session_id=parent.session_id,
            conversation_id="conv-child",
            session_id="sess_child",
        )

        self.assertEqual(child.session_id, "sess_child")
        self.assertEqual(child.parent_session_id, parent.session_id)
        self.assertEqual(child.session_kind, "subagent")
        self.assertEqual(child.lineage_depth, 1)
        self.assertEqual(child.config_snapshot_id, parent.config_snapshot_id)
        self.assertEqual(child.bootstrap_manifest_id, parent.bootstrap_manifest_id)
        self.assertEqual(store.get(child.session_id).parent_session_id, parent.session_id)

    def test_create_session_exposes_catalog_metadata_defaults(self) -> None:
        store = SessionStore()

        record = store.create(
            session_id="sess_catalog",
            conversation_id="conv-catalog",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )

        self.assertEqual(record.channel_id, "http")
        self.assertEqual(record.user_id, "")
        self.assertEqual(record.agent_id, "")
        self.assertEqual(record.session_title, "")
        self.assertEqual(record.session_preview, "")
        self.assertEqual(record.message_count, 0)


if __name__ == "__main__":
    unittest.main()
