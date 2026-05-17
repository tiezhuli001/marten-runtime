import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.memory.loader import MemoryLoadRequest, MemoryLoader
from marten_runtime.memory.models import MemoryItem
from marten_runtime.memory.sqlite_store import SQLiteMemoryStore


class MemoryLoaderTests(unittest.TestCase):
    def test_loader_includes_global_and_selected_agent_memory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            store.append(MemoryItem.new(user_id="demo", scope="global", type="preference", section="output_style", content="回答默认使用中文。"))
            store.append(MemoryItem.new(user_id="demo", scope="agent", agent_id="main", type="constraint", section="runtime", content="保持 thin harness 边界。"))
            store.append(MemoryItem.new(user_id="demo", scope="agent", agent_id="coding", type="constraint", section="runtime", content="只输出补丁。"))

            result = MemoryLoader(store).load(MemoryLoadRequest(user_id="demo", agent_id="main", current_message="继续中文回答", char_budget=400))

        self.assertIn("[preference][global] 回答默认使用中文。", result.rendered_text or "")
        self.assertIn("[constraint][agent:main] 保持 thin harness 边界。", result.rendered_text or "")
        self.assertNotIn("agent:coding", result.rendered_text or "")

    def test_loader_includes_workspace_only_when_matched(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            store.append(MemoryItem.new(user_id="demo", scope="workspace", workspace_id="repo-a", type="workflow_hint", section="testing", content="先跑 memory eval。"))
            store.append(MemoryItem.new(user_id="demo", scope="workspace", workspace_id="repo-b", type="workflow_hint", section="testing", content="先跑 provider eval。"))

            result = MemoryLoader(store).load(MemoryLoadRequest(user_id="demo", workspace_id="repo-a", current_message="测试", char_budget=400))

        self.assertIn("[workflow_hint][workspace:repo-a] 先跑 memory eval。", result.rendered_text or "")
        self.assertNotIn("repo-b", result.rendered_text or "")

    def test_loader_recalls_fts_match_from_current_message(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            item = store.append(MemoryItem.new(user_id="demo", scope="global", type="fact", section="profile", content="用户喜欢番茄炒蛋。"))

            result = MemoryLoader(store).load(MemoryLoadRequest(user_id="demo", current_message="晚餐和番茄炒蛋有关吗", char_budget=400))

        self.assertIn(item.memory_id, [loaded.memory_id for loaded in result.items])
        self.assertIn("番茄炒蛋", result.rendered_text or "")

    def test_loader_dedupes_items_from_list_and_search(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            store.append(MemoryItem.new(user_id="demo", scope="global", type="preference", section="output_style", content="回答默认使用中文。"))

            result = MemoryLoader(store).load(MemoryLoadRequest(user_id="demo", current_message="中文", char_budget=400))

        self.assertEqual((result.rendered_text or "").count("回答默认使用中文。"), 1)

    def test_loader_respects_char_budget_and_priority(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteMemoryStore(Path(tmpdir) / "memory.sqlite3")
            store.append(MemoryItem.new(user_id="demo", scope="global", type="fact", section="profile", content="低优先级内容很长很长很长。", priority=10))
            high = store.append(MemoryItem.new(user_id="demo", scope="global", type="constraint", section="runtime", content="高优先级。", priority=90))

            result = MemoryLoader(store).load(MemoryLoadRequest(user_id="demo", current_message="内容", char_budget=60))

        self.assertEqual([item.memory_id for item in result.items], [high.memory_id])
        self.assertIn("高优先级", result.rendered_text or "")
        self.assertNotIn("低优先级", result.rendered_text or "")


if __name__ == "__main__":
    unittest.main()
