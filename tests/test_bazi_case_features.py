from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from marten_runtime.bazi_cases.features import extract_chart_features
from marten_runtime.bazi_cases.sqlite_store import SQLiteBaziCaseStore
from marten_runtime.bazi_cases.text_parser import parse_case_text


class BaziCaseFeatureTests(unittest.TestCase):
    def test_extracts_real_object_chart_and_profiles(self) -> None:
        payload = {
            "result": {
                "四柱": [
                    {"柱": "年柱", "干支": "戊辰", "藏干": [{"天干": "戊", "气性": "本气"}]},
                    {"柱": "月柱", "干支": "甲寅"},
                    {"柱": "日柱", "干支": "辛丑"},
                    {"柱": "时柱", "干支": "戊子"},
                ],
                "基本信息": {"日主": "辛", "性别": "男"},
            },
            "relatedResults": {
                "dayun": {"大运列表": [{"干支": "壬申", "起运年份": 2020, "起运年龄": 6}]}
            },
        }

        features = extract_chart_features(payload, reference_year=2026)

        self.assertEqual(features["pillars"], ["戊辰", "甲寅", "辛丑", "戊子"])
        self.assertEqual(features["day_master"], "辛")
        self.assertAlmostEqual(sum(features["element_profile"].values()), 1.0, places=5)
        self.assertAlmostEqual(sum(features["ten_god_profile"].values()), 1.0, places=5)
        self.assertEqual(features["active_dayun"]["ganzhi"], "壬申")

    def test_v1_database_is_migrated_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.sqlite3"
            with sqlite3.connect(path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE bazi_cases (
                        case_id TEXT PRIMARY KEY, owner_key TEXT NOT NULL, schema_version TEXT NOT NULL,
                        case_version INTEGER NOT NULL, status TEXT NOT NULL, visibility TEXT NOT NULL,
                        source_type TEXT NOT NULL, source_run_id TEXT NOT NULL, source_session_id TEXT NOT NULL,
                        input_fingerprint TEXT NOT NULL, engine_json TEXT NOT NULL,
                        result_schema_version TEXT NOT NULL, time_basis_json TEXT,
                        chart_snapshot_json TEXT NOT NULL, chart_features_json TEXT NOT NULL,
                        question TEXT NOT NULL, analysis_summary TEXT NOT NULL,
                        projection_namespace TEXT NOT NULL, projection_source_id TEXT NOT NULL,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE bazi_case_events (
                        event_id TEXT NOT NULL, case_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                        category TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(case_id, event_id)
                    );
                    """
                )
            SQLiteBaziCaseStore(path)
            with sqlite3.connect(path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(bazi_cases)")}
            self.assertTrue({"raw_case_text", "interpretation_json", "predictions_json", "reviews_json"} <= columns)

    def test_parser_does_not_treat_six_dayun_columns_as_four_pillars(self) -> None:
        parsed = parse_case_text(
            "男：缺四柱\n大运：\n辛 庚 癸 甲 乙 丙\n巳 午 未 申 酉 戌\n原局：测试"
        )
        self.assertEqual(parsed, [])

    def test_parser_supports_markdown_heading_separate_pillars_and_inline_dayun(self) -> None:
        parsed = parse_case_text(
            """### 男01
己巳
己巳
壬申
辛丑
大运：庚午，辛未，壬申
原局：身不算弱。
学历：学历是博士。"""
        )

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["pillars"], ["己巳", "己巳", "壬申", "辛丑"])
        self.assertEqual(parsed[0]["dayun"], ["庚午", "辛未", "壬申"])
        self.assertEqual(parsed[0]["events"][0]["category"], "education")


if __name__ == "__main__":
    unittest.main()
