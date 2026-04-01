import inspect
import unittest

from marten_runtime.runtime.capabilities import (
    CapabilityDeclaration,
    get_capability_declarations,
    render_capability_catalog,
    render_tool_description,
)


class RuntimeCapabilitiesTests(unittest.TestCase):
    def test_capability_declarations_cover_runtime_visible_tool_families(self) -> None:
        declarations = get_capability_declarations()

        self.assertEqual(
            list(declarations.keys()),
            ["automation", "mcp", "self_improve", "skill", "time"],
        )
        self.assertTrue(all(isinstance(item, CapabilityDeclaration) for item in declarations.values()))

    def test_capability_declarations_render_catalog_and_descriptions_from_same_source(self) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations)

        self.assertIn("Capability catalog:", catalog)
        self.assertIn("- automation:", catalog)
        self.assertIn(
            "action=register/list/detail/update/delete/pause/resume",
            render_tool_description(declarations["automation"]),
        )
        self.assertIn(
            "Inspect available MCP servers and tools",
            render_tool_description(declarations["mcp"]),
        )

    def test_time_capability_description_requires_tool_for_natural_language_current_time_queries(self) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations) or ""
        time_description = render_tool_description(declarations["time"])

        self.assertIn("现在几点", catalog)
        self.assertIn("不要直接猜", catalog)
        self.assertIn("先调用 `time`", catalog)
        self.assertIn("不要直接猜", time_description)
        self.assertIn("先调用", time_description)

    def test_capability_declarations_stay_data_only(self) -> None:
        declarations = get_capability_declarations()
        source = inspect.getsource(inspect.getmodule(CapabilityDeclaration))

        self.assertIsInstance(declarations["mcp"], CapabilityDeclaration)
        self.assertNotIn("router", source)
        self.assertNotIn("session", source)
        self.assertNotIn("channel", source)
        self.assertNotIn("ToolRegistry", source)
        self.assertNotIn("tool_description", CapabilityDeclaration.model_fields)


if __name__ == "__main__":
    unittest.main()
