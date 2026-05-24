import tempfile
import unittest
from pathlib import Path

from marten_runtime.knowledge.config import load_knowledge_config
from marten_runtime.knowledge.service import KnowledgeService
from marten_runtime.tools.builtins.knowledge_tool import run_knowledge_tool


class KnowledgeToolTests(unittest.TestCase):
    def test_tool_dispatches_actions_without_host_intent_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = KnowledgeService(load_knowledge_config.from_text(_config(tmp)).knowledge)
            ingest = run_knowledge_tool(
                {"action": "ingest_text", "namespace": "fanqie", "source": {"title": "Book", "kind": "text", "uri": "local://book", "text": "师父在山门出现"}},
                knowledge_service=service,
            )
            self.assertTrue(ingest["ok"])

            search = run_knowledge_tool(
                {"action": "search", "namespace": "fanqie", "query": "师父", "top_k": 1},
                knowledge_service=service,
            )
            self.assertTrue(search["ok"])
            self.assertEqual(len(search["results"]), 1)

    def test_tool_rejects_invalid_top_k(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = KnowledgeService(load_knowledge_config.from_text(_config(tmp)).knowledge)
            result = run_knowledge_tool(
                {"action": "search", "namespace": "fanqie", "query": "师父", "top_k": 0},
                knowledge_service=service,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "KNOWLEDGE_TOP_K_INVALID")
            self.assertEqual(result["top_k"], 0)

    def test_tool_dispatches_model_status_and_unload_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = KnowledgeService(load_knowledge_config.from_text(_config(tmp)).knowledge)
            status = run_knowledge_tool({"action": "model_status"}, knowledge_service=service)
            self.assertTrue(status["ok"])
            self.assertEqual(status["embedding"]["status"], "not_loaded")

            service.ingest_text(namespace="fanqie", source={"title": "Book", "kind": "text", "uri": "local://book", "text": "师父在山门出现"})
            unloaded = run_knowledge_tool({"action": "unload_models"}, knowledge_service=service)
            self.assertTrue(unloaded["ok"])
            self.assertEqual(unloaded["embedding"]["status"], "not_loaded")

    def test_tool_reports_missing_required_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = KnowledgeService(load_knowledge_config.from_text(_config(tmp)).knowledge)
            with self.assertRaises(ValueError):
                run_knowledge_tool({}, knowledge_service=service)


def _config(tmp: str) -> str:
    root = Path(tmp)
    return f'''
[knowledge]
db_path = "{root / 'knowledge.sqlite3'}"
default_namespace = "personal"
model_idle_ttl_seconds = 300
[knowledge.chunking]
target_chars = 100
overlap_chars = 10
max_chars = 160
batch_size = 4
[knowledge.embedding]
provider = "fake"
model = "fake-embedding"
local_path = "{root / 'models' / 'embedding'}"
dimension = 8
allow_remote_download = false
use_fp16 = false
[knowledge.reranker]
provider = "fake"
model = "fake-reranker"
local_path = "{root / 'models' / 'reranker'}"
allow_remote_download = false
use_fp16 = false
top_n = 10
[knowledge.vector_store]
enabled = true
backend = "sqlite_vec"
[knowledge.search]
default_top_k = 5
candidate_pool = 20
fts_weight = 1.0
vector_weight = 1.0
metadata_weight = 0.2
reranker_weight = 2.0
'''


if __name__ == "__main__":
    unittest.main()
