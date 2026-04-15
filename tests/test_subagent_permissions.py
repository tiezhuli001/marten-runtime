import unittest

from marten_runtime.tools.registry import ToolRegistry


class SubagentPermissionProfileTests(unittest.TestCase):
    def _build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register("automation", lambda payload: {"ok": True})
        registry.register("mcp", lambda payload: {"ok": True})
        registry.register("runtime", lambda payload: {"ok": True})
        registry.register("skill", lambda payload: {"ok": True})
        registry.register("time", lambda payload: {"ok": True})
        registry.register("spawn_subagent", lambda payload: {"ok": True})
        registry.register(
            "dangerous_mcp_tool",
            lambda payload: {"ok": True},
            source_kind="mcp",
            server_id="danger",
            backend_id="dangerous_mcp_tool",
        )
        return registry

    def test_restricted_profile_excludes_high_risk_tools_and_recursive_spawn(self) -> None:
        try:
            from marten_runtime.subagents.tool_profiles import resolve_child_allowed_tools
        except ModuleNotFoundError as exc:
            self.fail(f"subagent tool profile module missing: {exc}")

        allowed = resolve_child_allowed_tools(
            requested_profile="restricted",
            parent_allowed_tools=["automation", "runtime", "skill", "time", "spawn_subagent", "mcp:*"],
        )
        snapshot = self._build_registry().build_snapshot(allowed)

        self.assertIn("runtime", snapshot.available_tools())
        self.assertIn("skill", snapshot.available_tools())
        self.assertIn("time", snapshot.available_tools())
        self.assertNotIn("spawn_subagent", snapshot.available_tools())
        self.assertNotIn("dangerous_mcp_tool", snapshot.available_tools())

    def test_requested_profile_cannot_exceed_parent_ceiling(self) -> None:
        try:
            from marten_runtime.subagents.tool_profiles import resolve_child_allowed_tools
        except ModuleNotFoundError as exc:
            self.fail(f"subagent tool profile module missing: {exc}")

        allowed = resolve_child_allowed_tools(
            requested_profile="elevated",
            parent_allowed_tools=["runtime", "skill", "time"],
        )

        self.assertEqual(sorted(allowed), ["runtime", "skill", "time"])

    def test_standard_profile_ceiling_accepts_mcp_selector_authorization(self) -> None:
        from marten_runtime.subagents.tool_profiles import (
            resolve_child_allowed_tools,
            resolve_effective_tool_profile,
        )

        effective = resolve_effective_tool_profile(
            requested_profile="standard",
            parent_allowed_tools=["automation", "runtime", "skill", "time", "mcp:*"],
        )
        allowed = resolve_child_allowed_tools(
            requested_profile="standard",
            parent_allowed_tools=["automation", "runtime", "skill", "time", "mcp:*"],
        )

        self.assertEqual(effective, "standard")
        self.assertIn("mcp", allowed)

    def test_standard_profile_ceiling_accepts_builtin_star_authorization(self) -> None:
        from marten_runtime.subagents.tool_profiles import (
            resolve_child_allowed_tools,
            resolve_effective_tool_profile,
        )

        effective = resolve_effective_tool_profile(
            requested_profile="standard",
            parent_allowed_tools=["builtin:*"],
        )
        allowed = resolve_child_allowed_tools(
            requested_profile="standard",
            parent_allowed_tools=["builtin:*"],
        )

        self.assertEqual(effective, "standard")
        self.assertEqual(
            sorted(allowed),
            ["automation", "mcp", "runtime", "skill", "time"],
        )

    def test_profile_resolution_compiles_to_existing_allowed_tool_selectors(self) -> None:
        try:
            from marten_runtime.subagents.tool_profiles import resolve_child_allowed_tools
        except ModuleNotFoundError as exc:
            self.fail(f"subagent tool profile module missing: {exc}")

        allowed = resolve_child_allowed_tools(
            requested_profile="standard",
            parent_allowed_tools=["automation", "runtime", "skill", "time", "mcp"],
        )

        self.assertTrue(all(isinstance(item, str) for item in allowed))
        snapshot = self._build_registry().build_snapshot(allowed)
        self.assertIn("automation", snapshot.available_tools())
        self.assertIn("mcp", snapshot.available_tools())
        self.assertIn("runtime", snapshot.available_tools())
        self.assertIn("skill", snapshot.available_tools())


if __name__ == "__main__":
    unittest.main()
