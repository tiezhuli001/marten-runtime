import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage
from marten_runtime.session.sqlite_store import SQLiteSessionStore
from marten_runtime.session.store import SessionStore
from marten_runtime.tools.builtins.session_tool import run_session_tool


class _FailingLLM:
    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("compact failed")


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


class SessionToolTests(unittest.TestCase):
    def test_session_tool_requires_explicit_action(self) -> None:
        store = SessionStore()

        with self.assertRaisesRegex(ValueError, "action is required"):
            run_session_tool({}, session_store=store, tool_context={})

    def test_session_tool_lists_and_shows_sessions(self) -> None:
        store = SessionStore()
        record = store.create(
            session_id="sess_1",
            conversation_id="conv-1",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            record.session_id,
            user_id="demo",
            agent_id="main",
            session_title="修复会话切换",
            session_preview="实现 list/show/new/resume。",
        )

        listed = run_session_tool(
            {"action": "list"},
            session_store=store,
            tool_context={"user_id": "demo"},
        )
        detail = run_session_tool(
            {"action": "show", "session_id": record.session_id},
            session_store=store,
            tool_context={"user_id": "demo"},
        )

        self.assertEqual(listed["action"], "list")
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["session_id"], record.session_id)
        self.assertEqual(detail["action"], "show")
        self.assertEqual(detail["session"]["session_title"], "修复会话切换")
        self.assertEqual(detail["session"]["compact_summary"], "实现 list/show/new/resume。")

    def test_session_tool_list_marks_current_session(self) -> None:
        store = SessionStore()
        current = store.create(
            session_id="sess_current",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            current.session_id,
            user_id="demo",
            agent_id="main",
            session_title="当前排查",
            session_preview="当前对话",
        )
        other = store.create(
            session_id="sess_other",
            conversation_id="conv-other",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            other.session_id,
            user_id="demo",
            agent_id="main",
            session_title="历史排查",
            session_preview="历史对话",
        )

        listed = run_session_tool(
            {"action": "list"},
            session_store=store,
            tool_context={"user_id": "demo", "session_id": current.session_id},
        )

        self.assertEqual(listed["current_session"]["session_id"], current.session_id)
        self.assertTrue(listed["items"][0]["is_current"])
        self.assertFalse(listed["items"][1]["is_current"])

    def test_session_tool_show_prefers_compacted_summary_text(self) -> None:
        store = SessionStore()
        record = store.create(
            session_id="sess_summary",
            conversation_id="conv-summary",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            record.session_id,
            user_id="demo",
            agent_id="main",
            session_title="修复摘要",
            session_preview="列表预览文本。",
        )
        store.set_compacted_context(
            record.session_id,
            CompactedContext(
                compact_id="cmp_1",
                session_id=record.session_id,
                summary_text="当前进展：已经完成 durable session 恢复。",
                source_message_range=[0, 2],
            ),
        )

        detail = run_session_tool(
            {"action": "show", "session_id": record.session_id},
            session_store=store,
            tool_context={"user_id": "demo"},
        )

        self.assertEqual(
            detail["session"]["compact_summary"],
            "当前进展：已经完成 durable session 恢复。",
        )

    def test_session_tool_show_exposes_compact_metadata_fields(self) -> None:
        store = SessionStore()
        record = store.create(
            session_id="sess_summary_meta",
            conversation_id="conv-summary-meta",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        compacted = CompactedContext(
            compact_id="cmp_meta",
            session_id=record.session_id,
            summary_text="当前进展：已经完成 durable session 恢复。",
            source_message_range=[0, 4],
            preserved_tail_user_turns=3,
        )
        store.set_compacted_context(record.session_id, compacted)

        detail = run_session_tool(
            {"action": "show", "session_id": record.session_id},
            session_store=store,
            tool_context={},
        )

        self.assertTrue(detail["session"]["has_compacted_context"])
        self.assertEqual(detail["session"]["compacted_prefix_end"], 4)
        self.assertEqual(detail["session"]["preserved_tail_user_turns"], 3)
        self.assertEqual(detail["session"]["compacted_at"], compacted.created_at.isoformat())
        self.assertNotIn("checkpoint_trigger_kind", detail["session"])

    def test_session_tool_show_defaults_to_current_session_when_payload_omits_session_id(
        self,
    ) -> None:
        store = SessionStore()
        record = store.create(
            session_id="sess_current_show",
            conversation_id="conv-current-show",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            record.session_id,
            user_id="demo",
            agent_id="main",
            session_title="当前会话",
            session_preview="当前绑定会话详情。",
        )

        detail = run_session_tool(
            {"action": "show"},
            session_store=store,
            tool_context={"user_id": "demo", "session_id": record.session_id},
        )

        self.assertEqual(detail["action"], "show")
        self.assertEqual(detail["session"]["session_id"], record.session_id)
        self.assertEqual(detail["session"]["session_title"], "当前会话")

    def test_session_tool_new_rebinds_current_conversation_to_fresh_session(self) -> None:
        store = SessionStore()
        current = store.create(
            session_id="sess_current",
            conversation_id="conv-1",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )

        result = run_session_tool(
            {"action": "new"},
            session_store=store,
            tool_context={
                "channel_id": "http",
                "conversation_id": "conv-1",
                "session_id": current.session_id,
            },
        )

        self.assertEqual(result["action"], "new")
        self.assertNotEqual(result["session"]["session_id"], current.session_id)
        rebound = store.resolve_session_for_conversation(
            channel_id="http",
            conversation_id="conv-1",
        )
        self.assertEqual(rebound, result["session"]["session_id"])

    def test_session_tool_new_keeps_new_session_visible_to_current_user(self) -> None:
        store = SessionStore()
        current = store.create(
            session_id="sess_current",
            conversation_id="conv-1",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            current.session_id,
            user_id="user-a",
            agent_id="main",
            session_title="current",
            session_preview="current preview",
        )

        result = run_session_tool(
            {"action": "new"},
            session_store=store,
            tool_context={
                "channel_id": "http",
                "conversation_id": "conv-1",
                "session_id": current.session_id,
                "user_id": "user-a",
            },
        )

        new_session_id = result["session"]["session_id"]
        detail = run_session_tool(
            {"action": "show", "session_id": new_session_id},
            session_store=store,
            tool_context={"user_id": "user-a"},
        )
        listed = run_session_tool(
            {"action": "list"},
            session_store=store,
            tool_context={"user_id": "user-a"},
        )

        self.assertEqual(result["session"]["user_id"], "user-a")
        self.assertEqual(detail["session"]["session_id"], new_session_id)
        self.assertEqual(detail["session"]["user_id"], "user-a")
        self.assertEqual(listed["count"], 2)
        self.assertEqual(listed["items"][0]["session_id"], new_session_id)

    def test_session_tool_new_preserves_current_active_agent_on_new_session(self) -> None:
        store = SessionStore()
        current = store.create(
            session_id="sess_current",
            conversation_id="conv-1",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            current.session_id,
            user_id="user-a",
            agent_id="coding",
            session_title="current",
            session_preview="current preview",
        )
        store.set_active_agent(current.session_id, "coding")

        result = run_session_tool(
            {"action": "new"},
            session_store=store,
            tool_context={
                "channel_id": "http",
                "conversation_id": "conv-1",
                "session_id": current.session_id,
                "user_id": "user-a",
            },
        )

        created = store.get(result["session"]["session_id"])
        self.assertEqual(created.active_agent_id, "coding")
        self.assertEqual(created.agent_id, "coding")
        self.assertEqual(result["session"]["agent_id"], "coding")

    def test_session_tool_new_returns_deferred_compaction_job_metadata(self) -> None:
        store = _QueueingStore()
        current = store.create(
            session_id="sess_current",
            conversation_id="conv-1",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            current.session_id,
            user_id="user-a",
            agent_id="coding",
            session_title="current",
            session_preview="current preview",
        )
        store.set_active_agent(current.session_id, "coding")
        store.append_message(current.session_id, SessionMessage.user("历史 1"))
        store.append_message(current.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(current.session_id, SessionMessage.user("历史 2"))
        store.append_message(current.session_id, SessionMessage.assistant("历史 2 完成"))
        store.append_message(current.session_id, SessionMessage.user("切到新会话"))

        result = run_session_tool(
            {"action": "new"},
            session_store=store,
            tool_context={
                "channel_id": "http",
                "conversation_id": "conv-1",
                "session_id": current.session_id,
                "user_id": "user-a",
                "message": "切到新会话",
                "llm_client": None,
                "session_replay_user_turns": 1,
            },
        )

        self.assertNotEqual(result["session"]["session_id"], current.session_id)
        self.assertEqual(result["transition"]["compaction_reason"], "deferred")
        self.assertFalse(result["transition"]["compaction_succeeded"])
        self.assertEqual(result["transition"]["compaction_job"]["enqueue_status"], "queued")
        self.assertEqual(result["transition"]["compaction_job"]["current_message"], "切到新会话")
        self.assertEqual(
            result["transition"]["compaction_job"]["snapshot_message_count"],
            len(store.get(current.session_id).history),
        )
        self.assertEqual(len(store.enqueued_jobs), 1)

    def test_session_tool_resume_returns_enqueue_failure_metadata_without_blocking_switch(self) -> None:
        store = _QueueingStore()
        current = store.create(
            session_id="sess_current",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        target = store.create(
            session_id="sess_target",
            conversation_id="conv-target",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            current.session_id,
            user_id="user-a",
            agent_id="main",
            session_title="current",
            session_preview="current preview",
        )
        store.set_catalog_metadata(
            target.session_id,
            user_id="user-a",
            agent_id="main",
            session_title="target",
            session_preview="target preview",
        )
        store.append_message(current.session_id, SessionMessage.user("历史 1"))
        store.append_message(current.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(current.session_id, SessionMessage.user("历史 2"))
        store.append_message(current.session_id, SessionMessage.assistant("历史 2 完成"))
        store.append_message(current.session_id, SessionMessage.user("恢复旧会话"))
        store.fail_enqueue = True

        result = run_session_tool(
            {"action": "resume", "session_id": target.session_id},
            session_store=store,
            tool_context={
                "channel_id": "http",
                "conversation_id": "conv-current",
                "session_id": current.session_id,
                "user_id": "user-a",
                "message": "恢复旧会话",
                "llm_client": None,
                "session_replay_user_turns": 1,
            },
        )

        self.assertEqual(result["session"]["session_id"], target.session_id)
        self.assertEqual(result["transition"]["compaction_reason"], "enqueue_failed")
        self.assertEqual(result["transition"]["compaction_job"]["enqueue_status"], "failed")
        self.assertEqual(
            store.resolve_session_for_conversation(
                channel_id="http",
                conversation_id="conv-current",
                user_id="user-a",
            ),
            target.session_id,
        )

    def test_session_tool_new_keeps_new_session_visible_to_current_user_with_sqlite_store(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSessionStore(Path(tmpdir) / "sessions.sqlite3")
            current = store.create(
                session_id="sess_current",
                conversation_id="conv-1",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
                channel_id="http",
            )
            store.set_catalog_metadata(
                current.session_id,
                user_id="user-a",
                agent_id="main",
                session_title="current",
                session_preview="current preview",
            )

            result = run_session_tool(
                {"action": "new"},
                session_store=store,
                tool_context={
                    "channel_id": "http",
                    "conversation_id": "conv-1",
                    "session_id": current.session_id,
                    "user_id": "user-a",
                },
            )
            new_session_id = result["session"]["session_id"]
            detail = run_session_tool(
                {"action": "show", "session_id": new_session_id},
                session_store=store,
                tool_context={"user_id": "user-a"},
            )
            listed = run_session_tool(
                {"action": "list"},
                session_store=store,
                tool_context={"user_id": "user-a"},
            )

        self.assertEqual(result["session"]["user_id"], "user-a")
        self.assertEqual(detail["session"]["session_id"], new_session_id)
        self.assertEqual(listed["items"][0]["session_id"], new_session_id)

    def test_session_tool_list_only_returns_sessions_for_current_user(self) -> None:
        store = SessionStore()
        own = store.create(
            session_id="sess_own",
            conversation_id="conv-own",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        other = store.create(
            session_id="sess_other",
            conversation_id="conv-other",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            own.session_id,
            user_id="user-a",
            agent_id="main",
            session_title="own",
            session_preview="own preview",
        )
        store.set_catalog_metadata(
            other.session_id,
            user_id="user-b",
            agent_id="main",
            session_title="other",
            session_preview="other preview",
        )

        listed = run_session_tool(
            {"action": "list"},
            session_store=store,
            tool_context={"user_id": "user-a"},
        )

        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["session_id"], own.session_id)

    def test_session_tool_show_rejects_session_from_other_user(self) -> None:
        store = SessionStore()
        target = store.create(
            session_id="sess_target",
            conversation_id="conv-target",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            target.session_id,
            user_id="user-b",
            agent_id="main",
            session_title="other",
            session_preview="other preview",
        )

        with self.assertRaisesRegex(ValueError, "not visible"):
            run_session_tool(
                {"action": "show", "session_id": target.session_id},
                session_store=store,
                tool_context={"user_id": "user-a"},
            )

    def test_session_tool_without_stable_user_id_only_sees_anonymous_sessions(self) -> None:
        store = SessionStore()
        anonymous = store.create(
            session_id="sess_anon",
            conversation_id="conv-anon",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        user_bound = store.create(
            session_id="sess_user",
            conversation_id="conv-user",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            user_bound.session_id,
            user_id="user-a",
            agent_id="main",
            session_title="user session",
            session_preview="user preview",
        )

        listed = run_session_tool(
            {"action": "list"},
            session_store=store,
            tool_context={},
        )

        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["session_id"], anonymous.session_id)

    def test_session_tool_resume_rebinds_current_conversation_to_existing_session(self) -> None:
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
            conversation_id="conv-target",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )

        result = run_session_tool(
            {"action": "resume", "session_id": target.session_id},
            session_store=store,
            tool_context={
                "channel_id": "http",
                "conversation_id": "conv-current",
                "session_id": current.session_id,
            },
        )

        self.assertEqual(result["action"], "resume")
        self.assertEqual(result["session"]["session_id"], target.session_id)
        self.assertEqual(result["session"]["conversation_id"], "conv-current")
        self.assertEqual(result["session"]["channel_id"], "http")
        rebound = store.resolve_session_for_conversation(
            channel_id="http",
            conversation_id="conv-current",
        )
        self.assertEqual(rebound, target.session_id)
        self.assertIsNone(
            store.resolve_session_for_conversation(
                channel_id="http",
                conversation_id="conv-target",
            )
        )

    def test_session_tool_resume_rejects_session_from_other_user(self) -> None:
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
            conversation_id="conv-target",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            current.session_id,
            user_id="user-a",
            agent_id="main",
            session_title="current",
            session_preview="current preview",
        )
        store.set_catalog_metadata(
            target.session_id,
            user_id="user-b",
            agent_id="main",
            session_title="target",
            session_preview="target preview",
        )

        with self.assertRaisesRegex(ValueError, "not visible"):
            run_session_tool(
                {"action": "resume", "session_id": target.session_id},
                session_store=store,
                tool_context={
                    "channel_id": "http",
                    "conversation_id": "conv-current",
                    "session_id": current.session_id,
                    "user_id": "user-a",
                },
            )

    def test_session_tool_resume_same_session_marks_noop_transition(self) -> None:
        store = SessionStore()
        current = store.create(
            session_id="sess_current",
            conversation_id="conv-current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            current.session_id,
            user_id="user-a",
            agent_id="main",
            session_title="current",
            session_preview="current preview",
        )

        result = run_session_tool(
            {"action": "resume", "session_id": current.session_id},
            session_store=store,
            tool_context={
                "channel_id": "http",
                "conversation_id": "conv-current",
                "session_id": current.session_id,
                "user_id": "user-a",
            },
        )

        self.assertEqual(result["action"], "resume")
        self.assertEqual(result["session"]["session_id"], current.session_id)
        self.assertEqual(result["transition"]["mode"], "noop_same_session")
        self.assertFalse(result["transition"]["binding_changed"])
        self.assertIsNone(result["transition"]["compaction_job"])

    def test_session_tool_resume_keeps_switch_success_when_compaction_is_deferred(self) -> None:
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
            conversation_id="conv-target",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
            channel_id="http",
        )
        store.set_catalog_metadata(
            current.session_id,
            user_id="user-a",
            agent_id="main",
            session_title="current",
            session_preview="current preview",
        )
        store.set_catalog_metadata(
            target.session_id,
            user_id="user-a",
            agent_id="main",
            session_title="target",
            session_preview="target preview",
        )
        store.set_compacted_context(
            current.session_id,
            CompactedContext(
                compact_id="cmp_old",
                session_id=current.session_id,
                summary_text="旧摘要",
                source_message_range=[0, 2],
                preserved_tail_user_turns=1,
            ),
        )
        store.append_message(current.session_id, SessionMessage.user("历史 1"))
        store.append_message(current.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(current.session_id, SessionMessage.user("历史 2"))
        store.append_message(current.session_id, SessionMessage.assistant("历史 2 完成"))
        store.append_message(current.session_id, SessionMessage.user("恢复旧会话"))

        result = run_session_tool(
            {"action": "resume", "session_id": target.session_id},
            session_store=store,
            tool_context={
                "channel_id": "http",
                "conversation_id": "conv-current",
                "session_id": current.session_id,
                "user_id": "user-a",
                "message": "恢复旧会话",
                "llm_client": _FailingLLM(),
                "session_replay_user_turns": 1,
            },
        )

        self.assertEqual(result["action"], "resume")
        self.assertEqual(result["session"]["session_id"], target.session_id)
        self.assertEqual(result["transition"]["compaction_reason"], "deferred")
        self.assertEqual(result["transition"]["compaction_job"]["enqueue_status"], "queued")
        self.assertEqual(store.get(current.session_id).latest_compacted_context.summary_text, "旧摘要")


if __name__ == "__main__":
    unittest.main()
