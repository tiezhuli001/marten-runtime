from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "evals" / "fixtures" / "knowledge" / "bazi_theory_minimal.json"


class BaziTheoryFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_classical_excerpts_have_fixed_traceable_provenance(self) -> None:
        excerpts = [
            source
            for source in self.fixture["sources"]
            if source["metadata"].get("content_type")
            == "classical_excerpt_with_marten_commentary"
        ]
        self.assertEqual(len(excerpts), 4)

        required_metadata = {
            "work",
            "chapter",
            "edition_or_source",
            "source_url",
            "verification_status",
            "license",
            "provenance",
        }
        for source in excerpts:
            with self.subTest(source_id=source["source_id"]):
                metadata = source["metadata"]
                self.assertTrue(required_metadata <= metadata.keys())
                self.assertEqual(source["title"], metadata["work"])
                self.assertIn("oldid=", source["uri"])
                self.assertEqual(source["uri"], metadata["source_url"])
                self.assertIn("# 古籍原文\n\n", source["text"])
                self.assertIn("# Marten 释义\n\n", source["text"])
                self.assertLess(
                    source["text"].index("# 古籍原文"),
                    source["text"].index("# Marten 释义"),
                )

    def test_marten_summaries_do_not_present_classic_titles_as_source_titles(self) -> None:
        classic_titles = {"穷通宝鉴", "子平真诠", "滴天髓", "神峰通考"}
        summaries = [source for source in self.fixture["sources"] if source["kind"] == "method_summary"]
        for source in summaries:
            with self.subTest(source_id=source["source_id"]):
                self.assertNotIn(source["title"], classic_titles)
                self.assertIn("Marten", source["metadata"]["provenance"])

    def test_verified_excerpt_text_matches_reviewed_transcriptions(self) -> None:
        by_id = {source["source_id"]: source for source in self.fixture["sources"]}
        expected = {
            "ksrc_bazi_qiongtong_jia_spring_v1": "正月甲木，初春尚有余寒，得丙癸逢，富贵双全。",
            "ksrc_bazi_ditiansui_geju_v1": "財官印綬分偏正，兼論食傷格局定。",
            "ksrc_bazi_ditiansui_wealth_v1": "無財而暗成財局，財露而傷官亦露",
            "ksrc_bazi_shenfeng_bingyao_v1": "有病方为贵，无伤不是奇；格中如去病，财禄两相随。",
        }
        for source_id, excerpt in expected.items():
            with self.subTest(source_id=source_id):
                self.assertIn(excerpt, by_id[source_id]["text"])

    def test_marten_method_summary_distinguishes_self_punishment_and_repetition(self) -> None:
        by_id = {source["source_id"]: source for source in self.fixture["sources"]}
        source = by_id["ksrc_bazi_mangpai_v1"]

        self.assertEqual(source["version"], "2.1.0")
        self.assertIn("自刑限定为辰辰、午午、酉酉、亥亥", source["text"])
        self.assertIn("巳巳属于伏吟", source["text"])
        self.assertIn("寅午戌见卯、申子辰见酉、巳酉丑见午、亥卯未见子", source["text"])
        self.assertIn("检查、治疗、住院或开刀", source["text"])
        self.assertIn("父亲与母亲健康分开结合父星、母星、年柱", source["text"])
        self.assertIn("申酉缺少稳定身体部位归纳", source["text"])
        self.assertIn("现实结论以体检和医疗专业意见为准", source["text"])


if __name__ == "__main__":
    unittest.main()
