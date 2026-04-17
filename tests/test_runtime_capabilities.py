import unittest

from marten_runtime.runtime.capabilities import (
    CapabilityDeclaration,
    get_capability_declarations,
    get_parameters_schema,
    render_capability_catalog,
    render_tool_description,
)


class RuntimeCapabilitiesTests(unittest.TestCase):
    def test_capability_declarations_cover_runtime_visible_tool_families(self) -> None:
        declarations = get_capability_declarations()

        self.assertEqual(
            set(declarations.keys()),
            {
                "automation",
                "mcp",
                "runtime",
                "self_improve",
                "skill",
                "time",
                "spawn_subagent",
                "cancel_subagent",
            },
        )
        self.assertTrue(all(isinstance(item, CapabilityDeclaration) for item in declarations.values()))

    def test_capability_declarations_render_catalog_and_descriptions_from_same_source(self) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations)
        automation_description = render_tool_description(declarations["automation"])
        mcp_description = render_tool_description(declarations["mcp"])
        runtime_description = render_tool_description(declarations["runtime"])

        self.assertIn("Capability catalog:", catalog)
        self.assertIn("- automation:", catalog)
        self.assertIn("- runtime:", catalog)
        self.assertTrue(automation_description)
        self.assertTrue(mcp_description)
        self.assertTrue(runtime_description)
        self.assertIn("Actions:", automation_description)
        self.assertIn("automation", automation_description.lower())
        self.assertIn("github", mcp_description.lower())
        self.assertIn("exact server_id", mcp_description)
        self.assertIn("exact tool_name", mcp_description)
        self.assertTrue(
            "runtime" in runtime_description.lower() or "上下文" in runtime_description
        )

    def test_runtime_capability_description_requires_tool_for_natural_language_context_queries(self) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations) or ""
        runtime_description = render_tool_description(declarations["runtime"])

        self.assertIn("current context window usage", catalog)
        self.assertIn("live runtime context data", runtime_description)
        self.assertIn("current session", runtime_description)
        self.assertNotIn("先调用 `runtime`", catalog)
        self.assertNotIn("不要直接根据记忆回答", catalog)
        self.assertTrue(
            "context_status" in runtime_description or "上下文" in runtime_description
        )
        self.assertNotIn("先调用 `runtime`", runtime_description)
        self.assertNotIn("不要直接根据记忆回答", runtime_description)

    def test_time_capability_description_requires_tool_for_natural_language_current_time_queries(self) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations) or ""
        time_description = render_tool_description(declarations["time"])

        self.assertIn("现在几点", catalog)
        self.assertIn("live clock data", time_description)
        self.assertIn("timezone", time_description)
        self.assertNotIn("不要直接猜", catalog)
        self.assertNotIn("先调用 `time`", catalog)
        self.assertNotIn("不要直接猜", time_description)
        self.assertNotIn("先调用", time_description)

    def test_mcp_capability_description_stays_declarative_for_github_queries(self) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations) or ""
        mcp_description = render_tool_description(declarations["mcp"])

        self.assertIn("GitHub repository questions", catalog)
        self.assertIn("github", mcp_description.lower())
        self.assertIn("exact server_id", mcp_description)
        self.assertIn("exact tool_name", mcp_description)
        self.assertIn("arguments", mcp_description)
        self.assertIn("do not invent aliases", mcp_description.lower())
        self.assertNotIn("progressive inspection", mcp_description.lower())
        self.assertNotIn("before one concrete call", mcp_description.lower())
        self.assertNotIn("search_repositories", mcp_description)
        self.assertNotIn("repo:owner/name", mcp_description)
        self.assertNotIn("list_commits", mcp_description)
        self.assertNotIn("不要先调用", mcp_description)
        self.assertNotIn("不要拿仓库 metadata 冒充 commit 信息", mcp_description)

    def test_capability_declarations_expose_expected_structured_fields(self) -> None:
        declarations = get_capability_declarations()

        self.assertIsInstance(declarations["mcp"], CapabilityDeclaration)
        self.assertEqual(
            set(CapabilityDeclaration.model_fields),
            {
                "name",
                "summary",
                "actions",
                "usage_rules",
                "parameters_schema",
            },
        )
        for declaration in declarations.values():
            self.assertIsInstance(get_parameters_schema(declaration), dict)
            self.assertTrue(render_tool_description(declaration))


if __name__ == "__main__":
    unittest.main()
