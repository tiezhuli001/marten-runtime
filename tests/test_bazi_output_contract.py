from __future__ import annotations

import json
import unittest

from marten_runtime.runtime.bazi_output_contract import (
    BaziAnalysisDraft,
    BaziVerificationEventDraft,
    bazi_analysis_response_schema,
    bind_bazi_verification_facts,
    bazi_repair_source_text,
    bazi_timing_contract_violations,
    bazi_verification_group_violations,
    deterministic_rejected_verification_event_labels,
    deterministic_verification_event_violations,
    bazi_violation_sections,
    merge_bazi_repaired_sections,
    missing_bazi_sections,
    normalize_bazi_timing_contract_text,
    normalize_bazi_verification_candidate_reasons,
    normalize_verification_event_text,
    parse_bazi_semantic_review,
    parse_bazi_verification_events_patch,
    past_event_timing_categories,
    prune_semantically_rejected_verification_events,
    render_bazi_analysis_draft,
)


class BaziOutputContractTests(unittest.TestCase):
    def test_response_schema_requires_fact_ids_instead_of_free_text_evidence(self) -> None:
        schema = bazi_analysis_response_schema()
        event_schema = schema["$defs"]["BaziVerificationEventDraft"]

        self.assertIn("fact_ids", event_schema["required"])
        self.assertNotIn("liunian_basis", event_schema["properties"])
        self.assertNotIn("dayun_basis", event_schema["properties"])
        self.assertNotIn("natal_basis", event_schema["properties"])
        self.assertNotIn("shensha_basis", event_schema["properties"])

    def test_fact_binding_drops_wrong_year_shensha_and_renders_canonical_evidence(self) -> None:
        event = BaziVerificationEventDraft.model_validate(
            {
                "year": 2022,
                "category": "self_health",
                "event": "因受伤接受医疗处理",
                "fact_ids": [
                    "year.2022.relation.0",
                    "dayun.2017.identity",
                    "natal.pillars",
                    "natal.pillar.2",
                    "year.2021.shensha.0",
                    "year.2022.shensha.0",
                ],
            }
        )
        draft = BaziAnalysisDraft.model_construct(
            chart="命盘",
            pattern_and_use="格局",
            dayun="大运",
            health="健康",
            education="学历",
            career="事业",
            marriage="婚姻",
            kinship="六亲",
            wealth="财富",
            verification_candidates=[],
            verification_events=[event],
            references=["依据"],
        )
        registry = {
            "year.2022.relation.0": {
                "id": "year.2022.relation.0",
                "layer": "liunian",
                "kind": "relation",
                "year": 2022,
                "text": "寅巳相刑",
            },
            "dayun.2017.identity": {
                "id": "dayun.2017.identity",
                "layer": "dayun",
                "kind": "identity",
                "year_start": 2017,
                "year_end": 2026,
                "text": "2017年起进入壬申大运",
            },
            "natal.pillars": {
                "id": "natal.pillars",
                "layer": "natal",
                "kind": "pillars",
                "text": "原局四柱为甲戌、己巳、丁巳、甲辰",
            },
            "natal.pillar.2": {
                "id": "natal.pillar.2",
                "layer": "natal",
                "kind": "pillar_ten_gods",
                "text": "日柱为丁巳，夫妻宫坐劫财",
            },
            "year.2021.shensha.0": {
                "id": "year.2021.shensha.0",
                "layer": "shensha",
                "kind": "shensha",
                "year": 2021,
                "text": "流霞",
            },
            "year.2022.shensha.0": {
                "id": "year.2022.shensha.0",
                "layer": "shensha",
                "kind": "shensha",
                "year": 2022,
                "text": "血刃",
            },
        }

        bound, violations = bind_bazi_verification_facts(draft, registry)
        bound_event = bound.verification_events[0]

        self.assertEqual(violations, ())
        self.assertEqual(bound_event.liunian_basis, "寅巳相刑")
        self.assertEqual(bound_event.shensha_basis, "血刃")
        self.assertNotIn("year.2021.shensha.0", bound_event.fact_ids)

    def test_fact_binding_reports_only_missing_verification_layer(self) -> None:
        event = BaziVerificationEventDraft.model_validate(
            {
                "year": 2022,
                "category": "self_health",
                "event": "因受伤接受医疗处理",
                "fact_ids": ["year.2022.relation.0"],
            }
        )
        draft = BaziAnalysisDraft.model_construct(
            chart="命盘",
            pattern_and_use="格局",
            dayun="大运",
            health="健康",
            education="学历",
            career="事业",
            marriage="婚姻",
            kinship="六亲",
            wealth="财富",
            verification_candidates=[],
            verification_events=[event],
            references=["依据"],
        )
        registry = {
            "year.2022.relation.0": {
                "id": "year.2022.relation.0",
                "layer": "liunian",
                "kind": "relation",
                "year": 2022,
                "text": "寅巳相刑",
            }
        }

        _, violations = bind_bazi_verification_facts(draft, registry)

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].scope, "verification")
        self.assertEqual(violations[0].repair_strategy, "verification_patch")
        self.assertIn("dayun,natal", violations[0].message)

    def test_fact_binding_rejects_empty_fact_ids(self) -> None:
        event = BaziVerificationEventDraft.model_validate(
            {
                "year": 2022,
                "category": "self_health",
                "event": "因受伤接受医疗处理",
                "fact_ids": [],
            }
        )
        draft = BaziAnalysisDraft.model_construct(
            chart="命盘", pattern_and_use="格局", dayun="大运", health="健康",
            education="学历", career="事业", marriage="婚姻", kinship="六亲",
            wealth="财富", verification_candidates=[], verification_events=[event],
            references=["依据"],
        )

        _, violations = bind_bazi_verification_facts(
            draft,
            {
                "natal.pillar.2": {
                    "id": "natal.pillar.2", "layer": "natal",
                    "kind": "pillar_ten_gods", "text": "日柱为丁巳",
                }
            },
        )

        self.assertEqual(len(violations), 1)
        self.assertIn("liunian,dayun,natal", violations[0].message)

    def test_relationship_fact_binding_requires_spouse_palace_fact(self) -> None:
        event = BaziVerificationEventDraft.model_validate(
            {
                "year": 2019,
                "category": "relationship",
                "event": "感情关系发生明显变动",
                "fact_ids": [
                    "year.2019.relation.0",
                    "dayun.2016.identity",
                    "natal.relation.0",
                ],
            }
        )
        draft = BaziAnalysisDraft.model_construct(
            chart="命盘", pattern_and_use="格局", dayun="大运", health="健康",
            education="学历", career="事业", marriage="婚姻", kinship="六亲",
            wealth="财富", verification_candidates=[], verification_events=[event],
            references=["依据"],
        )
        registry = {
            "year.2019.relation.0": {
                "layer": "liunian", "kind": "relation", "year": 2019,
                "text": "亥巳相冲",
            },
            "dayun.2016.identity": {
                "layer": "dayun", "kind": "identity", "year_start": 2016,
                "year_end": 2025, "text": "壬申大运",
            },
            "natal.relation.0": {
                "layer": "natal", "kind": "relation", "text": "原局关系",
            },
        }

        _, violations = bind_bazi_verification_facts(draft, registry)

        self.assertEqual(len(violations), 1)
        self.assertEqual(
            violations[0].code,
            "verification_relationship_spouse_palace_required",
        )

    def test_structured_draft_renders_all_eleven_sections(self) -> None:
        draft = BaziAnalysisDraft.model_validate(
            {
                "chart": "四柱排盘事实。",
                "pattern_and_use": "格局与喜用判断。",
                "dayun": "大运分析正文。",
                "health": "健康传统取象。",
                "education": "学历分析正文。",
                "career": "事业分析正文。",
                "marriage": "婚姻分析正文。",
                "kinship": "六亲分析正文。",
                "wealth": "财富结构分析。",
                "verification_candidates": [
                    {
                        "category": category,
                        "year": year,
                        "event": event,
                        "confidence": confidence,
                        "evidence_summary": "原局大运流年三层证据摘要。",
                        "discard_reason": discard_reason,
                    }
                    for category, year, event, confidence, discard_reason in (
                        ("self_health", 2015, "完成一次手术", 86, ""),
                        ("career_change", 2018, "正式入职", 88, ""),
                        ("relationship", 2020, "结束恋爱关系", 84, ""),
                        ("wealth_change", 2024, "获得一笔重大收益", 80, ""),
                        ("family", 2012, "父亲完成一次住院治疗", 42, "证据不足未进入最终事件"),
                    )
                ],
                "verification_events": [
                    {
                        "year": year,
                        "category": category,
                        "event": event,
                        "liunian_basis": "流年干支作用明确。",
                        "dayun_basis": "所在大运提供阶段背景。",
                        "natal_basis": "原局宫位关系被引动。",
                        "shensha_basis": "",
                    }
                    for year, category, event in (
                        (2024, "wealth_change", "获得一笔重大收益"),
                        (2015, "self_health", "完成一次手术"),
                        (2018, "career_change", "正式入职"),
                        (2020, "relationship", "结束恋爱关系"),
                    )
                ],
                "references": ["《子平真诠》·论用神"],
            }
        )

        rendered = render_bazi_analysis_draft(draft)

        self.assertEqual(missing_bazi_sections(rendered), [])
        self.assertIn("2018年｜正式入职｜流年：", rendered)
        self.assertNotIn("- 1.", rendered)
        self.assertNotIn("- 2.", rendered)
        self.assertNotIn("。；", rendered)
        self.assertNotIn("。。", rendered)
        self.assertEqual(rendered.count("## 十一、参考依据"), 1)
        self.assertLess(rendered.index("2015年｜"), rendered.index("2018年｜"))
        self.assertLess(rendered.index("2018年｜"), rendered.index("2020年｜"))
        self.assertLess(rendered.index("2020年｜"), rendered.index("2024年｜"))

    def test_verification_event_patch_parser_rejects_other_fields(self) -> None:
        selected = (
            ("self_health", 2015, "完成一次手术"),
            ("career_change", 2018, "正式入职"),
            ("relationship", 2020, "结束恋爱关系"),
            ("wealth_change", 2024, "获得重大收益"),
        )
        valid = json.dumps(
            {
                "verification_candidates": [
                    *[
                        {
                            "category": category,
                            "year": year,
                            "event": event,
                            "confidence": 80,
                            "evidence_summary": "原局大运流年三层证据摘要",
                            "discard_reason": "",
                        }
                        for category, year, event in selected
                    ],
                    {
                        "category": "family",
                        "year": 2012,
                        "event": "父亲完成一次住院治疗",
                        "confidence": 40,
                        "evidence_summary": "六亲候选证据不足",
                        "discard_reason": "证据不足未进入最终事件",
                    },
                ],
                "verification_events": [
                    {
                        "year": year,
                        "category": category,
                        "event": event,
                        "liunian_basis": "流年干支作用明确",
                        "dayun_basis": "所在大运提供阶段背景",
                        "natal_basis": "原局宫位关系被引动",
                        "shensha_basis": "",
                    }
                    for category, year, event in selected
                ],
            },
            ensure_ascii=False,
        )

        self.assertIsNotNone(parse_bazi_verification_events_patch(valid))
        self.assertIsNone(
            parse_bazi_verification_events_patch(
                valid[:-1] + ',"career":"不得改动"}'
            )
        )
        self.assertIsNone(
            parse_bazi_verification_events_patch(
                valid.replace("完成一次手术", "完成手术、住院", 1)
            )
        )
        normalized = parse_bazi_verification_events_patch(
            valid.replace(
                '"event": "正式入职"',
                '"event": "2018年正式入职且结果落定"',
            )
        )
        self.assertIsNotNone(normalized)
        self.assertEqual(
            next(
                item.event
                for item in normalized.verification_events
                if item.category == "career_change"
            ),
            "正式入职",
        )
        self.assertEqual(
            next(
                item.event
                for item in normalized.verification_candidates
                if item.category == "career_change"
            ),
            "正式入职",
        )

    def test_verification_group_keeps_only_one_year_per_candidate_column(self) -> None:
        def event(year: int, category: str, description: str) -> dict[str, object]:
            return {
                "year": year,
                "category": category,
                "event": description,
                "liunian_basis": "流年干支作用明确",
                "dayun_basis": "所在大运提供阶段背景",
                "natal_basis": "原局宫位关系被引动",
                "shensha_basis": "",
            }

        concentrated = BaziAnalysisDraft.model_validate(
            {
                "chart": "四柱排盘事实。",
                "pattern_and_use": "格局与喜用判断。",
                "dayun": "大运分析正文。",
                "health": "健康传统取象。",
                "education": "学历分析正文。",
                "career": "事业分析正文。",
                "marriage": "婚姻分析正文。",
                "kinship": "六亲分析正文。",
                "wealth": "财富结构分析。",
                "verification_candidates": [
                    {
                        "category": category,
                        "year": year,
                        "event": description,
                        "confidence": confidence,
                        "evidence_summary": "原局大运流年三层证据摘要",
                        "discard_reason": discard_reason,
                    }
                    for category, year, description, confidence, discard_reason in (
                        ("career_change", 2012, "正式入职", 90, ""),
                        ("career_change", 2017, "离开原单位", 80, ""),
                        ("career_change", 2019, "完成一次升职", 70, ""),
                        ("relationship", 2020, "结束恋爱关系", 85, ""),
                        ("wealth_change", 2024, "获得重大收益", 75, ""),
                        ("self_health", 2015, "完成一次手术", 40, "证据不足"),
                        ("family", 2016, "父亲完成一次住院治疗", 35, "证据不足"),
                    )
                ],
                "verification_events": [
                    event(2012, "career_change", "正式入职"),
                    event(2017, "career_change", "离开原单位"),
                    event(2019, "career_change", "完成一次升职"),
                    event(2020, "relationship", "结束恋爱关系"),
                    event(2024, "wealth_change", "获得重大收益"),
                ],
                "references": ["《子平真诠》·论用神"],
            }
        )
        self.assertEqual(
            len(
                bazi_verification_group_violations(
                    concentrated.verification_candidates,
                    concentrated.verification_events,
                )
            ),
            2,
        )

        diverse = concentrated.model_copy(
            update={
                "verification_candidates": [
                    candidate
                    for candidate in concentrated.verification_candidates
                    if not (candidate.category == "career_change" and candidate.year == 2019)
                ],
                "verification_events": [
                    event
                    for event in concentrated.verification_events
                    if not (event.category == "career_change" and event.year == 2019)
                ],
            }
        )
        self.assertEqual(
            bazi_verification_group_violations(
                diverse.verification_candidates,
                diverse.verification_events,
            ),
            [],
        )

        lower_ranked = diverse.model_copy(
            update={
                "verification_candidates": [
                    candidate.model_copy(update={"discard_reason": "错误舍弃高分候选"})
                    if candidate.category == "career_change" and candidate.year == 2012
                    else candidate
                    for candidate in diverse.verification_candidates
                ],
                "verification_events": [
                    event
                    for event in diverse.verification_events
                    if not (event.category == "career_change" and event.year == 2012)
                ],
            }
        )
        self.assertIn(
            "过三关 career_change 栏目未选择可信度最高的一至两条候选",
            bazi_verification_group_violations(
                lower_ranked.verification_candidates,
                lower_ranked.verification_events,
            ),
        )
        normalized_candidates = normalize_bazi_verification_candidate_reasons(
            lower_ranked.verification_candidates,
            lower_ranked.verification_events,
        )
        self.assertIn(
            "过三关 career_change 栏目未选择可信度最高的一至两条候选",
            bazi_verification_group_violations(
                normalized_candidates,
                lower_ranked.verification_events,
            ),
        )

    def test_verification_group_selects_credible_events_per_category(self) -> None:
        categories = (
            ("relationship", 2023, "与对象确定恋爱关系", 90),
            ("self_health", 2015, "本人接受一次治疗", 85),
            ("family", 2024, "父亲完成一次住院治疗", 69),
            ("career_change", 2017, "本人正式入职", 88),
            ("wealth_change", 2020, "本人承担一笔重大损失", 80),
        )
        candidates = [
            {
                "category": category,
                "year": year,
                "event": event,
                "confidence": confidence,
                "evidence_summary": "原局大运流年三层证据摘要",
                "discard_reason": "可信度低于入选阈值" if confidence < 70 else "",
            }
            for category, year, event, confidence in categories
        ]
        events = [
            {
                "year": year,
                "category": category,
                "event": event,
                "liunian_basis": "流年依据",
                "dayun_basis": "大运依据",
                "natal_basis": "原局依据",
                "shensha_basis": "",
            }
            for category, year, event, confidence in categories
            if confidence >= 70
        ]
        draft = BaziAnalysisDraft.model_validate(
            {
                "chart": "四柱排盘事实。",
                "pattern_and_use": "格局与喜用判断。",
                "dayun": "大运分析正文。",
                "health": "健康传统取象。",
                "education": "学历分析正文。",
                "career": "事业分析正文。",
                "marriage": "婚姻分析正文。",
                "kinship": "六亲分析正文。",
                "wealth": "财富结构分析。",
                "verification_candidates": candidates,
                "verification_events": events,
                "references": ["《子平真诠》·论用神"],
            }
        )

        self.assertEqual(
            bazi_verification_group_violations(
                draft.verification_candidates,
                draft.verification_events,
            ),
            [],
        )

        missing_relationship = [
            event for event in draft.verification_events if event.category != "relationship"
        ]
        normalized = normalize_bazi_verification_candidate_reasons(
            draft.verification_candidates,
            missing_relationship,
        )
        self.assertIn(
            "过三关 relationship 栏目存在可信度达标候选但未选择事件",
            bazi_verification_group_violations(normalized, missing_relationship),
        )

        family_candidate = next(
            candidate for candidate in draft.verification_candidates if candidate.category == "family"
        )
        low_confidence_selected = [
            *draft.verification_events,
            BaziVerificationEventDraft.model_validate(
                {
                    "year": family_candidate.year,
                    "category": family_candidate.category,
                    "event": family_candidate.event,
                    "liunian_basis": "流年依据",
                    "dayun_basis": "大运依据",
                    "natal_basis": "原局依据",
                    "shensha_basis": "",
                }
            ),
        ]
        normalized = normalize_bazi_verification_candidate_reasons(
            draft.verification_candidates,
            low_confidence_selected,
        )
        self.assertIn(
            "过三关 family 栏目候选均低于可信度阈值，不应选择事件",
            bazi_verification_group_violations(normalized, low_confidence_selected),
        )
        self.assertIn(
            "过三关最终事件包含重复的栏目年份事件",
            bazi_verification_group_violations(
                draft.verification_candidates,
                [*draft.verification_events, draft.verification_events[0]],
            ),
        )

    def test_semantic_review_parser_accepts_plain_or_fenced_json(self) -> None:
        self.assertTrue(
            parse_bazi_semantic_review(
                '{"passed":true,"violations":[]}'
            ).passed
        )
        failed = parse_bazi_semantic_review(
            '```json\n{"passed":false,"violations":['
            '{"event":"合作失衡事件","reason":"缺少具体动作和结果"}]}\n```'
        )
        self.assertFalse(failed.passed)
        self.assertEqual(
            failed.violations,
            ("合作失衡事件：缺少具体动作和结果",),
        )
        self.assertEqual(failed.rejected_events, ("合作失衡事件",))

    def test_semantic_rejection_prunes_only_uniquely_matched_events(self) -> None:
        draft = BaziAnalysisDraft.model_validate(
            {
                "chart": "四柱排盘事实。",
                "pattern_and_use": "格局与喜用判断。",
                "dayun": "大运分析正文。",
                "health": "健康传统取象。",
                "education": "学历分析正文。",
                "career": "事业分析正文。",
                "marriage": "婚姻分析正文。",
                "kinship": "六亲分析正文。",
                "wealth": "财富结构分析。",
                "verification_candidates": [
                    {
                        "category": category,
                        "year": year,
                        "event": event,
                        "confidence": 80,
                        "evidence_summary": "三层证据摘要",
                        "discard_reason": "",
                    }
                    for category, year, event in (
                        ("relationship", 2023, "与对象确定恋爱关系"),
                        ("self_health", 2015, "本人接受一次治疗"),
                        ("family", 2024, "父亲完成一次住院治疗"),
                        ("career_change", 2017, "本人正式入职"),
                        ("wealth_change", 2020, "本人承担一笔重大损失"),
                    )
                ],
                "verification_events": [
                    {
                        "year": year,
                        "category": category,
                        "event": event,
                        "liunian_basis": "流年依据",
                        "dayun_basis": "大运依据",
                        "natal_basis": "原局依据",
                        "shensha_basis": "",
                    }
                    for category, year, event in (
                        ("relationship", 2023, "与对象确定恋爱关系"),
                        ("self_health", 2015, "本人接受一次治疗"),
                        ("family", 2024, "父亲完成一次住院治疗"),
                        ("career_change", 2017, "本人正式入职"),
                        ("wealth_change", 2020, "本人承担一笔重大损失"),
                    )
                ],
                "references": ["《子平真诠》·论用神"],
            }
        )

        pruned = prune_semantically_rejected_verification_events(
            draft,
            (
                "1. 2023年｜与对象确定恋爱关系",
                "3. 2024年｜父亲完成一次住院治疗",
            ),
        )

        self.assertIsNone(pruned)

        invalid_events = [
            event.model_copy(update={"event": "本人接受治疗或住院"})
            if event.category == "self_health"
            else event.model_copy(update={"liunian_basis": "月支直接合日干"})
            if event.category == "family"
            else event
            for event in draft.verification_events
        ]
        self.assertEqual(
            deterministic_rejected_verification_event_labels(invalid_events),
            (
                "2015年｜本人接受治疗或住院",
                "2024年｜父亲完成一次住院治疗",
            ),
        )

    def test_candidate_reason_normalization_only_fills_structural_metadata(self) -> None:
        draft = BaziAnalysisDraft.model_validate(
            {
                "chart": "四柱排盘事实。",
                "pattern_and_use": "格局与喜用判断。",
                "dayun": "大运分析正文。",
                "health": "健康传统取象。",
                "education": "学历分析正文。",
                "career": "事业分析正文。",
                "marriage": "婚姻分析正文。",
                "kinship": "六亲分析正文。",
                "wealth": "财富结构分析。",
                "verification_candidates": [
                    {
                        "category": category,
                        "year": year,
                        "event": event,
                        "confidence": confidence,
                        "evidence_summary": "三层证据摘要",
                        "discard_reason": reason,
                    }
                    for category, year, event, confidence, reason in (
                        ("relationship", 2023, "与对象结束恋爱关系", 90, "误填理由"),
                        ("relationship", 2019, "与对象确定恋爱关系", 70, ""),
                        ("self_health", 2015, "本人接受一次治疗", 85, ""),
                        ("family", 2024, "父亲完成一次住院治疗", 50, "模型给出的证据不足"),
                        ("career_change", 2017, "本人正式入职", 88, ""),
                        ("wealth_change", 2020, "本人承担一笔重大损失", 45, ""),
                    )
                ],
                "verification_events": [
                    {
                        "year": year,
                        "category": category,
                        "event": event,
                        "liunian_basis": "流年依据",
                        "dayun_basis": "大运依据",
                        "natal_basis": "原局依据",
                        "shensha_basis": "",
                    }
                    for category, year, event in (
                        ("relationship", 2023, "与对象结束恋爱关系"),
                        ("self_health", 2015, "本人接受一次治疗"),
                        ("career_change", 2017, "本人正式入职"),
                    )
                ],
                "references": ["《子平真诠》·论用神"],
            }
        )

        normalized = normalize_bazi_verification_candidate_reasons(
            draft.verification_candidates,
            draft.verification_events,
        )
        reasons = {(item.category, item.year): item.discard_reason for item in normalized}

        self.assertEqual(reasons[("relationship", 2023)], "")
        self.assertEqual(reasons[("relationship", 2019)], "同列可信度排序较低")
        self.assertEqual(reasons[("family", 2024)], "可信度低于入选阈值")
        self.assertEqual(reasons[("wealth_change", 2020)], "可信度低于入选阈值")

    def test_semantic_review_parser_fails_closed_on_invalid_payload(self) -> None:
        review = parse_bazi_semantic_review("看起来没有问题")

        self.assertFalse(review.passed)
        self.assertEqual(review.violations, ("语义审查响应无法解析",))

    def test_deterministic_event_violations_identify_exact_repair_targets(self) -> None:
        event = BaziVerificationEventDraft.model_validate(
            {
                "year": 2023,
                "category": "relationship",
                "event": "婚恋",
                "liunian_basis": "癸卯流年支卯与日支戌六合",
                "dayun_basis": "庚午大运为比肩运",
                "natal_basis": "日支戌为夫妻宫",
                "shensha_basis": "",
            }
        )

        violations = deterministic_verification_event_violations(
            [event]
        )

        self.assertEqual(
            violations,
            ("过三关事件 2023年｜婚恋：事件字段只是栏目名称或模糊主题",),
        )
        self.assertEqual(
            deterministic_rejected_verification_event_labels(
                [event]
            ),
            ("2023年｜婚恋",),
        )

    def test_semantic_review_parser_accepts_json_surrounded_by_provider_text(self) -> None:
        review = parse_bazi_semantic_review(
            '审查结果如下：\n{"passed":true,"violations":[]}\n请以此为准。'
        )

        self.assertTrue(review.passed)
        self.assertEqual(review.violations, ())

    def test_normalize_does_not_rewrite_model_wealth_reasoning(self) -> None:
        text = (
            "九、财富等级\n"
            "财富结构分：6/9＝成局路径 2 + 承载 2 + 大运 3 - 制约 1。\n"
            "命理年收入能力区间：30-60 万；这是传统文化模型估算，不等同现实收入。\n"
            "十、过三关\n- 2024｜搬家｜推算原因：流年：甲辰；大运：庚午；原局：辰戌冲。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("财富结构分：6/9", normalized)
        self.assertIn("命理年收入能力区间：30-60 万", normalized)
        self.assertFalse(
            any("财富栏" in item for item in bazi_timing_contract_violations(normalized))
        )

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

    def test_wealth_accepts_bazi_income_estimate_without_baseline(self) -> None:
        text = (
            "九、财富等级\n"
            "财富结构分：6/9；成局路径 2 + 承载 2 + 大运 3 - 制约 1。"
            "命理年收入能力区间：30-60 万元；这是文化模型估算，不等同现实收入。"
        )

        self.assertFalse(
            any("财富栏" in item for item in bazi_timing_contract_violations(text))
        )

    def test_wealth_accepts_qualitative_analysis_without_baseline(self) -> None:
        text = (
            "九、财富等级\n"
            "原局有财官流通路径，更适合依靠专业能力与平台积累；"
            "未提供现实收入、资产和负债，不估算金额。"
        )

        self.assertIn(
            "财富栏缺少多路径结构评分与命理年收入能力区间",
            bazi_timing_contract_violations(text),
        )

    def test_wealth_does_not_treat_markdown_bold_as_multiplication(self) -> None:
        text = (
            "九、财富等级\n"
            "财富更适合靠**主业能力**与长期积累；未提供现实收入，不估算金额。"
        )

        violations = bazi_timing_contract_violations(text)

        self.assertIn(
            "财富栏缺少多路径结构评分与命理年收入能力区间",
            violations,
        )
        self.assertNotIn(
            "财富栏使用了用户未提供的现实收入或资产基线",
            violations,
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

    def test_negated_peach_blossom_year_is_not_treated_as_claim(self) -> None:
        text = (
            "一、命盘\n地支：戌 卯 戌 辰\n"
            "七、婚姻\n2023年癸卯为桃花应期。"
            "2025年乙巳仍可推进关系，但不单独作为桃花年判断。"
        )

        self.assertFalse(
            any("桃花流年" in item for item in bazi_timing_contract_violations(text))
        )

    def test_rejects_denial_of_existing_spouse_palace_clash(self) -> None:
        text = (
            "一、命盘\n地支：戌 卯 戌 辰\n"
            "七、婚姻\n日支不是夫妻宫受重冲型，所以关系结构稳定。"
        )

        self.assertIn(
            "婚姻栏否认原局已经存在的夫妻宫相冲",
            bazi_timing_contract_violations(text),
        )

    def test_does_not_require_shensha_when_model_does_not_use_it(self) -> None:
        text = "十、过三关\n- 2024｜搬家｜流年甲辰冲原局戌。"

        self.assertFalse(
            any(
                "神煞" in violation
                for violation in bazi_timing_contract_violations(
                    text,
                    expected_shensha_years=((2017, "羊刃"), (2024, "流霞")),
                )
            )
        )

    def test_requires_exact_year_and_shensha_pair(self) -> None:
        text = (
            "十、过三关\n"
            "- 2017｜入职｜流霞仅作辅助。\n"
            "- 2024｜搬家｜如见流霞可作辅助。"
        )

        violations = bazi_timing_contract_violations(
            text,
            expected_shensha_years=((2017, "羊刃"), (2024, "流霞")),
        )

        self.assertIn("过三关流年神煞与已计算年份不一致", violations)
        accepted = bazi_timing_contract_violations(
            "十、过三关\n- 2024｜搬家｜流霞仅作辅助，主因仍是辰戌冲。",
            expected_shensha_years=((2017, "羊刃"), (2024, "流霞")),
        )
        self.assertFalse(
            any(
                "神煞" in violation
                for violation in accepted
            )
        )

        non_verification = bazi_timing_contract_violations(
            "四、健康注意\n2017年见流霞，注意外伤。",
            expected_shensha_years=((2017, "羊刃"), (2024, "流霞")),
        )
        self.assertIn("正文中的流年神煞与已计算年份不一致", non_verification)

    def test_normalize_verification_event_text_removes_dangling_conjunction(self) -> None:
        self.assertEqual(
            normalize_verification_event_text("感情关系出现机会但"),
            "感情关系出现机会",
        )

    def test_normalize_contract_text_preserves_model_event_wording(self) -> None:
        text = (
            "十、过三关\n"
            "- **2012｜升学或离家求学｜流年：壬辰；大运：辛未；原局：年时柱同动。**\n"
            "- **2018｜工作平台｜流年：戊戌；大运：壬申；原局：月柱受冲。**"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("2012｜升学或离家求学｜", normalized)
        self.assertIn("2018｜工作平台｜", normalized)
        violations = bazi_timing_contract_violations(normalized)
        self.assertIn("过三关包含栏目名称，缺少可核验的具体事件", violations)
        self.assertIn("过三关同一行混入多个事件主题", violations)

    def test_normalize_does_not_choose_between_multiple_model_events(self) -> None:
        text = (
            "十、过三关\n"
            "- 2012｜搬家、换学校｜流年：壬辰；大运：己巳；原局：辰戌冲。\n"
            "- 2017｜入职、转岗｜流年：丁酉；大运：庚午；原局：酉冲卯。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("2012｜搬家、换学校｜", normalized)
        self.assertIn("2017｜入职、转岗｜", normalized)

    def test_normalize_does_not_add_spouse_palace_reasoning(self) -> None:
        text = (
            "一、命盘\n地支：戌 卯 戌 辰\n"
            "七、婚姻\n卯戌相合，感情需要现实筛选。\n"
            "八、六亲\n六亲正文。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertEqual(normalized, text)

    def test_normalize_contract_text_preserves_and_rejects_multi_topic_event(self) -> None:
        text = (
            "十、过三关\n"
            "- 2020｜感情工作双变动｜流年：庚子；大运：壬申；原局：日月同动。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("2020｜感情工作双变动｜", normalized)
        self.assertIn(
            "过三关同一行混入多个事件主题",
            bazi_timing_contract_violations(normalized),
        )

    def test_normalize_does_not_rewrite_relationship_risk_reasoning(self) -> None:
        text = (
            "四、健康注意\n"
            "检查时也要排除外缘环境造成的作息影响。\n"
            "七、婚姻\n"
            "此盘不足以直接论二婚或外缘。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("排除外缘环境", normalized)
        self.assertIn("不足以直接论二婚", normalized)
        self.assertIn(
            "婚姻栏在无明确风险结论时仍讨论二婚",
            bazi_timing_contract_violations(normalized),
        )

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

    def test_normalize_preserves_unsupported_relationship_risk_disclaimer(self) -> None:
        text = (
            "## 七、婚姻\n"
            "2021年关系现实化。\n"
            "现有盘面不足以支持二婚或外缘判断，本轮不展开。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("二婚", normalized)
        self.assertIn("外缘", normalized)
        self.assertIn(
            "婚姻栏在无明确风险结论时仍讨论二婚",
            bazi_timing_contract_violations(normalized),
        )

    def test_normalize_does_not_add_parent_health_reasoning(self) -> None:
        text = (
            "## 八、六亲\n"
            "父母对成长影响较深。\n"
            "父亲：2024年家宅事务增加。\n"
            "母亲：2021年操心较多。\n"
            "## 九、财富等级\n"
            "财富结构分：6/9。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertNotIn("本轮未形成可靠高信号健康应期", normalized)
        self.assertIn("父亲：2024年家宅事务增加", normalized)
        self.assertIn("母亲：2021年操心较多", normalized)
        self.assertIn("## 九、财富等级", normalized)

    def test_contract_rejects_dangling_verification_event(self) -> None:
        text = (
            "十、过三关\n"
            "- 2023｜感情关系出现机会但｜"
            "流年：癸卯；大运：壬申；原局：夫妻宫被合。"
        )

        self.assertIn("过三关包含未完成的事件描述", bazi_timing_contract_violations(text))

    def test_contract_rejects_branch_relation_claimed_against_day_stem(self) -> None:
        text = (
            "十、过三关\n"
            "- 2023｜确定恋爱关系｜流年：卯戌六合牵动日支并合日干庚；"
            "大运：庚午运提供阶段背景；原局：财星居月令。"
        )

        self.assertIn(
            "过三关将地支关系误写成与日干直接作用",
            bazi_timing_contract_violations(text),
        )

    def test_contract_allows_relationship_preposition_in_single_event(self) -> None:
        text = (
            "十、过三关\n"
            "- 2023｜与特定对象结束恋爱关系｜"
            "流年：癸卯；大运：庚午；原局：夫妻宫被引动。"
        )

        self.assertNotIn(
            "过三关同一行混入多个事件主题",
            bazi_timing_contract_violations(text),
        )

    def test_contract_allows_bounded_relationship_change_without_inventing_direction(self) -> None:
        event = BaziVerificationEventDraft.model_validate(
            {
                "year": 2019,
                "category": "relationship",
                "event": "感情关系发生明显变动",
                "liunian_basis": "流年亥冲日支巳",
                "dayun_basis": "壬申大运引动日支巳",
                "natal_basis": "日柱为丁巳",
                "shensha_basis": "天喜",
            }
        )

        self.assertEqual(deterministic_verification_event_violations([event]), ())

    def test_contract_treats_relative_career_as_single_family_event(self) -> None:
        text = (
            "十、过三关\n"
            "- 2012｜父亲更换工作单位｜"
            "流年：壬辰；大运：己巳；原局：父星与年柱同动。"
        )

        self.assertNotIn(
            "过三关同一行混入多个事件主题",
            bazi_timing_contract_violations(text),
        )

    def test_contract_does_not_join_separate_branch_and_stem_relations(self) -> None:
        text = (
            "十、过三关\n"
            "- 2023｜与特定对象结束恋爱关系｜"
            "流年：卯与日支戌六合；大运：运干庚伏吟日干；原局：财星当令。"
        )

        self.assertNotIn(
            "过三关将地支关系误写成与日干直接作用",
            bazi_timing_contract_violations(text),
        )

    def test_contract_rejects_unstructured_verification_event(self) -> None:
        text = (
            "十、过三关\n"
            "- **2024 甲辰**：岗位、合作与家宅可能同时变化，辰戌冲。"
        )

        self.assertIn(
            "过三关缺少年份、单一事件与事实依据的分隔结构",
            bazi_timing_contract_violations(text),
        )

    def test_contract_rejects_multiple_options_inside_event_field(self) -> None:
        text = (
            "十、过三关\n"
            "- 2024｜岗位调整、居所变化或合作重组｜流年甲辰；大运庚午；原局辰戌冲。"
        )

        self.assertIn(
            "过三关同一行混入多个事件主题",
            bazi_timing_contract_violations(text),
        )

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

    def test_unknown_verification_wording_is_preserved_for_model_reasoning(self) -> None:
        text = (
            "十、过三关\n"
            "- 2024｜职业责任重新编排｜推算原因：流年：甲辰；大运：壬申；原局：年时柱同动。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("2024｜职业责任重新编排｜", normalized)
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
        self.assertIn("感情工作双变动", normalized)

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

    def test_normalize_preserves_but_contract_rejects_annual_parent_identity_claim(self) -> None:
        text = (
            "八、六亲\n"
            "- 父亲：2011｜肺胸检查｜流年辛卯、辛未运；"
            "辛金为偏财到位，可指父星，且辛克原局甲印，年柱同步受引动。"
        )

        normalized = normalize_bazi_timing_contract_text(text)

        self.assertIn("可指父星", normalized)
        self.assertIn(
            "六亲栏按流年自身十神直接指定父母身份",
            bazi_timing_contract_violations(normalized),
        )

    def test_parent_reasoning_is_not_subject_to_removed_health_template(self) -> None:
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
