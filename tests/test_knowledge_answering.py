from __future__ import annotations

import unittest

from marten_runtime.knowledge.answering import KnowledgeAnswerService
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient


class _KnowledgeService:
    def __init__(self, results: list[dict[str, object]]) -> None:
        self.results = results

    def search(self, **kwargs) -> dict[str, object]:  # noqa: ANN003
        return {
            "ok": True,
            "query": kwargs["query"],
            "results": self.results,
            "embedding_ms": 1.0,
            "total_ms": 2.0,
        }


class KnowledgeAnsweringTests(unittest.TestCase):
    def test_answer_uses_three_theory_evidence_items_and_exactly_one_model_request(self) -> None:
        llm = ScriptedLLMClient([LLMReply(final_text="## 原文依据\n月劫。\n## 现代解释\n解释。\n## 适用限制\n有限。\n## 引用\n[证据 1]")])
        service = KnowledgeAnswerService(
            knowledge_service=_KnowledgeService(
                [
                    _item("c1", "s1", "论用神成败救应", "建禄月劫，透官而逢财印。", "classical_original"),
                    _item("c2", "s2", "论用神成败救应", "月劫格以月令为据。", "modern_commentary"),
                    _item("c3", "s3", "课程", "月劫格课程。", "course_notes"),
                    _item("c4", "s4", "命例", "月劫格命例。", "case_record"),
                    _item("c5", "s5", "论月令", "月劫与建禄相关。", "classical_original"),
                ]
            ),
            llm_factory=lambda: llm,
            model_profile="test",
        )

        result = service.answer(namespace="bazi-theory", query="月劫格有什么特征")

        self.assertTrue(result["ok"])
        self.assertEqual(result["model_request_count"], 1)
        self.assertEqual(len(llm.requests), 1)
        self.assertEqual(len(result["evidence"]), 3)
        self.assertNotIn("course_notes", {item["evidence_kind"] for item in result["evidence"]})
        self.assertNotIn("results", result["retrieval"])
        self.assertEqual(result["retrieval"]["embedding_ms"], 1.0)
        request = llm.requests[0]
        self.assertEqual(request.request_kind, "knowledge_answer")
        self.assertEqual(request.max_completion_tokens, 640)
        self.assertIn("不超过 600 个中文字符", request.message)
        self.assertEqual(request.available_tools, [])
        self.assertLessEqual(len(request.message), 6_500)

    def test_answer_refuses_without_direct_support_and_does_not_call_model(self) -> None:
        llm = ScriptedLLMClient([])
        service = KnowledgeAnswerService(
            knowledge_service=_KnowledgeService(
                [_item("c1", "s1", "论用神", "八字用神，专求月令。", "classical_original")]
            ),
            llm_factory=lambda: llm,
            model_profile="test",
        )

        result = service.answer(namespace="bazi-theory", query="量子计算是什么")

        self.assertTrue(result["ok"])
        self.assertTrue(result["insufficient_evidence"])
        self.assertEqual(result["model_request_count"], 0)
        self.assertEqual(llm.requests, [])
        self.assertNotIn("results", result["retrieval"])

    def test_answer_preserves_retrieval_rank_across_evidence_kinds(self) -> None:
        llm = ScriptedLLMClient([LLMReply(final_text="有依据。")])
        service = KnowledgeAnswerService(
            knowledge_service=_KnowledgeService(
                [
                    _item("c1", "s1", "月劫释义", "月劫格以月令为据。", "modern_commentary"),
                    _item("c2", "s2", "建禄月劫", "月劫透官，宜见财印。", "classical_original"),
                    _item("c3", "s3", "月劫补注", "月劫须结合透干判断。", "historical_commentary"),
                    _item("c4", "s4", "低相关原文", "月劫二字偶见于此。", "classical_original"),
                ]
            ),
            llm_factory=lambda: llm,
            model_profile="test",
        )

        result = service.answer(namespace="bazi-theory", query="月劫格有什么特征")

        self.assertEqual(
            [item["chunk_id"] for item in result["evidence"]],
            ["c1", "c2", "c3"],
        )

    def test_answer_does_not_fill_direct_concept_evidence_with_unrelated_results(self) -> None:
        llm = ScriptedLLMClient([LLMReply(final_text="有依据。")])
        service = KnowledgeAnswerService(
            knowledge_service=_KnowledgeService(
                [
                    _item("c1", "s1", "月劫", "月劫透官以制伏。", "classical_original"),
                    _item("c2", "s2", "月劫变化", "月劫化为食伤。", "classical_original"),
                    _item("c3", "s3", "泛论格局", "有格不正者败。", "classical_original"),
                ]
            ),
            llm_factory=lambda: llm,
            model_profile="test",
        )

        result = service.answer(namespace="bazi-theory", query="月劫格有什么特征")

        self.assertEqual([item["chunk_id"] for item in result["evidence"]], ["c1", "c2"])


def _item(chunk_id: str, source_id: str, heading: str, text: str, evidence_kind: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "source_title": "经典",
        "heading": heading,
        "text": text,
        "metadata": {"evidence_kind": evidence_kind},
    }


if __name__ == "__main__":
    unittest.main()
