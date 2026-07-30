from __future__ import annotations

import unittest

from marten_runtime.bazi.retrieval_query import (
    build_bazi_retrieval_plan,
    rerank_bazi_theory_results,
)


def _chart() -> dict[str, object]:
    return {
        "ok": True,
        "result": {
            "基本信息": {"性别": "男", "日主": "庚"},
            "四柱": [
                {"干支": "甲戌", "天干十神": "偏财", "藏干": [{"天干": "戊", "十神": "偏印"}]},
                {"干支": "丁卯", "天干十神": "正官", "藏干": [{"天干": "乙", "十神": "正财"}]},
                {"干支": "庚戌", "天干十神": "-", "藏干": [{"天干": "戊", "十神": "偏印"}]},
                {"干支": "庚辰", "天干十神": "比肩", "藏干": [{"天干": "戊", "十神": "偏印"}]},
            ],
            "干支关系": ["戌卯六合化火", "戌辰相冲", "卯辰相害", "甲庚冲克"],
        },
        "relatedResults": {
            "dayun": {
                "大运列表": [
                    {"起运年份": 2017, "干支": "庚午"},
                    {"起运年份": 2027, "干支": "辛未"},
                ]
            }
        },
    }


class BaziRetrievalQueryTests(unittest.TestCase):
    def test_plan_uses_chart_facts_instead_of_birth_sentence(self) -> None:
        plan = build_bazi_retrieval_plan(
            _chart(),
            user_message="男，1994年农历2月14日早上8点40，请按子平格局法和盲派分析事业婚姻。",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("庚金生卯月", plan.theory_query)
        self.assertIn("正财格", plan.theory_query)
        self.assertIn("财生官", plan.theory_query)
        self.assertIn("比劫财星", plan.theory_query)
        self.assertIn("财官同见", plan.facts)
        self.assertIn("正财格候选", plan.facts)
        self.assertIn("当前庚午大运", plan.case_query)
        self.assertIn("事业", plan.case_query)
        self.assertIn("婚姻", plan.case_query)
        self.assertNotIn("1994", plan.theory_query)
        self.assertNotIn("正官格", plan.theory_query)
        self.assertEqual(plan.classical_query, "月令")
        self.assertIn("婚姻宫逢冲", plan.author_method_query)
        self.assertNotIn("事业应期", plan.author_method_query)

    def test_full_analysis_requests_author_method_topics(self) -> None:
        plan = build_bazi_retrieval_plan(_chart(), user_message="请按子平格局法和盲派完整分析")

        assert plan is not None
        self.assertIn("健康取象", plan.theory_query)
        self.assertIn("神煞应用", plan.theory_query)
        self.assertIn("婚姻应期", plan.theory_query)
        self.assertIn("过三关具体应验", plan.theory_query)
        self.assertEqual(
            plan.evidence_topics,
            (
                "过三关",
                "应期",
                "神煞",
                "健康取象",
                "婚姻",
                "六亲",
                "事业",
                "财富",
                "学历",
            ),
        )
        self.assertEqual(
            plan.author_method_query,
            "过三关 大运定阶段 流年定具体应验 星宫位 寻根基 找出处 引动原理",
        )
        self.assertEqual(len(plan.theory_queries), 4)
        self.assertTrue(any("过三关具体应验" in query for query in plan.theory_queries))
        self.assertTrue(any("健康取象" in query for query in plan.theory_queries))
        self.assertTrue(any("神煞应用" in query for query in plan.theory_queries))
        self.assertTrue(any("事业应期" in query for query in plan.theory_queries))

    def test_domain_rerank_reserves_author_method_and_chapter_evidence(self) -> None:
        plan = build_bazi_retrieval_plan(_chart(), user_message="完整分析")
        assert plan is not None
        results = [
            {
                "chunk_id": f"core-{index}", "source_id": f"classic-{index}",
                "heading": f"格局{index}", "text": "庚金生卯月正财当令",
                "score": 1.0 - index / 20,
                "metadata": {"evidence_kind": "classical_original"},
            }
            for index in range(5)
        ] + [
            {
                "chunk_id": "method", "source_id": "author-method", "heading": "具体应验经验卡",
                "text": "原局大运流年综合判断，流年是大事情具体应验的时间", "score": 0.2,
                "metadata": {"evidence_kind": "modern_commentary", "content_type": "author_method"},
            },
            {
                "chunk_id": "method-2", "source_id": "author-method-2", "heading": "似水流年",
                "text": "大运定阶段，流年定具体应验，结合星宫位判断人事对象", "score": 0.18,
                "metadata": {"evidence_kind": "modern_commentary", "content_type": "author_method"},
            },
            {
                "chunk_id": "chapter", "source_id": "author-chapter", "heading": "神煞教学章节",
                "text": "神煞应用先看五行生克和用忌条件", "score": 0.1,
                "metadata": {"evidence_kind": "modern_commentary", "content_type": "author_chapter"},
            },
        ]

        reranked = rerank_bazi_theory_results(results, plan=plan, top_k=5)

        self.assertIn("method", {item["chunk_id"] for item in reranked})
        self.assertIn("method-2", {item["chunk_id"] for item in reranked})
        self.assertIn("chapter", {item["chunk_id"] for item in reranked})
        self.assertTrue(any(item["chunk_id"].startswith("core-") for item in reranked))
        self.assertTrue(reranked[0]["chunk_id"].startswith("core-"))

    def test_domain_rerank_prefers_author_method_over_generic_timing_method(self) -> None:
        plan = build_bazi_retrieval_plan(_chart(), user_message="完整分析")
        assert plan is not None
        results = [
            {
                "chunk_id": "classic", "source_id": "classic", "heading": "月令",
                "text": "庚金生卯月正财当令", "score": 1.0,
                "metadata": {"evidence_kind": "classical_original"},
            },
            {
                "chunk_id": "timing", "source_id": "timing", "heading": "通用应期",
                "text": "大运流年应期", "score": 0.9,
                "metadata": {"evidence_kind": "modern_commentary", "content_type": "timing_method"},
            },
            {
                "chunk_id": "author", "source_id": "author", "heading": "具体应验作者经验卡",
                "text": "流年是人生大事情具体应验的时间", "score": 0.1,
                "metadata": {"evidence_kind": "modern_commentary", "content_type": "author_method"},
            },
            {
                "chunk_id": "chapter", "source_id": "chapter", "heading": "作者教学章节",
                "text": "原局大运流年综合判断", "score": 0.05,
                "metadata": {"evidence_kind": "modern_commentary", "content_type": "author_chapter"},
            },
            {
                "chunk_id": "core", "source_id": "core", "heading": "财官",
                "text": "财官同见", "score": 0.8,
                "metadata": {"evidence_kind": "historical_commentary"},
            },
        ]

        reranked = rerank_bazi_theory_results(results, plan=plan, top_k=3)

        chunk_ids = {item["chunk_id"] for item in reranked}
        self.assertIn("author", chunk_ids)
        self.assertNotIn("timing", chunk_ids)

    def test_full_analysis_does_not_select_off_topic_author_method(self) -> None:
        plan = build_bazi_retrieval_plan(_chart(), user_message="完整分析")
        assert plan is not None
        results = [
            {
                "chunk_id": "classic", "source_id": "classic", "heading": "月令",
                "text": "月令取格", "score": 1.0,
                "metadata": {"evidence_kind": "classical_original"},
            },
            {
                "chunk_id": "wealth", "source_id": "author", "heading": "财富案例",
                "text": "身弱财旺，等待大运流年帮身即可求财", "score": 0.9,
                "metadata": {"evidence_kind": "modern_commentary", "content_type": "author_method"},
            },
            {
                "chunk_id": "timing", "source_id": "author", "heading": "具体应验",
                "text": "原局大运流年综合断事，流年确定应验", "score": 0.2,
                "metadata": {"evidence_kind": "modern_commentary", "content_type": "author_method"},
            },
            {
                "chunk_id": "chapter", "source_id": "chapter", "heading": "教学章节",
                "text": "完整章节", "score": 0.1,
                "metadata": {"evidence_kind": "modern_commentary", "content_type": "author_chapter"},
            },
        ]

        selected = rerank_bazi_theory_results(results, plan=plan, top_k=3)
        chunk_ids = [item["chunk_id"] for item in selected]

        self.assertIn("timing", chunk_ids)
        self.assertNotIn("wealth", chunk_ids)

    def test_domain_rerank_promotes_matching_month_order_evidence(self) -> None:
        plan = build_bazi_retrieval_plan(_chart(), user_message="按子平格局法分析")
        assert plan is not None
        results = [
            {
                "chunk_id": "generic",
                "source_title": "三命通会",
                "heading": "论正官",
                "text": "正官先看月令，官星宜财印两扶。",
                "score": 1.0,
                "score_parts": {"rerank": 0.9},
                "metadata": {"evidence_kind": "classical_original"},
            },
            {
                "chunk_id": "matching",
                "source_title": "八字命理评点",
                "heading": "财星秉令",
                "text": "庚金生卯月，正财当令，财官同见，并见辰戌相冲。",
                "score": 0.6,
                "score_parts": {"rerank": 0.5},
                "metadata": {"evidence_kind": "modern_commentary"},
            },
        ]

        reranked = rerank_bazi_theory_results(results, plan=plan, top_k=2)

        self.assertEqual(reranked[0]["chunk_id"], "matching")
        self.assertGreater(
            reranked[0]["score_parts"]["bazi_domain"],
            reranked[1]["score_parts"]["bazi_domain"],
        )


if __name__ == "__main__":
    unittest.main()
