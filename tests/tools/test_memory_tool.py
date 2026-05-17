import unittest
from tempfile import TemporaryDirectory

from marten_runtime.memory.intent import (
    MEMORY_DELETE_INTENT,
    MEMORY_INTENT_FIELD,
    MEMORY_SOURCE_EXCERPT_FIELD,
    MEMORY_WRITE_INTENT,
)
from marten_runtime.memory.service import ThinMemoryService
from marten_runtime.tools.builtins.memory_tool import run_memory_tool


class MemoryToolTests(unittest.TestCase):
    def test_memory_tool_get_append_replace_delete_with_structured_intent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            appended = run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住：以后始终用中文回复",
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
                    "content": "Always answer in Chinese.",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "记住：以后始终用中文回复"},
            )
            replaced = run_memory_tool(
                {
                    "action": "replace",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "请把偏好改成以后回答尽量简洁",
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
                    "content": "Prefer concise answers.",
                },
                memory_service=service,
                tool_context={
                    "user_id": "demo",
                    "message": "请把偏好改成以后回答尽量简洁",
                },
            )
            fetched = run_memory_tool(
                {"action": "get"},
                memory_service=service,
                tool_context={"user_id": "demo"},
            )
            deleted = run_memory_tool(
                {
                    "action": "delete",
                    MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT,
                    "scope": "global",
                    MEMORY_SOURCE_EXCERPT_FIELD: "删除这个偏好",
                    "section": "preferences",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "删除这个偏好"},
            )

        self.assertTrue(appended["available"])
        self.assertIn("Always answer in Chinese.", appended["memory_text"])
        self.assertIn("Prefer concise answers.", replaced["memory_text"])
        self.assertIn("Prefer concise answers.", fetched["memory_text"])
        self.assertEqual(deleted["memory_text"], "")

    def test_memory_tool_accepts_scoped_structured_payload(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            result = run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住 main agent 约束：保持 thin harness 边界",
                    "scope": "agent",
                    "type": "constraint",
                    "section": "runtime",
                    "content": "保持 thin harness 边界",
                    "priority": 80,
                },
                memory_service=service,
                tool_context={"user_id": "demo", "agent_id": "main", "message": "记住 main agent 约束：保持 thin harness 边界", "run_id": "run-1"},
            )

        self.assertTrue(result["available"])
        self.assertIn("items", result)
        self.assertEqual(result["items"][0]["scope"], "agent")
        self.assertEqual(result["items"][0]["agent_id"], "main")
        self.assertEqual(result["items"][0]["source_run_id"], "run-1")
        self.assertIn("保持 thin harness 边界", result["memory_text"])


    def test_memory_tool_rendered_memory_uses_agent_scope_and_current_message(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            result = run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住 main agent 约束：保持 thin harness 边界",
                    "scope": "agent",
                    "type": "constraint",
                    "section": "runtime",
                    "content": "保持 thin harness 边界",
                },
                memory_service=service,
                tool_context={
                    "user_id": "demo",
                    "agent_id": "main",
                    "message": "记住 main agent 约束：保持 thin harness 边界",
                },
            )

        self.assertIn("保持 thin harness 边界", result["rendered_memory"] or "")

    def test_memory_tool_memory_id_mutation_cannot_cross_user_boundary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            alice = run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住 alice 偏好",
                    "scope": "global",
                    "type": "preference",
                    "section": "preferences",
                    "content": "alice 偏好",
                },
                memory_service=service,
                tool_context={"user_id": "alice", "message": "记住 alice 偏好"},
            )
            run_memory_tool(
                {
                    "action": "delete",
                    MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT,
                    "scope": "global",
                    MEMORY_SOURCE_EXCERPT_FIELD: "删除 alice 那条",
                    "memory_id": alice["items"][0]["memory_id"],
                    "section": "preferences",
                },
                memory_service=service,
                tool_context={"user_id": "bob", "message": "删除 alice 那条"},
            )
            alice_active = service.store.list_active("alice", scope="global", type="preference")

        self.assertEqual([item.content for item in alice_active], ["alice 偏好"])

    def test_memory_tool_requires_model_supplied_scope_and_type_for_writes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            with self.assertRaisesRegex(ValueError, "scope is required"):
                run_memory_tool(
                    {
                        "action": "append",
                        MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                        MEMORY_SOURCE_EXCERPT_FIELD: "记住：以后中文",
                        "section": "preferences",
                        "type": "preference",
                        "content": "以后中文",
                    },
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "记住：以后中文"},
                )
            with self.assertRaisesRegex(ValueError, "type is required"):
                run_memory_tool(
                    {
                        "action": "append",
                        MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                        MEMORY_SOURCE_EXCERPT_FIELD: "记住：以后中文",
                        "scope": "global",
                        "section": "preferences",
                        "content": "以后中文",
                    },
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "记住：以后中文"},
                )

    def test_memory_tool_requires_model_supplied_scope_for_delete(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            with self.assertRaisesRegex(ValueError, "scope is required"):
                run_memory_tool(
                    {
                        "action": "delete",
                        MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT,
                        MEMORY_SOURCE_EXCERPT_FIELD: "删除这条记忆",
                        "section": "preferences",
                    },
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "删除这条记忆"},
                )

    def test_memory_tool_delete_is_limited_to_explicit_scope(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住全局偏好",
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
                    "content": "同一内容",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "记住全局偏好"},
            )
            run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住 agent 偏好",
                    "scope": "agent",
                    "section": "preferences",
                    "type": "preference",
                    "content": "同一内容",
                },
                memory_service=service,
                tool_context={
                    "user_id": "demo",
                    "agent_id": "main",
                    "message": "记住 agent 偏好",
                },
            )

            deleted = run_memory_tool(
                {
                    "action": "delete",
                    MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT,
                    "scope": "global",
                    MEMORY_SOURCE_EXCERPT_FIELD: "删除全局偏好",
                    "section": "preferences",
                    "content": "同一内容",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "删除全局偏好"},
            )

        self.assertEqual(len(deleted["items"]), 1)
        self.assertEqual(deleted["items"][0]["scope"], "agent")
        self.assertEqual(deleted["items"][0]["agent_id"], "main")
        self.assertEqual(deleted["items"][0]["content"], "同一内容")

    def test_memory_tool_rejects_agent_scope_without_agent_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            with self.assertRaisesRegex(ValueError, "agent_id"):
                run_memory_tool(
                    {
                        "action": "append",
                        MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                        MEMORY_SOURCE_EXCERPT_FIELD: "记住 agent 约束",
                        "scope": "agent",
                        "type": "constraint",
                        "section": "runtime",
                        "content": "agent only",
                    },
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "记住 agent 约束"},
                )

    def test_memory_tool_deletes_by_memory_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            appended = run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住：以后中文",
                    "scope": "global",
                    "type": "preference",
                    "section": "preferences",
                    "content": "以后中文",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "记住：以后中文"},
            )
            memory_id = appended["items"][0]["memory_id"]
            deleted = run_memory_tool(
                {
                    "action": "delete",
                    MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT,
                    "scope": "global",
                    MEMORY_SOURCE_EXCERPT_FIELD: "删除刚才那条记忆",
                    "memory_id": memory_id,
                    "section": "preferences",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "删除刚才那条记忆"},
            )

        self.assertEqual(deleted["items"], [])
        self.assertEqual(deleted["memory_text"], "")

    def test_memory_tool_memory_id_delete_cannot_cross_scope_boundary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            appended = run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住 agent 偏好",
                    "scope": "agent",
                    "type": "preference",
                    "section": "preferences",
                    "content": "agent only",
                },
                memory_service=service,
                tool_context={
                    "user_id": "demo",
                    "agent_id": "main",
                    "message": "记住 agent 偏好",
                },
            )
            memory_id = appended["items"][0]["memory_id"]
            deleted = run_memory_tool(
                {
                    "action": "delete",
                    MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT,
                    "scope": "global",
                    MEMORY_SOURCE_EXCERPT_FIELD: "删除全局偏好",
                    "memory_id": memory_id,
                    "section": "preferences",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "删除全局偏好"},
            )

        self.assertEqual(len(deleted["items"]), 1)
        self.assertEqual(deleted["items"][0]["scope"], "agent")
        self.assertEqual(deleted["items"][0]["agent_id"], "main")
        self.assertEqual(deleted["items"][0]["content"], "agent only")

    def test_memory_tool_agent_scope_delete_uses_canonical_agent_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住 agent 偏好",
                    "scope": "agent",
                    "type": "preference",
                    "section": "preferences",
                    "content": "assistant alias preference",
                },
                memory_service=service,
                tool_context={
                    "user_id": "demo",
                    "agent_id": "assistant",
                    "message": "记住 agent 偏好",
                },
            )

            deleted = run_memory_tool(
                {
                    "action": "delete",
                    MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "删除 agent 偏好",
                    "scope": "agent",
                    "section": "preferences",
                    "content": "assistant alias preference",
                },
                memory_service=service,
                tool_context={
                    "user_id": "demo",
                    "agent_id": "assistant",
                    "message": "删除 agent 偏好",
                },
            )

        self.assertEqual(deleted["items"], [])

    def test_memory_tool_memory_id_replace_uses_canonical_agent_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            appended = run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住 agent 偏好",
                    "scope": "agent",
                    "type": "preference",
                    "section": "preferences",
                    "content": "old alias preference",
                },
                memory_service=service,
                tool_context={
                    "user_id": "demo",
                    "agent_id": "assistant",
                    "message": "记住 agent 偏好",
                },
            )
            memory_id = appended["items"][0]["memory_id"]

            replaced = run_memory_tool(
                {
                    "action": "replace",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "更新 agent 偏好",
                    "scope": "agent",
                    "type": "preference",
                    "memory_id": memory_id,
                    "section": "preferences",
                    "content": "new alias preference",
                },
                memory_service=service,
                tool_context={
                    "user_id": "demo",
                    "agent_id": "assistant",
                    "message": "更新 agent 偏好",
                },
            )

        self.assertEqual(len(replaced["items"]), 1)
        self.assertEqual(replaced["items"][0]["agent_id"], "main")
        self.assertEqual(replaced["items"][0]["content"], "new alias preference")

    def test_memory_tool_memory_id_replace_cannot_cross_scope_boundary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            appended = run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住 agent 偏好",
                    "scope": "agent",
                    "type": "preference",
                    "section": "preferences",
                    "content": "agent only",
                },
                memory_service=service,
                tool_context={
                    "user_id": "demo",
                    "agent_id": "main",
                    "message": "记住 agent 偏好",
                },
            )
            memory_id = appended["items"][0]["memory_id"]
            replaced = run_memory_tool(
                {
                    "action": "replace",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "更新全局偏好",
                    "scope": "global",
                    "type": "preference",
                    "memory_id": memory_id,
                    "section": "preferences",
                    "content": "global replacement",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "更新全局偏好"},
            )

        self.assertEqual(len(replaced["items"]), 2)
        self.assertEqual(
            sorted((item["scope"], item["agent_id"], item["content"]) for item in replaced["items"]),
            [("agent", "main", "agent only"), ("global", None, "global replacement")],
        )

    def test_memory_tool_rejects_write_without_structured_intent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            with self.assertRaisesRegex(ValueError, "explicit user memory intent"):
                run_memory_tool(
                    {
                        "action": "append",
                        "section": "preferences",
                        "content": "Always answer in Chinese.",
                    },
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "Remember this and save this to memory."},
                )

    def test_memory_tool_rejects_delete_without_structured_intent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            run_memory_tool(
                {
                    "action": "append",
                    MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                    MEMORY_SOURCE_EXCERPT_FIELD: "记住以后始终用中文回复",
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
                    "content": "Always answer in Chinese.",
                },
                memory_service=service,
                tool_context={"user_id": "demo", "message": "记住以后始终用中文回复"},
            )
            with self.assertRaisesRegex(ValueError, "explicit user memory intent"):
                run_memory_tool(
                    {"action": "delete", "section": "preferences"},
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "Delete this memory."},
                )

    def test_memory_tool_rejects_intent_action_mismatch(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            with self.assertRaisesRegex(ValueError, "explicit user memory intent"):
                run_memory_tool(
                    {
                        "action": "append",
                        MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT,
                        MEMORY_SOURCE_EXCERPT_FIELD: "记住以后始终用中文回复",
                        "scope": "global",
                        "section": "preferences",
                        "content": "Always answer in Chinese.",
                    },
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "记住以后始终用中文回复"},
                )
            with self.assertRaisesRegex(ValueError, "explicit user memory intent"):
                run_memory_tool(
                    {
                        "action": "delete",
                        MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                        MEMORY_SOURCE_EXCERPT_FIELD: "删除这条记忆",
                        "section": "preferences",
                    },
                    memory_service=service,
                    tool_context={"user_id": "demo", "message": "删除这条记忆"},
                )

    def test_memory_tool_rejects_mutation_without_matching_source_excerpt(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            with self.assertRaisesRegex(ValueError, "source_excerpt"):
                run_memory_tool(
                    {
                        "action": "append",
                        MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT,
                        MEMORY_SOURCE_EXCERPT_FIELD: "记住以后始终用英文回复",
                        "scope": "global",
                        "section": "preferences",
                        "content": "Always answer in English.",
                    },
                    memory_service=service,
                    tool_context={
                        "user_id": "demo",
                        "message": "记住以后始终用中文回复",
                    },
                )

    def test_memory_tool_degrades_cleanly_without_stable_user_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            service = ThinMemoryService(tmpdir)
            result = run_memory_tool(
                {"action": "get"},
                memory_service=service,
                tool_context={"user_id": ""},
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["available"])
        self.assertEqual(result["memory_text"], "")


if __name__ == "__main__":
    unittest.main()
