import tempfile
import unittest
from pathlib import Path

from marten_runtime.knowledge.config import load_knowledge_config
from marten_runtime.knowledge.service import KnowledgeService
from marten_runtime.tools.builtins.knowledge_tool import run_knowledge_tool
from marten_runtime.tools.builtins.bazi_tool import (
    CURRENT_RESULT_STATE_KEY,
    RESULTS_BY_ACTION_STATE_KEY,
)


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

    def test_bazi_theory_search_replaces_raw_birth_query_with_chart_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = KnowledgeService(load_knowledge_config.from_text(_config(tmp)).knowledge)
            service.ingest_text(
                namespace="bazi-theory",
                source={
                    "title": "财格资料",
                    "kind": "text",
                    "uri": "local://wealth-pattern",
                    "text": "庚金生卯月，正财当令，财官同见，应先辨身财官强弱。",
                    "metadata": {"evidence_kind": "classical_original"},
                },
            )
            service.ingest_text(
                namespace="bazi-theory",
                source={
                    "title": "命运开启智慧之门",
                    "kind": "text",
                    "uri": "local://author-method",
                    "text": (
                        "过三关具体应验 原局大运流年综合细致断事 "
                        "应期方法 大运流年 健康取象 五行生克 神煞应用 用忌条件 "
                        "婚姻宫逢冲 配偶星 婚姻不顺 离婚 六亲应期 父母星宫。"
                    ),
                    "metadata": {
                        "evidence_kind": "modern_commentary",
                        "content_type": "author_method",
                    },
                },
            )
            chart = _bazi_chart()
            dayun = {
                "ok": True,
                "action": "dayun",
                "result": {"大运列表": [{"起运年份": 2017, "干支": "庚午"}]},
            }
            context = {
                "agent_id": "bazi",
                "message": "男，1994年农历二月十四，请按子平格局法分析。",
                "turn_tool_state": {
                    CURRENT_RESULT_STATE_KEY: dayun,
                    RESULTS_BY_ACTION_STATE_KEY: {"chart": chart, "dayun": dayun},
                },
            }

            result = run_knowledge_tool(
                {"action": "search", "namespace": "bazi-theory", "query": "1994年农历二月十四"},
                knowledge_service=service,
                tool_context=context,
            )

            self.assertTrue(result["ok"])
            self.assertIn("庚金生卯月", result["query"])
            self.assertIn("正财格", result["query"])
            self.assertNotIn("1994", result["query"])
            self.assertEqual(result["query_plan"]["strategy"], "bazi_chart_multitopic_v3")
            self.assertGreater(len(result["query_plan"]["subqueries"]), 1)
            self.assertEqual(result["query_plan"]["targeted_content_types"], ["author_method"])
            self.assertTrue(
                any(
                    dict(item.get("metadata") or {}).get("content_type") == "author_method"
                    for item in result["results"]
                )
            )


def _bazi_chart() -> dict:
    return {
        "ok": True,
        "action": "chart",
        "result": {
            "基本信息": {"性别": "男", "日主": "庚"},
            "四柱": [
                {"干支": "甲戌", "天干十神": "偏财", "藏干": [{"十神": "偏印"}]},
                {"干支": "丁卯", "天干十神": "正官", "藏干": [{"十神": "正财"}]},
                {"干支": "庚戌", "天干十神": "-", "藏干": [{"十神": "偏印"}]},
                {"干支": "庚辰", "天干十神": "比肩", "藏干": [{"十神": "偏印"}]},
            ],
            "干支关系": ["卯戌六合", "辰戌相冲"],
        },
    }


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
