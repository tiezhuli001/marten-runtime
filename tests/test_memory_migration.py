import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from marten_runtime.memory.sqlite_store import SQLiteMemoryStore
from scripts.migrate_memory_md_to_sqlite import migrate_memory_root


class MemoryMigrationTests(unittest.TestCase):
    def test_migrates_memory_md_to_sqlite_and_regenerates_export(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "memory"
            user_dir = root / "users" / quote("demo", safe="-_.~")
            user_dir.mkdir(parents=True)
            (user_dir / "MEMORY.md").write_text(
                "# MEMORY\n\n## preferences\n- 回答默认使用中文。\n\n## facts\n- 喜欢番茄炒蛋。\n",
                encoding="utf-8",
            )
            db_path = root / "memory.sqlite3"

            summary = migrate_memory_root(memory_root=root, db_path=db_path, dry_run=False)
            store = SQLiteMemoryStore(db_path)
            items = store.list_active("demo")
            exported = (user_dir / "MEMORY.md").read_text(encoding="utf-8")

        self.assertEqual(summary["user_count"], 1)
        self.assertEqual(summary["item_count"], 2)
        self.assertEqual(sorted(item.type for item in items), ["fact", "preference"])
        self.assertIn("## global / preferences", exported)
        self.assertIn("回答默认使用中文。", exported)

    def test_dry_run_does_not_create_database(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "memory"
            user_dir = root / "users" / "demo"
            user_dir.mkdir(parents=True)
            (user_dir / "MEMORY.md").write_text("# MEMORY\n\n## facts\n- fact\n", encoding="utf-8")
            db_path = root / "memory.sqlite3"

            summary = migrate_memory_root(memory_root=root, db_path=db_path, dry_run=True)

        self.assertEqual(summary["item_count"], 1)
        self.assertFalse(db_path.exists())

    def test_legacy_app_id_main_agent_maps_to_agent_main(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "memory"
            root.mkdir(parents=True)
            legacy = root / "legacy_memory.jsonl"
            legacy.write_text(
                json.dumps({
                    "user_id": "demo",
                    "app_id": "main_agent",
                    "type": "constraint",
                    "section": "runtime",
                    "content": "保持 thin harness 边界。",
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            db_path = root / "memory.sqlite3"

            migrate_memory_root(memory_root=root, db_path=db_path, dry_run=False)
            items = SQLiteMemoryStore(db_path).list_active("demo", scope="agent", agent_id="main")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].content, "保持 thin harness 边界。")

    def test_import_edited_markdown_supersedes_represented_sections(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "memory"
            user_dir = root / "users" / "demo"
            user_dir.mkdir(parents=True)
            db_path = root / "memory.sqlite3"
            store = SQLiteMemoryStore(db_path)
            store.append_item = None
            store.append(__import__("marten_runtime.memory.models", fromlist=["MemoryItem"]).MemoryItem.new(
                user_id="demo", scope="global", type="preference", section="preferences", content="旧偏好。"
            ))
            (user_dir / "MEMORY.md").write_text("# MEMORY\n\n## global / preferences\n- 新偏好。\n", encoding="utf-8")

            migrate_memory_root(memory_root=root, db_path=db_path, dry_run=False, import_edited_markdown=True)
            reopened = SQLiteMemoryStore(db_path)
            active = reopened.list_active("demo", scope="global", type="preference")
            with reopened._connect() as conn:  # type: ignore[attr-defined]
                rows = conn.execute("SELECT content, status FROM memory_items").fetchall()

        self.assertEqual([item.content for item in active], ["新偏好。"])
        statuses_by_content = {str(row["content"]): str(row["status"]) for row in rows}
        self.assertEqual(statuses_by_content["旧偏好。"], "superseded")
        self.assertEqual(statuses_by_content["新偏好。"], "active")


if __name__ == "__main__":
    unittest.main()
