import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

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

    def test_legacy_sessions_schema_is_upgraded_before_first_get(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            created_at = datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc).isoformat()
            with sqlite3.connect(path) as conn:
                conn.execute(
                    """
                    CREATE TABLE sessions (
                        session_id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO sessions (
                        session_id, conversation_id, state, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    ("sess_legacy", "conv-legacy", "created", created_at, created_at),
                )

            reloaded = SQLiteSessionStore(path).get("sess_legacy")

        self.assertEqual(reloaded.session_id, "sess_legacy")
        self.assertEqual(reloaded.active_agent_id, "main")
        self.assertEqual(reloaded.session_kind, "main")
        self.assertEqual(reloaded.lineage_depth, 0)
        self.assertEqual(reloaded.config_snapshot_id, "cfg_bootstrap")
        self.assertEqual(reloaded.bootstrap_manifest_id, "boot_default")
        self.assertEqual(reloaded.tool_call_count, 0)

    def test_legacy_agent_id_backfills_active_agent_id_before_first_get(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            created_at = datetime(2026, 4, 24, 9, 0, tzinfo=timezone.utc).isoformat()
            with sqlite3.connect(path) as conn:
                conn.execute(
                    """
                    CREATE TABLE sessions (
                        session_id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        agent_id TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO sessions (
                        session_id, conversation_id, state, created_at, updated_at, agent_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("sess_coding", "conv-coding", "created", created_at, created_at, "coding"),
                )

            reloaded = SQLiteSessionStore(path).get("sess_coding")

        self.assertEqual(reloaded.agent_id, "coding")
        self.assertEqual(reloaded.active_agent_id, "coding")

    def test_legacy_assistant_agent_id_is_canonicalized_before_first_get(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            created_at = datetime(2026, 4, 24, 9, 0, tzinfo=timezone.utc).isoformat()
            with sqlite3.connect(path) as conn:
                conn.execute(
                    """
                    CREATE TABLE sessions (
                        session_id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        agent_id TEXT NOT NULL DEFAULT '',
                        active_agent_id TEXT NOT NULL DEFAULT 'main'
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO sessions (
                        session_id, conversation_id, state, created_at, updated_at, agent_id, active_agent_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "sess_legacy_main",
                        "conv-legacy-main",
                        "created",
                        created_at,
                        created_at,
                        "assistant",
                        "assistant",
                    ),
                )

            reloaded = SQLiteSessionStore(path).get("sess_legacy_main")
            with sqlite3.connect(path) as conn:
                row = conn.execute(
                    "SELECT agent_id, active_agent_id FROM sessions WHERE session_id = ?",
                    ("sess_legacy_main",),
                ).fetchone()

        self.assertEqual(reloaded.agent_id, "main")
        self.assertEqual(reloaded.active_agent_id, "main")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(str(row[0]), "main")
        self.assertEqual(str(row[1]), "main")

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

    def test_remove_last_message_if_match_removes_exact_trailing_message(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            store.create(
                session_id="sess_remove",
                conversation_id="conv-remove",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            previous = SessionMessage.user(
                "existing",
                created_at=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            )
            control = SessionMessage.user(
                "切换到新会话",
                created_at=datetime(2026, 4, 21, 9, 1, tzinfo=timezone.utc),
            )
            store.append_message("sess_remove", previous)
            store.append_message("sess_remove", control)

            updated = store.remove_last_message_if_match(
                "sess_remove",
                control,
                restore_updated_at=previous.created_at,
                restore_last_event_at=previous.created_at,
            )

        self.assertEqual([item.content for item in updated.history], ["created", "existing"])
        self.assertEqual(updated.message_count, 1)
        self.assertEqual(updated.updated_at, previous.created_at)
        self.assertEqual(updated.last_event_at, previous.created_at)

    def test_remove_last_message_if_match_keeps_history_when_message_differs(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            store.create(
                session_id="sess_keep",
                conversation_id="conv-keep",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            control = SessionMessage.user(
                "切换到新会话",
                created_at=datetime(2026, 4, 21, 9, 1, tzinfo=timezone.utc),
            )
            store.append_message("sess_keep", control)

            updated = store.remove_last_message_if_match(
                "sess_keep",
                SessionMessage.user(
                    "切换到旧会话",
                    created_at=control.created_at,
                ),
                restore_updated_at=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
                restore_last_event_at=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            )

        self.assertEqual([item.content for item in updated.history], ["created", "切换到新会话"])
        self.assertEqual(updated.message_count, 1)
        self.assertEqual(updated.updated_at, control.created_at)
        self.assertEqual(updated.last_event_at, control.created_at)

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
                preserved_tail_user_turns=5,
                trigger_kind="context_pressure_proactive",
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
        self.assertEqual(reloaded.latest_compacted_context.trigger_kind, "context_pressure_proactive")
        self.assertEqual(reloaded.latest_compacted_context.preserved_tail_user_turns, 5)
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

    def test_empty_user_id_does_not_resolve_user_owned_conversation_binding(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            store.create(
                session_id="sess_user_a",
                conversation_id="conv-shared",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="feishu",
                user_id="user-a",
            )

            resolved = SQLiteSessionStore(path).resolve_session_for_conversation(
                channel_id="feishu",
                conversation_id="conv-shared",
                user_id="",
            )

        self.assertIsNone(resolved)

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

    def test_round_trip_preserves_child_session_owner_metadata(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            parent = store.create(
                session_id="sess_parent_owner",
                conversation_id="conv-parent-owner",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="feishu",
                user_id="user-a",
            )
            store.set_active_agent(parent.session_id, "coding")
            store.set_catalog_metadata(
                parent.session_id,
                user_id="user-a",
                agent_id="coding",
                session_title="parent",
                session_preview="preview",
            )
            store.create_child_session(
                parent_session_id=parent.session_id,
                conversation_id="conv-child-owner",
                session_id="sess_child_owner",
            )

            reloaded = SQLiteSessionStore(path).get("sess_child_owner")

        self.assertEqual(reloaded.channel_id, "feishu")
        self.assertEqual(reloaded.user_id, "user-a")
        self.assertEqual(reloaded.agent_id, "coding")
        self.assertEqual(reloaded.active_agent_id, "coding")

    def test_round_trip_preserves_child_session_target_agent_metadata(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            parent = store.create(
                session_id="sess_parent_target_agent",
                conversation_id="conv-parent-target-agent",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="feishu",
                user_id="user-a",
            )
            store.set_active_agent(parent.session_id, "main")
            store.set_catalog_metadata(
                parent.session_id,
                user_id="user-a",
                agent_id="main",
                session_title="parent",
                session_preview="preview",
            )
            store.create_child_session(
                parent_session_id=parent.session_id,
                conversation_id="conv-child-target-agent",
                session_id="sess_child_target_agent",
                agent_id="coding",
                active_agent_id="coding",
            )

            reloaded = SQLiteSessionStore(path).get("sess_child_target_agent")

        self.assertEqual(reloaded.channel_id, "feishu")
        self.assertEqual(reloaded.user_id, "user-a")
        self.assertEqual(reloaded.agent_id, "coding")
        self.assertEqual(reloaded.active_agent_id, "coding")

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

    def test_compaction_job_round_trip_claim_and_complete(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            session = store.create(
                session_id="sess_job",
                conversation_id="conv-job",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            store.append_message(session.session_id, SessionMessage.user("历史 1"))
            job = store.enqueue_compaction_job(
                source_session_id=session.session_id,
                current_message="切换会话",
                preserved_tail_user_turns=2,
                source_message_range=[0, 2],
                snapshot_message_count=len(store.get(session.session_id).history),
                compaction_profile_name="minimax_m25",
            )

            claimed = store.claim_next_compaction_job()
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["job_id"], job["job_id"])
            self.assertEqual(claimed["status"], "running")
            self.assertIsNotNone(claimed["started_at"])

            store.mark_compaction_job_succeeded(
                job["job_id"],
                queue_wait_ms=12,
                compaction_llm_ms=345,
                persist_ms=8,
                result_reason="generated",
                source_range_end=2,
                write_applied=True,
            )
            reloaded = SQLiteSessionStore(path)
            finished = reloaded.get_compaction_job(job["job_id"])

        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(finished["queue_wait_ms"], 12)
        self.assertEqual(finished["compaction_llm_ms"], 345)
        self.assertEqual(finished["persist_ms"], 8)
        self.assertEqual(finished["result_reason"], "generated")
        self.assertTrue(finished["write_applied"])
        self.assertEqual(finished["compaction_profile_name"], "minimax_m25")
        self.assertIsNotNone(finished["finished_at"])

    def test_compaction_job_schema_adds_missing_profile_column_on_reload(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            enqueued_at = datetime(2026, 4, 23, 11, 0, tzinfo=timezone.utc).isoformat()
            with sqlite3.connect(path) as conn:
                conn.execute(
                    """
                    CREATE TABLE session_compaction_jobs (
                        job_id TEXT PRIMARY KEY,
                        source_session_id TEXT NOT NULL,
                        current_message TEXT NOT NULL,
                        preserved_tail_user_turns INTEGER NOT NULL,
                        source_message_range_json TEXT NOT NULL,
                        snapshot_message_count INTEGER NOT NULL DEFAULT 0,
                        enqueue_status TEXT NOT NULL DEFAULT 'queued',
                        status TEXT NOT NULL DEFAULT 'queued',
                        enqueued_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        queue_wait_ms INTEGER NOT NULL DEFAULT 0,
                        compaction_llm_ms INTEGER NOT NULL DEFAULT 0,
                        persist_ms INTEGER NOT NULL DEFAULT 0,
                        source_range_end INTEGER,
                        write_applied INTEGER NOT NULL DEFAULT 0,
                        result_reason TEXT,
                        error_code TEXT,
                        error_text TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO session_compaction_jobs (
                        job_id, source_session_id, current_message, preserved_tail_user_turns,
                        source_message_range_json, snapshot_message_count, enqueue_status,
                        status, enqueued_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "job_legacy",
                        "sess_legacy",
                        "切换会话",
                        2,
                        "[0, 2]",
                        3,
                        "queued",
                        "queued",
                        enqueued_at,
                    ),
                )

            job = SQLiteSessionStore(path).get_compaction_job("job_legacy")

        self.assertEqual(job["job_id"], "job_legacy")
        self.assertIsNone(job["compaction_profile_name"])

    def test_claim_next_compaction_job_recreates_missing_job_table(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            with sqlite3.connect(path) as conn:
                conn.execute("DROP TABLE session_compaction_jobs")

            claimed = store.claim_next_compaction_job()
            jobs = SQLiteSessionStore(path).list_compaction_jobs()

        self.assertIsNone(claimed)
        self.assertEqual(jobs, [])

    def test_reset_running_compaction_jobs_requeues_stale_jobs(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            session = store.create(
                session_id="sess_job",
                conversation_id="conv-job",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            job = store.enqueue_compaction_job(
                source_session_id=session.session_id,
                current_message="切换会话",
                preserved_tail_user_turns=2,
                source_message_range=[0, 1],
                snapshot_message_count=len(store.get(session.session_id).history),
            )
            claimed = store.claim_next_compaction_job()
            self.assertEqual(claimed["status"], "running")

            store.reset_running_compaction_jobs()
            reloaded = SQLiteSessionStore(path)
            reset_job = reloaded.get_compaction_job(job["job_id"])

        self.assertEqual(reset_job["status"], "queued")
        self.assertIsNone(reset_job["started_at"])
        self.assertEqual(reset_job["result_reason"], "requeued_startup")

    def test_set_compacted_context_if_newer_keeps_new_messages(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            session = store.create(
                session_id="sess_compact",
                conversation_id="conv-compact",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            store.append_message(session.session_id, SessionMessage.user("历史 1"))
            store.append_message(session.session_id, SessionMessage.assistant("历史 1 完成"))
            compacted = CompactedContext(
                compact_id="cmp_new",
                session_id=session.session_id,
                summary_text="压缩摘要",
                source_message_range=[0, 2],
                preserved_tail_user_turns=1,
            )

            store.append_message(session.session_id, SessionMessage.user("最新问题"))
            applied = store.set_compacted_context_if_newer(session.session_id, compacted)
            reloaded = SQLiteSessionStore(path).get(session.session_id)

        self.assertTrue(applied)
        self.assertEqual(reloaded.latest_compacted_context.summary_text, "压缩摘要")
        self.assertEqual(reloaded.history[-1].content, "最新问题")

    def test_set_compacted_context_if_newer_rejects_older_range(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(path)
            session = store.create(
                session_id="sess_compact",
                conversation_id="conv-compact",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            current = CompactedContext(
                compact_id="cmp_current",
                session_id=session.session_id,
                summary_text="新摘要",
                source_message_range=[0, 4],
                preserved_tail_user_turns=1,
            )
            older = CompactedContext(
                compact_id="cmp_old",
                session_id=session.session_id,
                summary_text="旧摘要",
                source_message_range=[0, 2],
                preserved_tail_user_turns=1,
            )
            store.set_compacted_context(session.session_id, current)

            applied = store.set_compacted_context_if_newer(session.session_id, older)
            reloaded = SQLiteSessionStore(path).get(session.session_id)

        self.assertFalse(applied)
        self.assertEqual(reloaded.latest_compacted_context.compact_id, "cmp_current")


if __name__ == "__main__":
    unittest.main()
