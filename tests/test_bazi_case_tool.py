from __future__ import annotations

import unittest

from jsonschema import Draft202012Validator

from marten_runtime.runtime.capabilities import get_capability_declarations
from marten_runtime.tools.builtins.bazi_case_tool import run_bazi_case_tool
from marten_runtime.tools.builtins.bazi_tool import CURRENT_RESULT_STATE_KEY
from marten_runtime.tools.builtins.bazi_tool import RESULTS_BY_ACTION_STATE_KEY
from marten_runtime.bazi_cases.service import owner_key_from_context
from tests.bazi_case_support import bazi_result, build_case_service


class BaziCaseToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service, self.tmp = build_case_service()
        self.context = {
            "channel_id": "feishu",
            "user_id": "user-a",
            "session_id": "session-1",
            "run_id": "run-1",
            "turn_tool_state": {},
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_capability_schema_is_valid_and_requires_action_specific_fields(self) -> None:
        schema = get_capability_declarations()["bazi_case"].parameters_schema
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        self.assertFalse(list(validator.iter_errors({"action": "list"})))
        self.assertTrue(list(validator.iter_errors({"action": "search"})))
        self.assertTrue(list(validator.iter_errors({"action": "update_events", "case_id": "c1"})))
        self.assertTrue(list(validator.iter_errors({"action": "import_text"})))
        self.assertFalse(list(validator.iter_errors({"action": "import_text", "text": "有效案例"})))
        self.assertFalse(
            list(
                validator.iter_errors(
                    {
                        "action": "save_current",
                        "events": [
                            {
                                "category": "health",
                                "description": "母亲住院治疗",
                                "evidence_type": "user_reported",
                                "subject": "mother",
                            }
                        ],
                    }
                )
            )
        )

    def test_save_requires_successful_bazi_result_in_same_turn(self) -> None:
        missing = run_bazi_case_tool(
            {"action": "save_current"}, case_service=self.service, tool_context=self.context
        )
        self.context["turn_tool_state"][CURRENT_RESULT_STATE_KEY] = bazi_result(
            ["甲子", "丙寅", "戊辰", "庚申"]
        )
        saved = run_bazi_case_tool(
            {
                "action": "save_current",
                "question": "事业如何",
                "events": [
                    {
                        "category": "career",
                        "description": "2021年晋升",
                        "evidence_type": "user_reported",
                    }
                ],
            },
            case_service=self.service,
            tool_context=self.context,
        )

        self.assertEqual(missing["error_code"], "BAZI_CASE_CURRENT_RUN_REQUIRED")
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["case"]["source_run_id"], "run-1")

    def test_missing_trusted_identity_fails_closed(self) -> None:
        result = run_bazi_case_tool(
            {"action": "list"},
            case_service=self.service,
            tool_context={"channel_id": "feishu", "user_id": ""},
        )
        self.assertEqual(result["error_code"], "BAZI_CASE_OWNER_REQUIRED")

    def test_model_inferred_event_cannot_be_marked_verified(self) -> None:
        self.context["turn_tool_state"][CURRENT_RESULT_STATE_KEY] = bazi_result(
            ["甲子", "丙寅", "戊辰", "庚申"]
        )
        result = run_bazi_case_tool(
            {
                "action": "save_current",
                "events": [
                    {
                        "category": "career",
                        "description": "推测晋升",
                        "evidence_type": "model_inferred",
                        "verification_status": "verified",
                    }
                ],
            },
            case_service=self.service,
            tool_context=self.context,
        )
        self.assertEqual(result["error_code"], "BAZI_CASE_EVENT_VERIFICATION_INVALID")

    def test_save_uses_chart_features_when_dayun_is_latest_result(self) -> None:
        chart = {**bazi_result(["甲子", "丙寅", "戊辰", "庚申"]), "action": "chart"}
        dayun = {
            **bazi_result(["甲子", "丙寅", "戊辰", "庚申"]),
            "action": "dayun",
            "result": {"大运列表": [{"干支": "辛酉"}]},
        }
        self.context["turn_tool_state"] = {
            CURRENT_RESULT_STATE_KEY: dayun,
            RESULTS_BY_ACTION_STATE_KEY: {"chart": chart, "dayun": dayun},
        }

        saved = run_bazi_case_tool(
            {"action": "save_current"},
            case_service=self.service,
            tool_context=self.context,
        )

        self.assertEqual(saved["case"]["chart_features"]["day_pillar"], "戊辰")
        owner = owner_key_from_context(self.context)
        stored = self.service.store.get(owner, saved["case"]["case_id"])
        self.assertEqual(stored.chart_snapshot["_related_results"]["dayun"]["大运列表"][0]["干支"], "辛酉")

    def test_save_accepts_resolved_original_pillars_with_related_dayun(self) -> None:
        resolved = {
            **bazi_result(["甲子", "丙寅", "戊辰", "庚申"]),
            "action": "resolve_pillars",
            "result": {
                "原始四柱": {"年柱": "戊辰", "月柱": "甲寅", "日柱": "辛丑", "时柱": "戊子"},
                "候选数量": 1,
            },
        }
        dayun = {
            **bazi_result(["甲子", "丙寅", "戊辰", "庚申"]),
            "action": "dayun",
            "result": {"大运列表": [{"干支": "壬申"}]},
        }
        self.context["turn_tool_state"] = {
            CURRENT_RESULT_STATE_KEY: dayun,
            RESULTS_BY_ACTION_STATE_KEY: {"resolve_pillars": resolved, "dayun": dayun},
        }

        saved = run_bazi_case_tool(
            {"action": "save_current"}, case_service=self.service, tool_context=self.context
        )

        self.assertTrue(saved["ok"])
        self.assertEqual(saved["case"]["chart_features"]["day_pillar"], "辛丑")

    def test_malformed_event_returns_domain_error(self) -> None:
        self.context["turn_tool_state"][CURRENT_RESULT_STATE_KEY] = bazi_result(
            ["甲子", "丙寅", "戊辰", "庚申"]
        )
        result = run_bazi_case_tool(
            {"action": "save_current", "events": ["not-an-object"]},
            case_service=self.service,
            tool_context=self.context,
        )
        self.assertEqual(result["error_code"], "BAZI_CASE_EVENT_INVALID")

    def test_import_text_uses_trusted_owner_without_current_chart(self) -> None:
        result = run_bazi_case_tool(
            {
                "action": "import_text",
                "text": "男：13\n庚 庚 己 癸\n辰 辰 未 酉\n原局：主要用食伤。\n命主反馈：工作较稳定。",
            },
            case_service=self.service,
            tool_context=self.context,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["cases"][0]["source_type"], "operator_imported")


if __name__ == "__main__":
    unittest.main()
