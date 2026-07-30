import unittest

from marten_runtime.evals.family_graders.bazi_agent import grade_bazi_agent_case_result
from marten_runtime.evals.grader_registry import resolve_case_grader
from marten_runtime.evals.models import EvalCaseObservation, EvalCaseSpec, EvalTurnSpec


class BaziAgentFamilyGraderTests(unittest.TestCase):
    def test_registry_and_complete_citation_path_pass(self) -> None:
        case = _case(
            {"citation_integrity": 40, "tool_order": 30, "fingerprint_consistency": 30},
            {"required_tool_order": [["bazi", "chart"], ["bazi", "dayun"], ["knowledge", "search"]]},
        )
        fingerprint = "sha256:" + "a" * 64
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="参考依据：《穷通宝鉴》·调候方法",
            tool_calls=[
                _call("bazi", "chart", {"ok": True, "inputFingerprint": fingerprint}),
                _call("bazi", "dayun", {"ok": True, "inputFingerprint": fingerprint}),
                _call("knowledge", "search", {"ok": True, "results": [{"source_id": "ksrc_1", "chunk_id": "kchk_1", "source_title": "穷通宝鉴", "heading": "调候方法"}]}),
            ],
        )

        self.assertEqual(resolve_case_grader(case).__name__, "grade_bazi_agent_case_result")
        result = grade_bazi_agent_case_result(case, observation, "eval_1")
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)

    def test_missing_chunk_citation_fails(self) -> None:
        case = _case({"citation_integrity": 100}, {})
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="只写《穷通宝鉴》，缺少篇章",
            tool_calls=[
                _call("knowledge", "search", {"ok": True, "results": [{"source_id": "ksrc_1", "chunk_id": "kchk_1", "source_title": "穷通宝鉴", "heading": "调候方法"}]})
            ],
        )

        self.assertEqual(grade_bazi_agent_case_result(case, observation, "eval_1").status, "failed")

    def test_readable_output_structure_rejects_internal_card_fields(self) -> None:
        case = _case(
            {"output_structure": 100},
            {"required_sections": ["命盘", "原局格局喜用", "大运", "事业", "过三关", "参考依据"]},
        )
        complete = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text=(
                "一、命盘\n二、原局格局喜用\n三、大运\n"
                "四、事业\n五、过三关：待核验\n六、参考依据"
            ),
        )
        leaked = complete.model_copy(
            update={"final_text": complete.final_text + ' source_id=x "wide_screen_mode": true'}
        )

        self.assertEqual(grade_bazi_agent_case_result(case, complete, "eval_1").status, "passed")
        self.assertEqual(grade_bazi_agent_case_result(case, leaked, "eval_1").status, "failed")

    def test_output_structure_rejects_question_menu(self) -> None:
        case = _case(
            {"output_structure": 100},
            {"required_sections": ["命盘", "原局格局喜用", "过三关", "参考依据"]},
        )
        base = "一、命盘\n二、原局格局喜用\n三、过三关：待核验\n四、参考依据\n"
        for forbidden in ("哪几年适合结婚", "哪步运财运更强"):
            with self.subTest(forbidden=forbidden):
                observation = EvalCaseObservation(
                    case_id=case.case_id,
                    family=case.family,
                    final_text=f"{base}{forbidden}",
                )
                result = grade_bazi_agent_case_result(case, observation, "eval_1")
                self.assertEqual(result.status, "failed")

    def test_output_structure_rejects_si_si_self_punishment(self) -> None:
        case = _case(
            {"output_structure": 100},
            {"required_sections": ["命盘", "婚姻", "参考依据"]},
        )
        base = "一、命盘\n四柱。\n二、婚姻\n%s\n三、参考依据\n《滴天髓》。"
        valid = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text=base % "巳巳伏吟落到夫妻宫，结合行运观察关系节奏。",
        )
        invalid = valid.model_copy(
            update={"final_text": base % "巳巳自刑导致关系反复。"}
        )

        self.assertEqual(
            grade_bazi_agent_case_result(case, valid, "eval_1").status,
            "passed",
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, invalid, "eval_1").status,
            "failed",
        )

    def test_output_structure_uses_headings_for_order(self) -> None:
        case = _case(
            {"output_structure": 100},
            {"required_sections": ["命盘", "原局格局喜用", "大运", "参考依据"]},
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text=(
                "工具摘要包含大运信息。\n"
                "一、命盘\n四柱。\n"
                "二、原局格局喜用\n结构。\n"
                "三、大运\n行运。\n"
                "四、参考依据\n《滴天髓》。"
            ),
        )

        self.assertEqual(
            grade_bazi_agent_case_result(case, observation, "eval_1").status,
            "passed",
        )

    def test_output_structure_can_require_year_event_and_derivation(self) -> None:
        case = _case(
            {"output_structure": 100},
            {
                "required_sections": ["命盘", "过三关", "参考依据"],
                "require_past_event_reasoning": True,
            },
        )
        complete = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text=(
                "一、命盘\n四柱。\n"
                "二、过三关\n"
                "2017（丁酉）｜待核验工作方向变化｜"
                "推算原因：流年丁酉处于甲寅大运，岁运引动原局事业宫。\n"
                "三、参考依据\n《滴天髓》。"
            ),
        )
        vague = complete.model_copy(
            update={
                "final_text": (
                    "一、命盘\n四柱。\n二、过三关\n"
                    "青年阶段可能有工作变化。\n三、参考依据\n《滴天髓》。"
                )
            }
        )

        self.assertEqual(
            grade_bazi_agent_case_result(case, complete, "eval_1").status,
            "passed",
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, vague, "eval_1").status,
            "failed",
        )

    def test_output_structure_can_require_concrete_topic_analysis(self) -> None:
        case = _case(
            {"output_structure": 100},
            {
                "required_sections": ["学历", "婚姻", "财富等级"],
                "require_concrete_topics": True,
            },
        )
        complete = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text=(
                "一、学历\n本科，2006 年升学待核验。\n"
                "二、婚姻\n2016 年为结婚窗口。\n"
                "三、财富等级\n财富结构分：6/9＝成局路径 2 + 承载 2 + 大运 3 - 制约 1。"
                "命理年收入能力区间：30-60 万；这是传统文化模型估算，不等同现实收入。"
            ),
        )
        vague = complete.model_copy(
            update={
                "final_text": (
                    "一、学历\n学习能力较好。\n二、婚姻\n感情需要经营。\n"
                    "三、财富等级\n财富取决于努力。"
                )
            }
        )

        self.assertEqual(
            grade_bazi_agent_case_result(case, complete, "eval_1").status,
            "passed",
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, vague, "eval_1").status,
            "failed",
        )

    def test_output_structure_can_require_concrete_timing_triggers(self) -> None:
        case = _case(
            {"output_structure": 100},
            {
                "required_sections": ["健康注意", "婚姻", "六亲", "过三关"],
                "require_timing_triggers": True,
            },
        )
        complete = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text=(
                "一、命盘\n地支：戌 巳 巳 辰\n"
                "二、健康注意\n2006 年待核验脾胃检查或开刀；流年丙戌冲年支辰并刑日支丑。\n"
                "三、婚姻\n2014 年甲午为桃花应期；2017 年财星作为配偶星得根并合动夫妻宫。\n"
                "四、六亲\n2006 年父亲脾胃检查；父星与年柱受流年冲动。\n"
                "2016 年母亲脾胃检查；母星与月柱受流年合冲引动。\n"
                "五、过三关\n"
                "2004｜待核验学业变化｜流年甲申处于辛未大运，引动原局印星。\n"
                "2014｜待核验重要恋爱｜流年甲午处于壬申大运，引动原局夫妻宫。\n"
                "2006｜待核验本人健康检查｜流年丙戌处于辛未大运，引动原局脾胃病位。\n"
                "2016｜待核验母亲健康波动｜流年丙申处于壬申大运，引动原局母星。"
            ),
        )
        vague = complete.model_copy(
            update={
                "final_text": (
                    "一、健康注意\n平时注意作息。\n二、婚姻\n感情有机会。\n"
                    "三、六亲\n父母注意健康。\n四、过三关\n青年阶段变化较多。"
                )
            }
        )

        self.assertEqual(
            grade_bazi_agent_case_result(case, complete, "eval_1").status,
            "passed",
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, vague, "eval_1").status,
            "failed",
        )

        missing_peach_blossom = complete.model_copy(
            update={"final_text": complete.final_text.replace("2014 年甲午为桃花应期；", "")}
        )
        merged_parent_event = complete.model_copy(
            update={
                "final_text": complete.final_text.replace(
                    "2016 年母亲脾胃检查；母星与月柱受流年合冲引动。",
                    "2016 年父母健康需要留意；月柱受流年合冲引动。",
                )
            }
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, missing_peach_blossom, "eval_1").status,
            "passed",
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, merged_parent_event, "eval_1").status,
            "passed",
        )

        wrong_peach_blossom = complete.model_copy(
            update={
                "final_text": complete.final_text.replace(
                    "2014 年甲午为桃花应期",
                    "2020 年庚子为桃花应期",
                )
            }
        )
        missing_father = complete.model_copy(
            update={
                "final_text": complete.final_text.replace(
                    "2006 年父亲脾胃检查；父星与年柱受流年冲动。\n",
                    "",
                )
            }
        )
        missing_surgery_assessment = complete.model_copy(
            update={"final_text": complete.final_text.replace("检查或开刀", "检查复诊")}
        )
        merged_verification_topics = complete.model_copy(
            update={
                "final_text": complete.final_text.replace(
                    "2014｜待核验重要恋爱｜",
                    "2014｜待核验重要恋爱且工作变化｜",
                )
            }
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, wrong_peach_blossom, "eval_1").status,
            "failed",
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, missing_father, "eval_1").status,
            "passed",
        )
        bounded_father = complete.model_copy(
            update={
                "final_text": complete.final_text.replace(
                    "2006 年父亲脾胃检查；父星与年柱受流年冲动。",
                    "父亲本轮未形成可靠的高信号健康应期。",
                )
            }
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, bounded_father, "eval_1").status,
            "passed",
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, missing_surgery_assessment, "eval_1").status,
            "passed",
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, merged_verification_topics, "eval_1").status,
            "failed",
        )

        bare_event = complete.model_copy(
            update={
                "final_text": complete.final_text.replace(
                    "2004｜待核验学业变化｜",
                    "2004｜工作｜",
                )
            }
        )
        self.assertEqual(
            grade_bazi_agent_case_result(case, bare_event, "eval_1").status,
            "failed",
        )

    def test_degradation_preserves_fact_marker_and_mismatch_stops(self) -> None:
        degraded = _case(
            {"degradation": 100},
            {"required_final_contains": ["排盘事实保留", "theory 暂不可用"]},
        )
        degraded_observation = EvalCaseObservation(
            case_id=degraded.case_id,
            family=degraded.family,
            final_text="排盘事实保留；theory 暂不可用。",
            tool_calls=[
                _call("bazi", "chart", {"ok": True, "inputFingerprint": "sha256:a"}),
                _call("knowledge", "search", {"ok": True, "results": []}),
            ],
        )
        mismatch = _case({"mismatch_stop": 100}, {"stop_marker": "停止综合解释"})
        mismatch_observation = EvalCaseObservation(
            case_id=mismatch.case_id,
            family=mismatch.family,
            final_text="fingerprint 不一致，停止综合解释。",
            tool_calls=[
                _call("bazi", "chart", {"ok": True, "inputFingerprint": "sha256:a"}),
                _call("bazi", "dayun", {"ok": True, "inputFingerprint": "sha256:b"}),
            ],
        )

        self.assertEqual(grade_bazi_agent_case_result(degraded, degraded_observation, "eval_1").status, "passed")
        self.assertEqual(grade_bazi_agent_case_result(mismatch, mismatch_observation, "eval_1").status, "passed")


def _call(tool_name: str, action: str, result: dict[str, object]) -> dict[str, object]:
    return {"tool_name": tool_name, "tool_payload": {"action": action}, "tool_result": result}


def _case(weights: dict[str, int], grader_case: dict[str, object]) -> EvalCaseSpec:
    return EvalCaseSpec(
        case_id="bazi_case",
        suite_id="bazi_agent",
        family="bazi_agent",
        grader_id="bazi_agent",
        description="bazi eval",
        agent_id="bazi",
        profile_name="openai_gpt_5_4",
        turns=[EvalTurnSpec(role="user", content="排盘")],
        component_weights=weights,
        gate_components=list(weights),
        grader_case=grader_case,
    )


if __name__ == "__main__":
    unittest.main()
