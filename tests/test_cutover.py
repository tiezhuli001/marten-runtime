import unittest
from pathlib import Path


class CutoverTests(unittest.TestCase):
    def test_cutover_and_rollback_docs_exist_with_required_sections(self) -> None:
        cutover = Path("migration/cutover-checklist.md").read_text(encoding="utf-8")
        rollback = Path("migration/rollback-playbook.md").read_text(encoding="utf-8")

        self.assertIn("Feishu inbound reachable", cutover)
        self.assertIn("rollback owner", cutover)
        self.assertIn("Trigger", rollback)
        self.assertIn("Verification", rollback)


if __name__ == "__main__":
    unittest.main()
