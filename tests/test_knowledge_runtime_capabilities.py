import unittest
from unittest.mock import Mock

from marten_runtime.runtime.capabilities import get_capability_declarations, render_capability_catalog, render_tool_description
from marten_runtime.tools.builtins.knowledge_tool import run_knowledge_tool
from marten_runtime.tools.registry import ToolRegistry


class KnowledgeCapabilityTests(unittest.TestCase):
    def test_knowledge_capability_is_declared_for_llm_tool_choice(self) -> None:
        declarations = get_capability_declarations()

        self.assertIn("knowledge", declarations)
        description = render_tool_description(declarations["knowledge"])
        self.assertIn("ingest_text", description)
        self.assertIn("reindex", description)
        self.assertIn("model_status", description)
        self.assertIn("unload_models", description)
        self.assertIn("namespace", description)
        self.assertIn("LLM", description)
        schema = declarations["knowledge"].parameters_schema
        self.assertIn("action", schema["properties"])
        self.assertIn("search", schema["properties"]["action"]["enum"])
        self.assertIn("model_status", schema["properties"]["action"]["enum"])
        self.assertIn("unload_models", schema["properties"]["action"]["enum"])
        self.assertEqual(schema["properties"]["top_k"]["minimum"], 1)

    def test_tool_snapshot_respects_allowed_tools_for_knowledge(self) -> None:
        registry = ToolRegistry()
        registry.register("knowledge", lambda payload: payload)
        registry.register("time", lambda payload: payload)

        snapshot = registry.build_snapshot(["time"])
        self.assertNotIn("knowledge", snapshot.builtin_tools)

        snapshot = registry.build_snapshot(["knowledge"])
        self.assertIn("knowledge", snapshot.builtin_tools)

    def test_knowledge_tool_enforces_action_scope_before_service_call(self) -> None:
        service = Mock()

        result = run_knowledge_tool(
            {"action": "ingest_text", "namespace": "bazi-theory", "source": {"text": "x"}},
            knowledge_service=service,
            tool_context={
                "allowed_knowledge_actions": ["search", "get_chunk", "model_status"],
                "allowed_knowledge_namespaces": ["bazi-theory", "bazi-cases"],
            },
        )

        self.assertEqual(result["error_code"], "KNOWLEDGE_ACTION_FORBIDDEN")
        self.assertFalse(result["ok"])
        service.assert_not_called()

    def test_knowledge_tool_enforces_namespace_scope(self) -> None:
        service = Mock()

        result = run_knowledge_tool(
            {"action": "search", "namespace": "personal", "query": "甲木"},
            knowledge_service=service,
            tool_context={
                "allowed_knowledge_actions": ["search"],
                "allowed_knowledge_namespaces": ["bazi-theory"],
            },
        )

        self.assertEqual(result["error_code"], "KNOWLEDGE_NAMESPACE_FORBIDDEN")
        service.assert_not_called()

    def test_no_namespace_read_action_uses_only_action_scope(self) -> None:
        service = Mock()
        service.model_status.return_value = {"ok": True, "action": "model_status"}

        result = run_knowledge_tool(
            {"action": "model_status"},
            knowledge_service=service,
            tool_context={
                "allowed_knowledge_actions": ["model_status"],
                "allowed_knowledge_namespaces": [],
            },
        )

        self.assertTrue(result["ok"])
        service.model_status.assert_called_once_with()

    def test_none_scope_preserves_family_level_compatibility(self) -> None:
        service = Mock()
        service.search.return_value = {"ok": True, "results": []}

        result = run_knowledge_tool(
            {"action": "search", "namespace": "legacy", "query": "x"},
            knowledge_service=service,
            tool_context={
                "allowed_knowledge_actions": None,
                "allowed_knowledge_namespaces": None,
            },
        )

        self.assertTrue(result["ok"])
        service.search.assert_called_once()

    def test_bazi_search_success_directs_immediate_cited_finalization(self) -> None:
        service = Mock()
        service.search.return_value = {
            "ok": True,
            "results": [
                {
                    "text": "reviewed theory",
                    "source_id": "source-1",
                    "chunk_id": "chunk-1",
                }
            ],
        }

        result = run_knowledge_tool(
            {"action": "search", "namespace": "bazi-theory", "query": "丁火 巳月"},
            knowledge_service=service,
            tool_context={"agent_id": "bazi"},
        )

        self.assertIn("generate the final response now", result["runtime_guidance"])
        self.assertIn("Do not call get_chunk", result["runtime_guidance"])


if __name__ == "__main__":
    unittest.main()
