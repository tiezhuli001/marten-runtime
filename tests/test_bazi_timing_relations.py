from __future__ import annotations

import unittest

from marten_runtime.bazi.timing_relations import natal_branch_dynamics, timing_relation_facts


class BaziTimingRelationTests(unittest.TestCase):
    def test_stem_combine_control_and_repeat_are_complete(self) -> None:
        facts = timing_relation_facts(
            "己酉", moving_label="流年", natal_pillars=["甲子", "乙卯", "己午", "庚戌"]
        )

        self.assertIn("己甲合（流年干合年干）", facts.stem_relations)
        self.assertIn("乙克己（月干克流年干）", facts.stem_relations)
        self.assertIn("己伏吟日干", facts.stem_relations)

    def test_stem_relations_include_generation_and_all_hidden_stems(self) -> None:
        facts = timing_relation_facts(
            "甲午", moving_label="流年", natal_pillars=["丙子", "丁卯", "庚戌", "壬辰"]
        )

        self.assertIn("甲生丙（流年干生年干）", facts.stem_relations)
        self.assertIn("甲克戊（流年干克日支本气戊）", facts.hidden_stem_relations)
        self.assertIn("辛克甲（日支中气辛克流年干）", facts.hidden_stem_relations)
        self.assertIn("甲生丁（流年干生日支余气丁）", facts.hidden_stem_relations)
        self.assertIn("丁克庚（流年支本气丁克日干）", facts.hidden_stem_relations)
        self.assertIn("己生庚（流年支中气己生日干）", facts.hidden_stem_relations)

    def test_dayun_hidden_stems_act_on_every_natal_exposed_stem(self) -> None:
        facts = timing_relation_facts(
            "戊辰", moving_label="大运", natal_pillars=["甲子", "乙卯", "庚戌", "壬申"]
        )

        self.assertIn("戊克壬（大运支本气戊克时干）", facts.hidden_stem_relations)
        self.assertIn("乙庚合（大运支中气乙合日干）", facts.hidden_stem_relations)
        self.assertIn("庚生癸（日干生大运支余气癸）", facts.hidden_stem_relations)

    def test_every_stem_pair_is_classified_without_duplicates(self) -> None:
        stems = "甲乙丙丁戊己庚辛壬癸"
        for moving in stems:
            facts = timing_relation_facts(
                f"{moving}辰",
                moving_label="流年",
                natal_pillars=[f"{target}子" for target in stems[:4]],
            )
            self.assertEqual(len(facts.stem_relations), len(set(facts.stem_relations)))
            self.assertEqual(len(facts.hidden_stem_relations), len(set(facts.hidden_stem_relations)))

    def test_all_pair_branch_relation_families(self) -> None:
        facts = timing_relation_facts(
            "甲子",
            moving_label="流年",
            natal_pillars=["乙丑", "丙午", "丁未", "戊卯"],
            dayun_pillar="己酉",
        )
        text = "\n".join(facts.branch_relations)

        self.assertIn("子丑六合", text)
        self.assertIn("子午相冲", text)
        self.assertIn("子未相害", text)
        self.assertIn("子卯相刑", text)
        self.assertIn("子酉相破", text)

    def test_cross_layer_three_harmony_meeting_and_punishment(self) -> None:
        harmony = timing_relation_facts(
            "戊辰", moving_label="流年", natal_pillars=["甲申", "乙寅", "丙午", "丁巳"],
            dayun_pillar="庚子",
        )
        meeting = timing_relation_facts(
            "戊辰", moving_label="流年", natal_pillars=["甲寅", "乙巳", "丙申", "丁子"],
            dayun_pillar="庚卯",
        )
        punishment = timing_relation_facts(
            "戊申", moving_label="流年", natal_pillars=["甲寅", "乙子", "丙卯", "丁辰"],
            dayun_pillar="庚巳",
        )

        self.assertTrue(any("三合水局" in item for item in harmony.multi_relations))
        self.assertTrue(any("三会木局" in item for item in meeting.multi_relations))
        self.assertTrue(any("三刑·无恩之刑" in item for item in punishment.multi_relations))

        force_punishment = timing_relation_facts(
            "戊戌", moving_label="流年", natal_pillars=["甲丑", "乙子", "丙卯", "丁辰"],
            dayun_pillar="庚未",
        )
        self.assertTrue(any("三刑·恃势之刑" in item for item in force_punishment.multi_relations))

    def test_only_four_self_punishments_are_emitted(self) -> None:
        self_punishment = timing_relation_facts(
            "甲辰", moving_label="流年", natal_pillars=["乙辰", "丙巳", "丁巳", "戊子"]
        )
        repeated_only = timing_relation_facts(
            "甲巳", moving_label="流年", natal_pillars=["乙巳", "丙辰", "丁午", "戊子"]
        )

        self.assertTrue(any("辰辰自刑" in item for item in self_punishment.branch_relations))
        self.assertIn("辰伏吟年支", self_punishment.repeated_branches)
        self.assertFalse(any("巳巳自刑" in item for item in repeated_only.branch_relations))
        self.assertIn("巳伏吟年支", repeated_only.repeated_branches)

    def test_natal_six_combine_uses_exposed_transformation_stem(self) -> None:
        dynamics = natal_branch_dynamics(["甲戌", "丁卯", "庚戌", "庚辰"])

        fire_combinations = [
            item for item in dynamics["合化判定"] if item["化神"] == "火"
        ]
        self.assertEqual(len(fire_combinations), 2)
        self.assertTrue(all(item["状态"] == "合化成立" for item in fire_combinations))
        self.assertTrue(all("月干丁" in item["引化天干"] for item in fire_combinations))
        month_day = next(
            item
            for item in fire_combinations
            if {part["宫位"] for part in item["参与支"]} == {"月支", "日支"}
        )
        self.assertEqual(
            [(part["地支"], part["十神"]) for part in month_day["参与支"]],
            [("卯", "正财"), ("戌", "偏印")],
        )

    def test_three_harmony_without_exposed_transformation_stem_stays_untransformed(self) -> None:
        facts = timing_relation_facts(
            "戊辰",
            moving_label="流年",
            natal_pillars=["甲申", "乙寅", "丙午", "丁巳"],
            dayun_pillar="庚子",
        )

        water = next(
            item for item in facts.transformation_relations if item["关系"].endswith("三合水局")
        )
        self.assertEqual(water["状态"], "合化未成")
        self.assertEqual(water["引化天干"], [])

    def test_moving_stem_can_trigger_three_harmony_transformation(self) -> None:
        facts = timing_relation_facts(
            "癸辰",
            moving_label="流年",
            natal_pillars=["甲申", "乙寅", "丙午", "丁巳"],
            dayun_pillar="庚子",
        )

        water = next(
            item for item in facts.transformation_relations if item["关系"].endswith("三合水局")
        )
        self.assertEqual(water["状态"], "合化成立")
        self.assertIn("流年干癸", water["引化天干"])

    def test_clash_identifies_controlled_element_ten_god_and_palace(self) -> None:
        facts = timing_relation_facts(
            "甲酉",
            moving_label="流年",
            natal_pillars=["甲戌", "丁卯", "庚戌", "庚辰"],
        )

        clash = next(item for item in facts.impact_relations if item["关系"] in {"酉卯相冲", "卯酉相冲"})
        self.assertEqual(clash["受影响一方"][0]["地支"], "卯")
        self.assertEqual(clash["受影响一方"][0]["十神"], "正财")
        self.assertEqual(clash["受影响一方"][0]["宫位"], "月支")
