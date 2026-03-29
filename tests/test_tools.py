import unittest

from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.registry import ToolRegistry


class ToolTests(unittest.TestCase):
    def test_registry_lists_and_calls_time_tool(self) -> None:
        registry = ToolRegistry()
        registry.register("time", run_time_tool)

        result = registry.call("time", {"timezone": "UTC"})

        self.assertEqual(registry.list(), ["time"])
        self.assertEqual(result["timezone"], "UTC")
        self.assertIn("iso_time", result)


if __name__ == "__main__":
    unittest.main()
