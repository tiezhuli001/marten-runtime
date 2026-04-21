import unittest
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from pathlib import Path

from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.session.sqlite_store import SQLiteSessionStore


class SQLiteSessionStoreTests(unittest.TestCase):
    def test_round_trip_restores_created_session(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            created = store.create(
                session_id="sess_1",
                conversation_id="conv-1",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )

            reloaded = SQLiteSessionStore(path).get(created.session_id)

        self.assertEqual(reloaded.session_id, created.session_id)
        self.assertEqual(reloaded.conversation_id, "conv-1")
        self.assertEqual(reloaded.config_snapshot_id, "cfg_bootstrap")
        self.assertEqual(reloaded.bootstrap_manifest_id, "boot_default")

    def test_round_trip_preserves_message_order(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            store.create(
                session_id="sess_msgs",
                conversation_id="conv-msgs",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            store.append_message("sess_msgs", SessionMessage.user("first"))
            store.append_message("sess_msgs", SessionMessage.assistant("second"))

            reloaded = SQLiteSessionStore(path).get("sess_msgs")

        self.assertEqual([item.content for item in reloaded.history[-2:]], ["first", "second"])

    def test_round_trip_preserves_compacted_context_and_usage(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            store.create(
                session_id="sess_state",
                conversation_id="conv-state",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            compacted = CompactedContext(
                compact_id="cmp_1",
                session_id="sess_state",
                summary_text="当前进展：已完成状态恢复。",
                source_message_range=[0, 2],
            )
            usage = NormalizedUsage(
                input_tokens=120,
                output_tokens=30,
                total_tokens=150,
                provider_name="openai",
                model_name="gpt-4.1",
                captured_at=datetime(2026, 4, 19, 12, 0, tzinfo=timezone.utc),
            )
            store.set_compacted_context("sess_state", compacted)
            store.set_latest_actual_usage("sess_state", usage)

            reloaded = SQLiteSessionStore(path).get("sess_state")

        self.assertIsNotNone(reloaded.latest_compacted_context)
        self.assertEqual(reloaded.latest_compacted_context.summary_text, compacted.summary_text)
        self.assertIsNotNone(reloaded.latest_actual_usage)
        self.assertEqual(reloaded.latest_actual_usage.total_tokens, 150)

    def test_round_trip_preserves_recent_tool_outcome_summaries(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            store.create(
                session_id="sess_summary",
                conversation_id="conv-summary",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            store.append_tool_outcome_summary(
                "sess_summary",
                {
                    "summary_id": "sum_1",
                    "run_id": "run_1",
                    "source_kind": "mcp",
                    "summary_text": "上一轮查询了 repo=openai/codex。",
                },
            )

            reloaded = SQLiteSessionStore(path)
            summaries = reloaded.list_recent_tool_outcome_summaries("sess_summary", limit=5)

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].source_kind, "mcp")

    def test_round_trip_restores_conversation_binding(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            created = store.get_or_create_for_conversation(
                conversation_id="conv-binding",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )

            reloaded = SQLiteSessionStore(path).get_or_create_for_conversation(
                conversation_id="conv-binding",
                config_snapshot_id="cfg_other",
                bootstrap_manifest_id="boot_other",
            )

        self.assertEqual(reloaded.session_id, created.session_id)
        self.assertEqual(reloaded.config_snapshot_id, "cfg_bootstrap")

    def test_same_conversation_id_in_different_channels_creates_distinct_sessions(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
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
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
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

            reloaded = SQLiteSessionStore(path)

            self.assertEqual(
                reloaded.resolve_session_for_conversation(
                    channel_id="http",
                    conversation_id="conv-current",
                ),
                target.session_id,
            )
            self.assertIsNone(
                reloaded.resolve_session_for_conversation(
                    channel_id="http",
                    conversation_id="conv-old",
                )
            )
            rebound = reloaded.get(target.session_id)
            self.assertEqual(rebound.conversation_id, "conv-current")
            self.assertEqual(rebound.channel_id, "http")

    def test_round_trip_preserves_child_session_lineage(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            parent = store.create(
                session_id="sess_parent",
                conversation_id="conv-parent",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            store.create_child_session(
                parent_session_id=parent.session_id,
                conversation_id="conv-child",
                session_id="sess_child",
            )

            reloaded = SQLiteSessionStore(path).get("sess_child")

        self.assertEqual(reloaded.parent_session_id, parent.session_id)
        self.assertEqual(reloaded.session_kind, "subagent")
        self.assertEqual(reloaded.lineage_depth, 1)

    def test_round_trip_preserves_catalog_metadata(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            store.create(
                session_id="sess_catalog",
                conversation_id="conv-catalog",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="http",
            )
            store.set_catalog_metadata(
                "sess_catalog",
                user_id="demo",
                agent_id="main",
                session_title="调试 durable session",
                session_preview="验证重启恢复和会话切换。",
            )
            store.append_message("sess_catalog", SessionMessage.user("first turn"))

            reloaded = SQLiteSessionStore(path).get("sess_catalog")

        self.assertEqual(reloaded.channel_id, "http")
        self.assertEqual(reloaded.user_id, "demo")
        self.assertEqual(reloaded.agent_id, "main")
        self.assertEqual(reloaded.session_title, "调试 durable session")
        self.assertEqual(reloaded.session_preview, "验证重启恢复和会话切换。")
        self.assertEqual(reloaded.message_count, 1)

    def test_list_sessions_returns_metadata_without_hydrating_full_history(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            store.create(
                session_id="sess_list",
                conversation_id="conv-list",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="http",
            )
            store.set_catalog_metadata(
                "sess_list",
                user_id="demo",
                agent_id="main",
                session_title="会话列表",
                session_preview="只返回元数据。",
            )
            store.append_message("sess_list", SessionMessage.user("first turn"))

            listed = SQLiteSessionStore(path).list_sessions()

        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].session_title, "会话列表")
        self.assertEqual(listed[0].message_count, 1)
        self.assertEqual(listed[0].history, [])


if __name__ == "__main__":
    unittest.main()
