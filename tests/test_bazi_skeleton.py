from __future__ import annotations

import json
import unittest
from pathlib import Path

from marten_runtime.runtime.capabilities import get_capability_declarations


class BaziSkeletonTests(unittest.TestCase):
    def test_shared_fixture_categories_are_versioned(self) -> None:
        fixtures_root = Path(__file__).parent / "fixtures" / "bazi"

        for kind in ("clock", "true_solar", "resolve_pillars", "protocol_errors"):
            manifest = json.loads(
                (fixtures_root / kind / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["schemaVersion"], "bazi.fixture.v1")
            self.assertEqual(manifest["kind"], kind)
            self.assertIsInstance(manifest["cases"], list)

    def test_bazi_capability_is_available_for_runtime_registration(self) -> None:
        self.assertIn("bazi", get_capability_declarations())

    def test_bridge_manager_exists_before_builtin_registration(self) -> None:
        source_root = Path(__file__).parents[1] / "src" / "marten_runtime"

        self.assertTrue((source_root / "runtime" / "bazi_bridge.py").is_file())
        self.assertTrue((source_root / "tools" / "builtins" / "bazi_tool.py").is_file())


if __name__ == "__main__":
    unittest.main()
