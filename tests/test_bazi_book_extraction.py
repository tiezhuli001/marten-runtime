from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from marten_runtime.bazi_cases.book_extraction import BookProfile, extract_book_cases, extraction_report
from marten_runtime.bazi_cases.author_experience import extract_author_material, render_author_chapters


class BaziBookExtractionTests(unittest.TestCase):
    def test_chapter_parser_accepts_colon_and_missing_space(self) -> None:
        text = """第1章：似水流年
八字命局需要结合日主、月令、十神、用神、忌神、大运和流年判断应期。流年负责具体应验，不能脱离原局判断。
如果大运确定阶段，流年引动原局宫位与十神，才可以判断具体事件；但不能只凭一个流年断事。

第 2章星宫位
八字星宫位教学需要结合命局、日主、月令、十神、用神、大运和流年。宫位代表对象，十神说明关系，岁运引动才是应期。
当原局、大运、流年共同作用时，可以判断应验对象；但不是每个冲合都对应重大事件。
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.txt"
            path.write_text(text, encoding="utf-8")
            chapters, _ = extract_author_material(path, BookProfile(title="测试书"))

        self.assertEqual(
            [item.title for item in chapters],
            ["第1章：似水流年", "第 2章星宫位"],
        )

    def test_author_material_keeps_complete_chapter_and_builds_conditioned_cards(self) -> None:
        text = """第707章 八字神煞篇（一）
八字神煞教学需要先看命局、日主、月令、十神、用神和忌神。神煞在大运流年只能辅助应期判断。天乙贵人、文昌贵人、禄神、羊刃、天医、将星、华盖、金舆、马星、桃花、空亡、灾煞都要结合五行生克。
如果五行生克为凶，又遇羊刃逢冲，才可以把伤灾作为待核验方向；不能只见羊刃就判断疾病。

第708章 日常故事
这里没有八字教学内容。
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.txt"
            path.write_text(text, encoding="utf-8")
            chapters, cards = extract_author_material(path, BookProfile(title="测试书", author="作者"))

        self.assertEqual([item.title for item in chapters], ["第707章 八字神煞篇（一）"])
        self.assertIn("天乙贵人", chapters[0].text)
        self.assertTrue(any(card.topic == "神煞" and "羊刃" in card.shensha_support for card in cards))
        self.assertTrue(any("不能" in card.exceptions for card in cards))
        rendered = render_author_chapters(chapters)
        self.assertGreaterEqual(rendered.count("原文行：1-4"), 2)
    def test_generic_pipeline_extracts_narrative_and_compact_cases(self) -> None:
        text = """第1章 案例一
男命：戊寅年，丁巳月，丁巳日，辛丑时。
命主五岁起戊午大运，十五岁己未大运，二十五岁庚申大运。
分析认为身旺，以伤官生财为主要观察线索。原局火旺，财星在时柱，行运时还要检查三合局是否改变旺衰和用神。命主后来开始经商，已经拥有较多资产，并长期经营餐饮和住宿业务，现实经历与前述分析存在可核验的对应关系。

第2章 案例二
坤造：戊辰 庚申 辛巳 辛卯
此造以母亲健康为问题，推断2002年需要关注。
事实是母亲于2002年去世。
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.txt"
            path.write_text(text, encoding="utf-8")
            candidates = extract_book_cases(path, BookProfile(title="测试书", author="作者"))

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].pillars, ["戊寅", "丁巳", "丁巳", "辛丑"])
        self.assertEqual(candidates[0].grade, "A")
        self.assertEqual(candidates[1].events[0]["evidence_type"], "document_verified")
        self.assertEqual(candidates[1].events[0]["subject"], "mother")
        self.assertEqual(candidates[1].source_ref["line_start"], 7)

    def test_rules_without_feedback_are_not_accepted(self) -> None:
        text = """第1章 理论示例
乾造：甲子 丙寅 戊辰 庚申
这个命局用于说明一般理论，可能在2028年发生事业变化。分析时需要先看月令和日主，再看天干是否透出以及地支是否有根，最后结合大运流年判断，还要区分原局事实和方法解释，检查用神是否随岁运改变；但这里没有提供命主后续反馈，只能作为规则示例，不能作为真实事件案例。
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.txt"
            path.write_text(text, encoding="utf-8")
            candidates = extract_book_cases(path, BookProfile(title="测试书"))

        self.assertEqual(candidates[0].grade, "C")
        self.assertEqual(extraction_report(candidates)["accepted_count"], 0)
        self.assertEqual(candidates[0].events, [])
        self.assertEqual(len(candidates[0].predictions), 1)

    def test_feedback_uses_actual_final_year_and_links_review(self) -> None:
        text = """第720章 理论联系实际
男命：乙卯年，乙酉月，癸酉日，庚申时。
第一位判断1999年己卯年结婚。第二位判断在2000年庚辰年结婚。
事实是命主在1999年想结婚，但遭到家中反对，的确推迟到2000年上半年结婚。
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.txt"
            path.write_text(text, encoding="utf-8")
            candidate = extract_book_cases(path, BookProfile(title="测试书"))[0]

        self.assertEqual(candidate.events[0]["time_start"], "2000")
        self.assertEqual(candidate.events[0]["subject"], "self")
        self.assertEqual(candidate.reviews[0]["outcome"], "confirmed")
        self.assertEqual(
            candidate.events[0]["linked_prediction_ids"],
            [candidate.reviews[0]["prediction_id"]],
        )
