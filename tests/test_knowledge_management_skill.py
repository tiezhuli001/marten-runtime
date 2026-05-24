import unittest
from pathlib import Path


class KnowledgeManagementSkillTests(unittest.TestCase):
    def test_skill_documents_chat_workflow_rules(self) -> None:
        path = Path("skills/knowledge_management/SKILL.md")
        text = path.read_text(encoding="utf-8")

        self.assertIn("knowledge", text)
        self.assertIn("namespace", text)
        self.assertIn("ingest_file", text)
        self.assertIn("ingest_status", text)
        self.assertIn("引用", text)
        self.assertIn("delete_source", text)
        self.assertIn("reindex", text)
        self.assertIn("确认", text)


if __name__ == "__main__":
    unittest.main()
