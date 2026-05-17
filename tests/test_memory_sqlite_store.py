import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.memory.models import MemoryItem
from marten_runtime.memory.sqlite_store import SQLiteMemoryStore


class SQLiteMemoryStoreTests(unittest.TestCase):
    def test_append_get_and_list_active_global_memory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            item = MemoryItem.new(
                user_id="demo",
                scope="global",
                type="preference",
                section="output_style",
                content="回答默认使用中文。",
                priority=70,
            )
            saved = store.append(item)

            loaded = store.get(saved.memory_id)
            active = store.list_active("demo", scope="global")

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.content, "回答默认使用中文。")
        self.assertEqual([x.memory_id for x in active], [saved.memory_id])

    def test_search_uses_fts_and_scope_filters(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            global_item = store.append(MemoryItem.new(
                user_id="demo",
                scope="global",
                type="preference",
                section="output_style",
                content="回答默认使用中文。",
            ))
            store.append(MemoryItem.new(
                user_id="demo",
                scope="agent",
                agent_id="coding",
                type="preference",
                section="output_style",
                content="回答默认使用中文标题。",
            ))

            results = store.search("demo", "请继续使用中文回答", scope="global")

        self.assertEqual([item.memory_id for item in results], [global_item.memory_id])

    def test_search_splits_chinese_current_message_into_trigram_terms(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            saved = store.append(MemoryItem.new(
                user_id="demo",
                scope="global",
                type="fact",
                section="profile",
                content="用户喜欢番茄炒蛋。",
            ))

            results = store.search("demo", "晚餐和番茄炒蛋有关吗")

        self.assertEqual([item.memory_id for item in results], [saved.memory_id])

    def test_agent_scope_requires_matching_agent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            store.append(MemoryItem.new(
                user_id="demo",
                scope="agent",
                agent_id="main",
                type="constraint",
                section="runtime",
                content="保持 thin harness 边界。",
            ))

            self.assertEqual(store.list_active("demo", scope="agent", agent_id="coding"), [])
            self.assertEqual(len(store.list_active("demo", scope="agent", agent_id="main")), 1)

    def test_replace_supersedes_old_item(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            old = store.append(MemoryItem.new(
                user_id="demo",
                scope="global",
                type="preference",
                section="output_style",
                content="回答默认使用英文。",
            ))
            new = store.replace(old.memory_id, MemoryItem.new(
                user_id="demo",
                scope="global",
                type="preference",
                section="output_style",
                content="回答默认使用中文。",
            ))

            old_loaded = store.get(old.memory_id)
            active = store.list_active("demo", scope="global", type="preference")
            search_old = store.search("demo", "英文")
            search_new = store.search("demo", "中文")

        self.assertIsNotNone(old_loaded)
        assert old_loaded is not None
        self.assertEqual(old_loaded.status, "superseded")
        self.assertEqual([item.memory_id for item in active], [new.memory_id])
        self.assertEqual(search_old, [])
        self.assertEqual([item.memory_id for item in search_new], [new.memory_id])

    def test_delete_hides_item_from_active_and_search(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            saved = store.append(MemoryItem.new(
                user_id="demo",
                scope="global",
                type="preference",
                section="output_style",
                content="回答默认使用中文。",
            ))
            deleted = store.delete(saved.memory_id)

            self.assertEqual(deleted.status, "deleted")
            self.assertEqual(store.list_active("demo", scope="global"), [])
            self.assertEqual(store.search("demo", "中文"), [])

    def test_priority_then_updated_order_is_stable(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            low = store.append(MemoryItem.new(
                user_id="demo",
                scope="global",
                type="fact",
                section="profile",
                content="低优先级事实。",
                priority=10,
                updated_at="2026-05-14T00:00:00Z",
                created_at="2026-05-14T00:00:00Z",
            ))
            high_old = store.append(MemoryItem.new(
                user_id="demo",
                scope="global",
                type="fact",
                section="profile",
                content="高优先级旧事实。",
                priority=80,
                updated_at="2026-05-14T00:00:01Z",
                created_at="2026-05-14T00:00:01Z",
            ))
            high_new = store.append(MemoryItem.new(
                user_id="demo",
                scope="global",
                type="fact",
                section="profile",
                content="高优先级新事实。",
                priority=80,
                updated_at="2026-05-14T00:00:02Z",
                created_at="2026-05-14T00:00:02Z",
            ))

            active = store.list_active("demo", scope="global")

        self.assertEqual([item.memory_id for item in active], [high_new.memory_id, high_old.memory_id, low.memory_id])


if __name__ == "__main__":
    unittest.main()
