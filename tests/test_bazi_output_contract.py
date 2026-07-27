from __future__ import annotations

import unittest

from marten_runtime.runtime.bazi_output_contract import (
    bazi_repair_source_text,
    bazi_timing_contract_violations,
    bazi_violation_sections,
    merge_bazi_repaired_sections,
    missing_bazi_sections,
    normalize_bazi_timing_contract_text,
    normalize_verification_event_text,
    past_event_timing_categories,
)


class BaziOutputContractTests(unittest.TestCase):
    def test_wealth_rejects_projection_without_real_world_baseline(self) -> None:
        text = (
            "九、财富等级\n"
            "年均可积累 20 万 × 10 年 = 200 万，属于普通积累。"
        )

        self.assertIn(
            "财富栏使用了用户未提供的现实收入或资产基线",
            bazi_timing_contract_violations(text),
        )

    def test_wealth_rejects_asset_range_after_saying_baseline_is_missing(self) -> None:
        text = (
            "九、财富等级\n"
            "未提供当前收入、资产、负债或储蓄率。预计总资产 320-780 万元。"
        )

        self.assertIn(
            "财富栏使用了用户未提供的现实收入或资产基线",
            bazi_timing_contract_violations(text),
        )

    def test_wealth_accepts_user_supplied_income_baseline(self) -> None:
        text = (
            "九、财富等级\n"
            "用户提供当前收入 40 万。财富结构分：6/9；"
            "成局路径 2 + 承载 2 + 大运 3 - 制约 1。"
            "命理年收入能力区间：30-60 万元；不等同现实收入。"
        )

        self.assertFalse(
            any("财富栏" in item for item in bazi_timing_contract_violations(text))
        )

    def test_wealth_accepts_structured_bazi_income_estimate_without_baseline(self) -> None:
        text = (
            "九、财富等级\n"
            "财富结构分：6/9；成局路径 2 + 承载 2 + 大运 3 - 制约 1。"
            "命理年收入能力区间：30-60 万元；这是文化模型估算，不等同现实收入。"
        )

        self.assertFalse(
            any("财富栏" in item for item in bazi_timing_contract_violations(text))
        )

    def test_wealth_accepts_markdown_emphasized_structure_score(self) -> None:
        text = (
            "九、财富等级\n"
            "财富结构分：**6/9＝成局路径 2 + 承载 2 + 大运 2 - 制约 0**。\n"
            "**命理年收入能力区间：30-60 万。**\n"
            "这是传统文化模型估算，**不等同现实收入**。"
        )

        self.assertFalse(
            any("财富栏" in item for item in bazi_timing_contract_violations(text))
        )

    def test_wealth_rejects_inconsistent_score_or_income_band(self) -> None:
        text = (
            "九、财富等级\n"
            "财富结构分：8/9；成局路径 2 + 承载 2 + 大运 3 - 制约 1。"
            "命理年收入能力区间：80-150 万元；不等同现实收入。"
        )

        self.assertIn(
            "财富栏缺少多路径结构评分与命理年收入能力区间",
            bazi_timing_contract_violations(text),
        )

    def test_wealth_rejects_unscored_second_income_range(self) -> None:
        text = (
            "九、财富等级\n"
            "财富结构分：6/9；成局路径 2 + 承载 2 + 大运 3 - 制约 1。"
            "命理年收入能力区间：30-60 万元；不等同现实收入。"
            "后续有机会达到 50-100 万元。"
        )

        self.assertIn(
            "财富栏缺少多路径结构评分与命理年收入能力区间",
            bazi_timing_contract_violations(text),
        )

    def test_marriage_uses_day_branch_peach_blossom_only(self) -> None:
        text = (
            "一、命盘\n地支：戌 巳 巳 辰\n"
            "七、婚姻\n2023年癸卯为桃花应期。2014年甲午为桃花应期。"
        )

        self.assertIn(
            "婚姻栏宣称的桃花流年与命局日支公式不一致",
            bazi_timing_contract_violations(text),
        )

    def test_marriage_rejects_low_risk_boilerplate_and_year_branch_combine(self) -> None:
        text = (
            "七、婚姻\n二婚风险不高，不能单凭伏吟定论。"
            "2023年虽有外缘，卯合年支戌，因此恋爱机会明显。"
        )

        violations = bazi_timing_contract_violations(text)
        self.assertIn("婚姻栏在无明确风险结论时仍讨论二婚", violations)
        self.assertIn("婚姻栏在无明确风险结论时仍讨论外缘", violations)
        self.assertIn("婚姻栏把只合年支误作夫妻宫信号", violations)

    def test_marriage_rejects_negative_risk_boilerplate_before_terms(self) -> None:
        text = "七、婚姻\n此盘不足以直接论二婚或外缘。"

        violations = bazi_timing_contract_violations(text)
        self.assertIn("婚姻栏在无明确风险结论时仍讨论二婚", violations)
        self.assertIn("婚姻栏在无明确风险结论时仍讨论外缘", violations)

    def test_mixed_marriage_signals_only_validate_year_labeled_as_peach_blossom(self) -> None:
        text = (
            "一、命盘\n地支：戌 卯 戌 辰\n"
            "七、婚姻\n桃花年重点是 2011、2023。"
            "较强婚恋年份是 2015（财星合身）、2023（桃花到位）、2024（夫妻宫受冲）。"
        )

        self.assertFalse(
            any("桃花流年" in item for item in bazi_timing_contract_violations(text))
        )

    def test_normalize_verification_event_text_removes_dangling_conjunction(self) -> None:
        self.assertEqual(
            normalize_verification_event_text("感情关系出现机会但"),
            "感情关系出现机会",
        )

    def test_normalize_contract_text_repairs_verification_event_shape(self) -> None:
        text = (
            "十、过三关\n"
            "- **2012｜升学或离家求学｜流年：壬辰；大运：辛未；原局：年时柱同动。**\n"
            "- **2018｜工作平台｜流年：戊戌；大运：壬申；原局：月柱受冲。**"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("2012｜升学｜", normalized)
        self.assertIn("2018｜工作平台发生明显变化｜", normalized)
        violations = bazi_timing_contract_violations(normalized)
        self.assertNotIn("过三关包含栏目名称，缺少可核验的具体事件", violations)
        self.assertNotIn("过三关同一行混入多个事件主题", violations)

    def test_normalize_contract_text_collapses_compact_multi_topic_event(self) -> None:
        text = (
            "十、过三关\n"
            "- 2020｜感情工作双变动｜流年：庚子；大运：壬申；原局：日月同动。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("2020｜恋爱关系变化｜", normalized)
        self.assertNotIn(
            "过三关同一行混入多个事件主题",
            bazi_timing_contract_violations(normalized),
        )

    def test_normalize_contract_text_only_removes_relationship_risk_in_marriage(self) -> None:
        text = (
            "四、健康注意\n"
            "检查时也要排除外缘环境造成的作息影响。\n"
            "七、婚姻\n"
            "此盘不足以直接论二婚或外缘。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("排除外缘环境", normalized)
        self.assertNotIn("不足以直接论二婚", normalized)

    def test_repair_source_and_merge_only_touch_violating_sections(self) -> None:
        original = (
            "## 命盘\n原命盘。\n"
            "## 六亲\n父亲信息不足。\n"
            "## 财富等级\n财富结构分：6/9。\n"
            "## 过三关\n- 2023｜健康｜流年：癸卯；大运：壬申；原局：日主受克。\n"
            "## 参考依据\n《滴天髓》·原文"
        )
        violations = [
            "六亲栏缺少父亲独立的年份、部位和岁运触发关系",
            "过三关包含栏目名称，缺少可核验的具体事件",
        ]
        sections = bazi_violation_sections(violations)
        source = bazi_repair_source_text(original, sections)
        repaired = (
            "## 六亲\n父亲本轮未形成可靠高信号健康应期。\n"
            "## 过三关\n- 2023｜体检｜流年：癸卯；大运：壬申；原局：日主受克。"
        )

        merged = merge_bazi_repaired_sections(original, repaired, sections)

        self.assertEqual(sections, ["六亲", "过三关"])
        self.assertNotIn("原命盘", source)
        self.assertNotIn("财富结构分", source)
        self.assertIn("原命盘", merged)
        self.assertIn("财富结构分：6/9", merged)
        self.assertIn("父亲本轮未形成可靠高信号健康应期", merged)
        self.assertIn("2023｜体检", merged)
        self.assertEqual(
            missing_bazi_sections(original),
            ["原局格局喜用", "大运", "健康注意", "学历", "事业", "婚姻"],
        )

    def test_missing_sections_requires_real_headings(self) -> None:
        text = (
            "命盘：甲戌、己巳、丁巳、甲辰。\n"
            "原局格局喜用：木火偏旺。\n"
            "大运：1996庚午。\n"
            "## 参考依据\n《滴天髓》·原文"
        )

        missing = missing_bazi_sections(text)

        self.assertIn("命盘", missing)
        self.assertIn("原局格局喜用", missing)
        self.assertIn("大运", missing)
        self.assertNotIn("参考依据", missing)

    def test_missing_sections_rejects_empty_heading_skeleton(self) -> None:
        text = "\n".join(f"## {section}" for section in (
            "命盘",
            "原局格局喜用",
            "大运",
            "健康注意",
            "学历",
            "事业",
            "婚姻",
            "六亲",
            "财富等级",
            "过三关",
            "参考依据",
        ))

        self.assertEqual(
            missing_bazi_sections(text),
            [
                "命盘",
                "原局格局喜用",
                "大运",
                "健康注意",
                "学历",
                "事业",
                "婚姻",
                "六亲",
                "财富等级",
                "过三关",
                "参考依据",
            ],
        )

    def test_missing_sections_accepts_numbered_markdown_headings(self) -> None:
        titles = (
            "命盘",
            "原局格局喜用",
            "大运",
            "健康注意",
            "学历",
            "事业",
            "婚姻",
            "六亲",
            "财富等级",
            "过三关",
            "参考依据",
        )
        numerals = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一")
        text = "\n".join(
            f"## {number}、{title}\n{title}正文。"
            for number, title in zip(numerals, titles, strict=True)
        )

        self.assertEqual(missing_bazi_sections(text), [])

    def test_normalize_removes_unsupported_relationship_risk_disclaimer(self) -> None:
        text = (
            "## 七、婚姻\n"
            "2021年关系现实化。\n"
            "现有盘面不足以支持二婚或外缘判断，本轮不展开。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertNotIn("二婚", normalized)
        self.assertNotIn("外缘", normalized)
        self.assertFalse(
            any(
                "婚姻栏" in violation
                for violation in bazi_timing_contract_violations(normalized)
            )
        )

    def test_normalize_adds_bounded_parent_health_when_evidence_is_weak(self) -> None:
        text = (
            "## 八、六亲\n"
            "父母对成长影响较深。\n"
            "父亲：2024年家宅事务增加。\n"
            "母亲：2021年操心较多。\n"
            "## 九、财富等级\n"
            "财富结构分：6/9。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("父亲：本轮未形成可靠高信号健康应期", normalized)
        self.assertIn("母亲：本轮未形成可靠高信号健康应期", normalized)
        self.assertIn("## 九、财富等级", normalized)
        self.assertFalse(
            any(
                "六亲栏" in violation
                for violation in bazi_timing_contract_violations(normalized)
            )
        )

    def test_contract_rejects_dangling_verification_event(self) -> None:
        text = (
            "十、过三关\n"
            "- 2023｜感情关系出现机会但｜"
            "流年：癸卯；大运：壬申；原局：夫妻宫被合。"
        )

        self.assertIn("过三关包含未完成的事件描述", bazi_timing_contract_violations(text))

    def test_two_strong_event_categories_are_not_rejected(self) -> None:
        text = (
            "十、过三关\n"
            "- 2018｜工作行业发生切换｜流年：戊戌；大运：壬申；原局：年支伏吟。\n"
            "- 2023｜本人接受肛肠手术｜流年：癸卯；大运：壬申；原局：病位受冲。"
        )

        self.assertEqual(past_event_timing_categories(text), 2)
        self.assertFalse(
            any("主题" in violation for violation in bazi_timing_contract_violations(text))
        )

    def test_physical_exam_is_a_concrete_verification_event(self) -> None:
        text = (
            "十、过三关\n"
            "- 2023｜体检｜推算原因：流年：癸卯；大运：壬申；原局：病位受冲。"
        )

        self.assertNotIn(
            "过三关包含栏目名称，缺少可核验的具体事件",
            bazi_timing_contract_violations(text),
        )

    def test_career_entry_and_residence_change_are_concrete_events(self) -> None:
        text = (
            "十、过三关\n"
            "- 2016｜入行｜推算原因：流年：丙申；大运：壬申；原局：月柱受合。\n"
            "- 2024｜换住处｜推算原因：流年：甲辰；大运：壬申；原局：年时柱同动。"
        )

        self.assertNotIn(
            "过三关包含栏目名称，缺少可核验的具体事件",
            bazi_timing_contract_violations(text),
        )

    def test_office_location_move_is_a_concrete_event(self) -> None:
        text = (
            "十、过三关\n"
            "- 2024｜搬动办公地点｜推算原因：流年：甲辰；大运：壬申；原局：年时柱同动。"
        )

        self.assertNotIn(
            "过三关包含栏目名称，缺少可核验的具体事件",
            bazi_timing_contract_violations(text),
        )

    def test_job_responsibility_reorganization_is_a_concrete_event(self) -> None:
        text = (
            "十、过三关\n"
            "- 2024｜岗位职责重排｜推算原因：流年：甲辰；大运：壬申；原局：年时柱同动。"
        )

        self.assertNotIn(
            "过三关包含栏目名称，缺少可核验的具体事件",
            bazi_timing_contract_violations(text),
        )

    def test_unknown_verification_wording_maps_to_concrete_category_action(self) -> None:
        text = (
            "十、过三关\n"
            "- 2024｜职业责任重新编排｜推算原因：流年：甲辰；大运：壬申；原局：年时柱同动。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("2024｜岗位调整｜", normalized)
        self.assertNotIn(
            "过三关包含栏目名称，缺少可核验的具体事件",
            bazi_timing_contract_violations(normalized),
        )

    def test_normalize_does_not_trim_health_treatment_wording(self) -> None:
        text = (
            "四、健康注意\n"
            "2006｜待核验脾胃检查、治疗或开刀经历｜"
            "流年戌冲辰；大运共同引动病位。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("检查、治疗或开刀经历", normalized)

    def test_merge_repair_never_removes_complete_sections(self) -> None:
        original = "\n".join(
            f"## {title}\n{title}正文。"
            for title in (
                "命盘",
                "原局格局喜用",
                "大运",
                "健康注意",
                "学历",
                "事业",
                "婚姻",
                "六亲",
                "财富等级",
                "过三关",
                "参考依据",
            )
        )
        repaired = "八、六亲\n修复后的六亲正文。\n十、过三关"

        merged = merge_bazi_repaired_sections(
            original,
            repaired,
            ["六亲", "过三关"],
        )

        self.assertEqual(missing_bazi_sections(merged), [])
        self.assertIn("修复后的六亲正文", merged)
        self.assertIn("过三关正文", merged)

    def test_normalized_repair_never_removes_complete_sections(self) -> None:
        original = "\n".join(
            f"## {title}\n{body}"
            for title, body in (
                ("命盘", "命盘正文。"),
                ("原局格局喜用", "格局正文。"),
                ("大运", "大运正文。"),
                ("健康注意", "检查时排除外缘环境造成的作息影响。"),
                ("学历", "学历正文。"),
                ("事业", "事业正文。"),
                ("婚姻", "婚姻正文。"),
                ("六亲", "六亲正文。"),
                ("财富等级", "财富正文。"),
                ("过三关", "2020｜工作方向出现明显变化｜流年、大运、原局同动。"),
                ("参考依据", "参考正文。"),
            )
        )
        repaired = (
            "## 过三关\n"
            "2020｜感情工作双变动｜流年：庚子；大运：壬申；原局：日月同动。"
        )

        merged = merge_bazi_repaired_sections(original, repaired, ["过三关"])
        normalized = normalize_bazi_timing_contract_text(merged)

        self.assertEqual(missing_bazi_sections(normalized), [])
        self.assertIn("排除外缘环境", normalized)
        self.assertIn("恋爱关系变化", normalized)

    def test_contract_rejects_vague_or_multi_topic_verification_events(self) -> None:
        text = (
            "十、过三关\n"
            "- 2018｜工作平台｜流年：戊戌；大运：壬申；原局：月柱受冲。\n"
            "- 2023｜感情与事业同时起波动｜流年：癸卯；大运：壬申；原局：日月同动。"
        )

        violations = bazi_timing_contract_violations(text)
        self.assertIn("过三关包含栏目名称，缺少可核验的具体事件", violations)
        self.assertIn("过三关同一行混入多个事件主题", violations)

    def test_contract_rejects_parent_identity_derived_from_annual_ten_god(self) -> None:
        text = (
            "八、六亲\n"
            "2021年父亲肺胸检查；流年辛丑，辛为偏财可作父星，年柱受刑。\n"
            "母亲本轮未形成可靠高信号健康应期。"
        )

        self.assertIn(
            "六亲栏按流年自身十神直接指定父母身份",
            bazi_timing_contract_violations(text),
        )

    def test_normalize_removes_annual_ten_god_parent_identity_claim(self) -> None:
        text = (
            "八、六亲\n"
            "- 父亲：2011｜肺胸检查｜流年辛卯、辛未运；"
            "辛金为偏财到位，可指父星，且辛克原局甲印，年柱同步受引动。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertNotIn("可指父星", normalized)
        self.assertNotIn(
            "六亲栏按流年自身十神直接指定父母身份",
            bazi_timing_contract_violations(normalized),
        )

    def test_parent_health_timing_accepts_direct_stem_control_relation(self) -> None:
        text = (
            "八、六亲\n"
            "父亲本轮未形成可靠高信号健康应期。\n"
            "2021年母亲肺胸检查待核验；流年辛丑，辛克原局甲印，大运申金助辛。"
        )

        self.assertFalse(
            any("母亲独立" in item for item in bazi_timing_contract_violations(text))
        )


if __name__ == "__main__":
    unittest.main()
