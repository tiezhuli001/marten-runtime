from __future__ import annotations

import unittest

from jsonschema import Draft202012Validator

from marten_runtime.runtime.bazi_bridge import ENGINE
from marten_runtime.tools.builtins.bazi_tool import (
    BAZI_PARAMETERS_SCHEMA,
    run_bazi_tool,
    validate_bazi_payload,
)


class FakeBridgeManager:
    def __init__(self, response: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.response = response

    def invoke(
        self,
        action,
        arguments,
        *,
        detail_level,
        tool_context,
        request_id,
    ) -> dict:
        self.calls.append(
            {
                "action": action,
                "arguments": arguments,
                "detail_level": detail_level,
                "tool_context": tool_context,
                "request_id": request_id,
            }
        )
        return self.response or {
            "ok": True,
            "protocolVersion": "1",
            "requestId": request_id,
            "action": action,
            "resultSchemaVersion": f"bazi.{action}.v1",
            "engine": dict(ENGINE),
            "inputFingerprint": "sha256:" + "a" * 64,
            "structuredContent": {"四柱": ["戊辰", "甲寅", "辛丑", "戊子"]},
            "normalizedTime": {
                "requested": "true_solar",
                "timezone": "Asia/Shanghai",
                "placeResolution": {
                    "provider": "amap",
                    "resolverVersion": "taibu-14860a2-marten-v1",
                    "formattedAddress": "四川省成都市武侯区",
                    "adcode": "510107",
                    "level": "区县",
                    "coordinateSystem": "gcj02",
                    "resolvedLongitude": 104.04,
                    "resolvedLatitude": 30.64,
                },
            },
            "degradedDiagnostics": [],
        }


class BaziToolTests(unittest.TestCase):
    @staticmethod
    def birth_payload(**overrides) -> dict:
        return {
            "action": "chart",
            "gender": "male",
            "birthYear": 1988,
            "birthMonth": 2,
            "birthDay": 15,
            "birthHour": 23,
            **overrides,
        }

    def test_schema_is_valid_draft_2020_12_and_uses_closed_action_unions(self) -> None:
        Draft202012Validator.check_schema(BAZI_PARAMETERS_SCHEMA)
        validator = Draft202012Validator(BAZI_PARAMETERS_SCHEMA)

        self.assertFalse(list(validator.iter_errors(self.birth_payload())))
        self.assertFalse(
            list(
                validator.iter_errors(
                    {
                        "action": "resolve_pillars",
                        "gender": "male",
                        "yearPillar": "戊辰",
                        "monthPillar": "甲寅",
                        "dayPillar": "辛丑",
                        "hourPillar": "戊子",
                    }
                )
            )
        )
        self.assertTrue(list(validator.iter_errors(self.birth_payload(longitude=104.04))))
        self.assertTrue(
            list(validator.iter_errors(self.birth_payload(timeBasis="true_solar")))
        )

    def test_birth_defaults_and_place_normalization_reach_manager(self) -> None:
        manager = FakeBridgeManager()
        context = {"turn_tool_state": {}}

        result = run_bazi_tool(
            self.birth_payload(
                timeBasis="true_solar",
                birthPlace=" 四川省\u3000成都市  武侯区 ",
            ),
            bridge_manager=manager,
            tool_context=context,
        )

        self.assertTrue(result["ok"])
        call = manager.calls[0]
        self.assertEqual(call["arguments"]["birthMinute"], 0)
        self.assertEqual(call["arguments"]["calendarType"], "solar")
        self.assertEqual(call["arguments"]["birthPlace"], "四川省 成都市 武侯区")
        self.assertIs(call["tool_context"], context)

    def test_model_result_omits_exact_coordinates_and_keeps_place_audit(self) -> None:
        result = run_bazi_tool(
            self.birth_payload(timeBasis="true_solar", birthPlace="成都市武侯区"),
            bridge_manager=FakeBridgeManager(),
        )

        place = result["timeBasis"]["placeResolution"]
        self.assertEqual(place["provider"], "amap")
        self.assertEqual(place["adcode"], "510107")
        self.assertNotIn("resolvedLongitude", place)
        self.assertNotIn("resolvedLatitude", place)
        self.assertIn("四柱", result["result"])

    def test_host_rejects_invalid_dates_ranges_timezone_and_public_coordinates(self) -> None:
        invalid = (
            (self.birth_payload(birthYear=1900), "bazi_birth_year_unsupported"),
            (self.birth_payload(birthMonth=2, birthDay=30), "bazi_bridge_invalid_request"),
            (self.birth_payload(timezone="UTC"), "bazi_timezone_unsupported"),
            (self.birth_payload(longitude=104), "bazi_bridge_invalid_request"),
            (self.birth_payload(calendarType="solar", isLeapMonth=True), "bazi_bridge_invalid_request"),
            (self.birth_payload(timeBasis="true_solar"), "bazi_birth_place_required"),
        )
        for payload, code in invalid:
            with self.subTest(payload=payload):
                manager = FakeBridgeManager()
                result = run_bazi_tool(payload, bridge_manager=manager)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], code)
                self.assertEqual(manager.calls, [])

    def test_resolve_rejects_structurally_valid_non_jiazi_pair(self) -> None:
        manager = FakeBridgeManager()
        result = run_bazi_tool(
            {
                "action": "resolve_pillars",
                "yearPillar": "甲丑",
                "monthPillar": "甲寅",
                "dayPillar": "辛丑",
                "hourPillar": "戊子",
            },
            bridge_manager=manager,
        )

        self.assertEqual(result["error"]["code"], "bazi_bridge_invalid_request")
        self.assertEqual(manager.calls, [])

    def test_real_bridge_rejects_nonexistent_lunar_leap_month(self) -> None:
        from marten_runtime.runtime.bazi_bridge import BaziBridgeManager

        result = run_bazi_tool(
            self.birth_payload(
                birthYear=2023,
                birthMonth=3,
                birthDay=1,
                calendarType="lunar",
                isLeapMonth=True,
            ),
            bridge_manager=BaziBridgeManager(env={}),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "bazi_bridge_invalid_request")

    def test_real_bridge_full_dayun_includes_annual_timing_facts(self) -> None:
        from marten_runtime.runtime.bazi_bridge import BaziBridgeManager

        result = run_bazi_tool(
            self.birth_payload(
                action="dayun",
                gender="male",
                birthYear=1994,
                birthMonth=5,
                birthDay=31,
                birthHour=7,
                detailLevel="full",
            ),
            bridge_manager=BaziBridgeManager(env={}),
        )

        self.assertTrue(result["ok"])
        cycles = result["result"]["大运列表"]
        self.assertTrue(cycles)
        self.assertTrue(cycles[0]["流年列表"])
        self.assertIn("原局关系", cycles[0]["流年列表"][0])

    def test_validation_expands_resolve_arguments_without_detail_level(self) -> None:
        arguments, detail = validate_bazi_payload(
            {
                "action": "resolve_pillars",
                "yearPillar": "戊辰",
                "monthPillar": "甲寅",
                "dayPillar": "辛丑",
                "hourPillar": "戊子",
            }
        )
        self.assertEqual(detail, "default")
        self.assertEqual(arguments["dayPillar"], "辛丑")

    def test_resolve_accepts_gender_for_followup_without_sending_it_to_bridge(self) -> None:
        manager = FakeBridgeManager()
        payload = {
            "action": "resolve_pillars",
            "gender": "male",
            "yearPillar": "甲戌",
            "monthPillar": "己巳",
            "dayPillar": "丁巳",
            "hourPillar": "甲辰",
        }

        result = run_bazi_tool(payload, bridge_manager=manager)

        self.assertTrue(result["ok"])
        self.assertNotIn("gender", manager.calls[0]["arguments"])

    def test_identical_successful_request_reuses_turn_result(self) -> None:
        manager = FakeBridgeManager()
        context = {"turn_tool_state": {}}

        first = run_bazi_tool(self.birth_payload(), bridge_manager=manager, tool_context=context)
        second = run_bazi_tool(self.birth_payload(), bridge_manager=manager, tool_context=context)

        self.assertEqual(len(manager.calls), 1)
        self.assertTrue(second["duplicateRequestSuppressed"])
        self.assertNotEqual(first["requestId"], second["requestId"])
        self.assertEqual(first["inputFingerprint"], second["inputFingerprint"])

    def test_chart_and_dayun_keep_distinct_successful_requests(self) -> None:
        manager = FakeBridgeManager()
        context = {"turn_tool_state": {}}

        run_bazi_tool(self.birth_payload(), bridge_manager=manager, tool_context=context)
        run_bazi_tool(self.birth_payload(action="dayun"), bridge_manager=manager, tool_context=context)

        self.assertEqual([call["action"] for call in manager.calls], ["chart", "dayun"])

    def test_model_string_scalars_are_normalized_at_builtin_boundary(self) -> None:
        manager = FakeBridgeManager()

        result = run_bazi_tool(
            self.birth_payload(
                birthYear="1994",
                birthMonth="4",
                birthDay="21",
                birthHour="8",
                birthMinute="40",
                calendarType="lunar",
                isLeapMonth="false",
            ),
            bridge_manager=manager,
        )

        self.assertTrue(result["ok"])
        arguments = manager.calls[0]["arguments"]
        self.assertEqual(arguments["birthYear"], 1994)
        self.assertEqual(arguments["birthMinute"], 40)
        self.assertIs(arguments["isLeapMonth"], False)

    def test_ambiguous_model_string_scalars_remain_invalid(self) -> None:
        invalid = (
            self.birth_payload(birthYear="1994.0"),
            self.birth_payload(birthYear="一九九四"),
            self.birth_payload(calendarType="lunar", isLeapMonth="no"),
        )

        for payload in invalid:
            with self.subTest(payload=payload):
                result = run_bazi_tool(payload, bridge_manager=FakeBridgeManager())
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "bazi_bridge_invalid_request")


if __name__ == "__main__":
    unittest.main()
