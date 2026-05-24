import unittest

from marten_runtime.runtime.capabilities import get_capability_declarations, render_capability_catalog, render_tool_description
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


if __name__ == "__main__":
    unittest.main()
