from __future__ import annotations

import json
import unittest

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.llm_message_support import (
    _annual_event_candidates,
    _compact_bazi_structural_summary,
    _compact_bazi_timing_years,
    _ten_god_for_stem,
    build_openai_chat_payload,
)
from marten_runtime.runtime.bazi_output_contract import missing_bazi_sections
from marten_runtime.channels.feishu.rendering import (
    normalize_feishu_durable_text,
    parse_feishu_card_protocol,
    render_final_reply_card,
)
from marten_runtime.runtime.loop import (
    RuntimeLoop,
    _bazi_dayun_payload,
    _bazi_has_actionable_birth_input,
)
from marten_runtime.runtime.run_outcome_flow import _ensure_bazi_citation_footer
from marten_runtime.runtime.llm_client import ToolExchange
from marten_runtime.tools.registry import ToolRegistry
from tests.support.finalization_contracts import contracted_final_reply


class BaziTurnToolStateTests(unittest.TestCase):
    def test_actionable_birth_input_accepts_complete_birth_or_four_pillars(self) -> None:
        self.assertTrue(
            _bazi_has_actionable_birth_input(
                "男，1988年农历二月十五日早上10点20分，四川省成都市武侯区。"
            )
        )
        self.assertTrue(
            _bazi_has_actionable_birth_input("男，甲戌，己巳，丁巳，甲辰。")
        )
        self.assertFalse(
            _bazi_has_actionable_birth_input("农历二月十四日，请分析。")
        )

    def _run_once(self, captured: list[dict]) -> None:
        tools = ToolRegistry()

        def handler(payload: dict, *, tool_context: dict | None = None) -> dict:
            state = tool_context["turn_tool_state"]
            state.setdefault("calls", []).append(payload["ordinal"])
            captured.append(state)
            return {"ok": True, "result_text": str(payload["ordinal"])}

        tools.register("capture", handler)
        runtime = RuntimeLoop(
            ScriptedLLMClient(
                [
                    LLMReply(tool_name="capture", tool_payload={"ordinal": 1}),
                    LLMReply(tool_name="capture", tool_payload={"ordinal": 2}),
                    contracted_final_reply("done"),
                ]
            ),
            tools,
            InMemoryRunHistory(),
        )
        runtime.run(
            session_id="session",
            message="capture",
            agent=AgentSpec(agent_id="main", role="test", allowed_tools=["capture"]),
        )

    def test_one_run_shares_one_mutable_turn_tool_state(self) -> None:
        captured: list[dict] = []

        self._run_once(captured)

        self.assertEqual(len(captured), 2)
        self.assertIs(captured[0], captured[1])
        self.assertEqual(captured[0]["calls"], [1, 2])

    def test_separate_runs_receive_separate_turn_tool_state(self) -> None:
        first: list[dict] = []
        second: list[dict] = []

        self._run_once(first)
        self._run_once(second)

        self.assertIsNot(first[0], second[0])
        self.assertEqual(first[0]["calls"], [1, 2])
        self.assertEqual(second[0]["calls"], [1, 2])

    def test_bazi_complete_evidence_forces_tool_free_finalization(self) -> None:
        tools = ToolRegistry()
        time_calls: list[dict] = []
        tools.register(
            "bazi",
            lambda payload: {"ok": True, "action": payload["action"], "result": {"四柱": ["甲戌", "己巳", "丁巳", "甲辰"]}},
        )
        tools.register(
            "knowledge",
            lambda payload: {
                "ok": True,
                "action": "search",
                "results": [
                    {"text": "reviewed theory", "source_id": "source-1", "chunk_id": "chunk-1"}
                ],
            },
        )
        tools.register("time", lambda payload: time_calls.append(payload) or {"ok": True})
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="bazi", tool_payload={"action": "resolve_pillars"}),
                LLMReply(
                    tool_name="knowledge",
                    tool_payload={"action": "search", "namespace": "bazi-theory", "query": "丁火"},
                ),
                LLMReply(tool_name="time", tool_payload={"action": "now"}),
                contracted_final_reply("四柱事实与理论分析已完成。source_id: source-1; chunk_id: chunk-1"),
            ]
        )
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(llm, tools, history)

        events = runtime.run(
            session_id="session",
            message="分析四柱",
            agent=AgentSpec(
                agent_id="bazi",
                role="test",
                allowed_tools=["bazi", "knowledge", "time"],
            ),
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["bazi", "knowledge"])
        self.assertEqual(time_calls, [])
        self.assertEqual(llm.requests[-1].request_kind, "finalization_retry")
        self.assertEqual(llm.requests[-1].available_tools, [])

    def test_bazi_complete_evidence_keeps_explicitly_requested_dayun_call(self) -> None:
        tools = ToolRegistry()
        tools.register(
            "bazi",
            lambda payload: {
                "ok": True,
                "action": payload["action"],
                "result": {"facts": payload["action"]},
                "inputFingerprint": f"sha256:{'a' * 64}",
            },
        )
        tools.register(
            "knowledge",
            lambda payload: {
                "ok": True,
                "action": "search",
                "results": [
                    {
                        "text": "reviewed theory",
                        "source_id": "source-1",
                        "chunk_id": "chunk-1",
                    }
                ],
            },
        )
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="bazi", tool_payload={"action": "chart"}),
                LLMReply(tool_name="bazi", tool_payload={"action": "dayun"}),
                LLMReply(
                    tool_name="knowledge",
                    tool_payload={
                        "action": "search",
                        "namespace": "bazi-theory",
                        "query": "丁火",
                    },
                ),
                contracted_final_reply(
                    "排盘、大运与理论分析完成。source_id: source-1; chunk_id: chunk-1"
                ),
            ]
        )
        history = InMemoryRunHistory()

        events = RuntimeLoop(llm, tools, history).run(
            session_id="session",
            message="请排盘并查看大运",
            agent=AgentSpec(
                agent_id="bazi",
                role="test",
                allowed_tools=["bazi", "knowledge"],
            ),
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(
            [
                (item["tool_name"], item["tool_payload"].get("action"))
                for item in run.tool_calls
            ],
            [("bazi", "chart"), ("bazi", "dayun"), ("knowledge", "search")],
        )
        self.assertEqual(llm.requests[-1].request_kind, "finalization_retry")
        self.assertEqual(llm.requests[-1].available_tools, [])
        self.assertEqual(len(llm.requests[-1].tool_history), 3)

    def test_four_pillar_input_with_supplied_dayun_finalizes_without_dayun_tool(self) -> None:
        tools = ToolRegistry()
        tools.register(
            "bazi",
            lambda payload: {
                "ok": True,
                "action": payload["action"],
                "result": {"四柱": ["乙丑", "戊子", "辛巳", "己亥"]},
            },
        )
        tools.register(
            "knowledge",
            lambda payload: {
                "ok": True,
                "action": "search",
                "results": [
                    {
                        "text": "reviewed theory",
                        "source_id": "source-1",
                        "chunk_id": "chunk-1",
                    }
                ],
            },
        )
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="bazi", tool_payload={"action": "resolve_pillars"}),
                LLMReply(
                    tool_name="knowledge",
                    tool_payload={
                        "action": "search",
                        "namespace": "bazi-theory",
                        "query": "辛金 子月",
                    },
                ),
                contracted_final_reply("四柱与用户提供的大运分析完成。"),
            ]
        )
        history = InMemoryRunHistory()

        events = RuntimeLoop(llm, tools, history).run(
            session_id="session",
            message="四柱乙丑、戊子、辛巳、己亥，大运丁亥、丙戌、乙酉、甲申、癸未",
            agent=AgentSpec(
                agent_id="bazi",
                role="test",
                allowed_tools=["bazi", "knowledge"],
            ),
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(
            [
                (item["tool_name"], item["tool_payload"].get("action"))
                for item in run.tool_calls
            ],
            [("bazi", "resolve_pillars"), ("knowledge", "search")],
        )
        self.assertEqual(llm.requests[-1].request_kind, "finalization_retry")
        self.assertEqual(llm.requests[-1].available_tools, [])

    def test_four_pillar_full_analysis_uses_unique_past_candidate_for_dayun(self) -> None:
        tools = ToolRegistry()
        calls: list[dict] = []

        def bazi_handler(payload: dict) -> dict:
            calls.append(dict(payload))
            if payload["action"] == "resolve_pillars":
                result = {
                    "原始四柱": {
                        "年柱": "甲戌",
                        "月柱": "己巳",
                        "日柱": "丁巳",
                        "时柱": "甲辰",
                    },
                    "候选数量": 2,
                    "候选列表": [
                        {"候选序号": 1, "公历": "1994-05-31 07:00"},
                        {"候选序号": 2, "公历": "2054-05-16 07:00"},
                    ],
                }
            else:
                result = {
                    "起运信息": {"起运年龄": 1, "起运时间": "1995-11-07 12:00"},
                    "大运列表": [
                        {"起运年份": 1995, "起运年龄": 1, "干支": "庚午"},
                        {"起运年份": 2005, "起运年龄": 11, "干支": "辛未"},
                    ],
                }
            return {
                "ok": True,
                "action": payload["action"],
                "inputFingerprint": "sha256:" + "a" * 64,
                "result": result,
            }

        tools.register("bazi", bazi_handler)
        tools.register(
            "knowledge",
            lambda payload: {
                "ok": True,
                "action": "search",
                "results": [
                    {
                        "text": "reviewed theory",
                        "source_id": "source-1",
                        "chunk_id": "chunk-1",
                    }
                ],
            },
        )
        resolve_payload = {
            "action": "resolve_pillars",
            "yearPillar": "甲戌",
            "monthPillar": "己巳",
            "dayPillar": "丁巳",
            "hourPillar": "甲辰",
        }
        inferred_dayun = {
            "action": "dayun",
            "gender": "male",
            "birthYear": 1994,
            "birthMonth": 5,
            "birthDay": 31,
            "birthHour": 7,
            "birthMinute": 0,
            "calendarType": "solar",
            "isLeapMonth": False,
            "timeBasis": "clock",
            "timezone": "Asia/Shanghai",
            "sourceTimeStandard": "beijing_standard",
            "detailLevel": "full",
        }
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="bazi", tool_payload=resolve_payload),
                LLMReply(tool_name="bazi", tool_payload=inferred_dayun),
                LLMReply(
                    tool_name="knowledge",
                    tool_payload={
                        "action": "search",
                        "namespace": "bazi-theory",
                        "query": "丁火 巳月",
                    },
                ),
                contracted_final_reply("完整解盘。"),
            ]
        )
        history = InMemoryRunHistory()

        events = RuntimeLoop(llm, tools, history).run(
            session_id="session",
            message="男，甲戌、己巳、丁巳、甲辰",
            agent=AgentSpec(
                agent_id="bazi",
                role="test",
                allowed_tools=["bazi", "knowledge"],
            ),
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(
            [
                (item["tool_name"], item["tool_payload"].get("action"))
                for item in run.tool_calls
            ],
            [
                ("bazi", "resolve_pillars"),
                ("bazi", "dayun"),
                ("knowledge", "search"),
            ],
        )
        self.assertEqual(calls[1], inferred_dayun)
        self.assertEqual(llm.requests[1].request_kind, "bazi_dayun_repair")
        self.assertEqual(llm.requests[1].requested_tool_payload, inferred_dayun)

    def test_four_pillar_dayun_repair_overrides_wrong_model_action(self) -> None:
        calls: list[dict] = []
        tools = ToolRegistry()

        def bazi_handler(payload: dict) -> dict:
            calls.append(payload)
            if payload["action"] == "resolve_pillars":
                return {
                    "ok": True,
                    "action": "resolve_pillars",
                    "result": {"候选列表": [{"公历": "1994-05-31 07:00"}]},
                }
            return {"ok": True, "action": "dayun", "result": {"大运": []}}

        tools.register("bazi", bazi_handler)
        tools.register(
            "knowledge",
            lambda payload: {"ok": True, "action": "search", "results": []},
        )
        resolve_payload = {
            "action": "resolve_pillars",
            "gender": "male",
            "yearPillar": "甲戌",
            "monthPillar": "己巳",
            "dayPillar": "丁巳",
            "hourPillar": "甲辰",
        }
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="bazi", tool_payload=resolve_payload),
                LLMReply(tool_name="bazi", tool_payload=resolve_payload),
                LLMReply(
                    tool_name="knowledge",
                    tool_payload={
                        "action": "search",
                        "namespace": "bazi-theory",
                        "query": "丁火 巳月",
                    },
                ),
                contracted_final_reply("完整解盘。"),
            ]
        )

        RuntimeLoop(llm, tools, InMemoryRunHistory()).run(
            session_id="session",
            message="男，甲戌、己巳、丁巳、甲辰，请完整分析",
            agent=AgentSpec(
                agent_id="bazi",
                role="test",
                allowed_tools=["bazi", "knowledge"],
            ),
        )

        self.assertEqual([item["action"] for item in calls], ["resolve_pillars", "dayun"])
        repair_request = build_openai_chat_payload("gpt-5.4", llm.requests[1])
        bazi_tool = next(item for item in repair_request["tools"] if item["function"]["name"] == "bazi")
        parameters = bazi_tool["function"]["parameters"]
        self.assertEqual(parameters["properties"]["action"]["const"], "dayun")
        self.assertEqual(parameters["properties"]["birthYear"]["const"], 1994)
        self.assertFalse(parameters["additionalProperties"])

    def test_four_pillar_dayun_does_not_choose_between_multiple_past_candidates(self) -> None:
        exchange = ToolExchange(
            tool_name="bazi",
            tool_payload={
                "action": "resolve_pillars",
                "yearPillar": "甲戌",
                "monthPillar": "己巳",
                "dayPillar": "丁巳",
                "hourPillar": "甲辰",
            },
            tool_result={
                "ok": True,
                "action": "resolve_pillars",
                "result": {
                    "候选列表": [
                        {"公历": "1934-06-15 07:00"},
                        {"公历": "1994-05-31 07:00"},
                    ]
                },
            },
        )

        self.assertIsNone(_bazi_dayun_payload([exchange], "男，完整分析"))

    def test_bazi_final_without_theory_forces_one_knowledge_search(self) -> None:
        tools = ToolRegistry()
        tools.register(
            "bazi",
            lambda payload: {
                "ok": True,
                "action": payload["action"],
                "result": {"四柱": ["甲戌", "己巳", "丁巳", "甲辰"]},
            },
        )
        tools.register(
            "knowledge",
            lambda payload: {
                "ok": True,
                "action": payload["action"],
                "results": [
                    {
                        "text": "reviewed theory",
                        "source_id": "source-1",
                        "chunk_id": "chunk-1",
                    }
                ],
            },
        )
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="bazi", tool_payload={"action": "resolve_pillars"}),
                LLMReply(
                    tool_name="knowledge",
                    tool_payload={
                        "action": "search",
                        "namespace": "bazi-theory",
                        "query": "丁火 巳月 五行关系",
                    },
                ),
                contracted_final_reply(
                    "四柱为甲戌、己巳、丁巳、甲辰。"
                    "理论分析引用 source_id: source-1; chunk_id: chunk-1"
                ),
            ]
        )
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(llm, tools, history)

        events = runtime.run(
            session_id="session",
            message="分析四柱并给出来源引用",
            agent=AgentSpec(
                agent_id="bazi",
                role="test",
                allowed_tools=["bazi", "knowledge"],
            ),
        )

        run = history.get(events[-1].run_id)
        self.assertEqual([item["tool_name"] for item in run.tool_calls], ["bazi", "knowledge"])
        self.assertEqual(llm.requests[1].request_kind, "bazi_knowledge_search")
        payload = build_openai_chat_payload("gpt-5.4", llm.requests[1])
        self.assertEqual(
            payload["tool_choice"],
            {"type": "function", "function": {"name": "knowledge"}},
        )
        schema = payload["tools"][0]["function"]["parameters"]
        self.assertEqual(schema["properties"]["action"]["const"], "search")
        self.assertEqual(schema["properties"]["namespace"]["const"], "bazi-theory")
        self.assertEqual(run.llm_request_count, 3)

    def test_bazi_full_analysis_repairs_dayun_before_knowledge(self) -> None:
        tools = ToolRegistry()
        fingerprint = "sha256:" + "a" * 64

        def bazi_handler(payload: dict) -> dict:
            result = {
                "四柱": [
                    {"柱": "年柱", "干支": "甲戌"},
                    {"柱": "月柱", "干支": "己巳"},
                    {"柱": "日柱", "干支": "丁巳"},
                    {"柱": "时柱", "干支": "甲辰"},
                ]
            }
            if payload["action"] == "dayun":
                result = {
                    "起运信息": {"起运年龄": 3, "起运时间": "1996-05-20 08:17"},
                    "大运列表": [
                        {
                            "起运年份": 1996,
                            "起运年龄": 3,
                            "干支": "庚午",
                            "十神": "正财",
                            "藏干": [1, 2, 3],
                            "流年列表": [
                                {
                                    "流年": 2018,
                                    "年龄": 25,
                                    "干支": "戊戌",
                                    "十神": "食神",
                                    "神煞": ["驿马", "华盖"],
                                    "原局关系": [
                                        {"类型": "六冲", "描述": "辰戌相冲（与时柱）"}
                                    ],
                                },
                                {
                                    "流年": 2099,
                                    "年龄": 106,
                                    "干支": "己未",
                                    "十神": "伤官",
                                },
                            ],
                        },
                        {"起运年份": 2006, "起运年龄": 13, "干支": "辛未", "十神": "偏财", "藏干": [1, 2, 3]},
                        {"起运年份": 2016, "起运年龄": 23, "干支": "壬申", "十神": "正官", "藏干": [1, 2, 3]},
                    ],
                }
            return {
                "ok": True,
                "action": payload["action"],
                "inputFingerprint": fingerprint,
                "result": result,
            }

        tools.register("bazi", bazi_handler)
        tools.register(
            "knowledge",
            lambda payload: {
                "ok": True,
                "action": payload["action"],
                "results": [
                    {
                        "text": "reviewed theory",
                        "source_id": "source-1",
                        "chunk_id": "chunk-1",
                        "source_title": "滴天髓",
                        "heading": "Marten 释义",
                    }
                ],
            },
        )
        birth_payload = {
            "action": "chart",
            "gender": "male",
            "birthYear": 1994,
            "birthMonth": 4,
            "birthDay": 21,
            "birthHour": 8,
            "birthMinute": 40,
            "calendarType": "lunar",
        }
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="bazi", tool_payload=birth_payload),
                LLMReply(
                    tool_name="bazi",
                    tool_payload={
                        **birth_payload,
                        "action": "dayun",
                        "detailLevel": "full",
                    },
                ),
                LLMReply(
                    tool_name="knowledge",
                    tool_payload={
                        "action": "search",
                        "namespace": "bazi-theory",
                        "query": "丁火 巳月",
                    },
                ),
                contracted_final_reply("完整解盘\n参考依据：《滴天髓》·Marten 释义"),
            ]
        )
        history = InMemoryRunHistory()

        events = RuntimeLoop(llm, tools, history).run(
            session_id="session",
            message="请按子平格局法和盲派分析",
            agent=AgentSpec(
                agent_id="bazi",
                role="test",
                allowed_tools=["bazi", "knowledge"],
            ),
        )

        run = history.get(events[-1].run_id)
        self.assertEqual(
            [(item["tool_name"], item["tool_payload"]["action"]) for item in run.tool_calls],
            [("bazi", "chart"), ("bazi", "dayun"), ("knowledge", "search")],
        )
        self.assertEqual(llm.requests[1].request_kind, "bazi_dayun_repair")
        self.assertEqual(run.tool_calls[1]["tool_payload"]["detailLevel"], "full")
        self.assertEqual(llm.requests[2].request_kind, "bazi_knowledge_search")
        dayun_repair = build_openai_chat_payload("gpt-5.4", llm.requests[1])
        self.assertEqual(
            dayun_repair["tool_choice"],
            {"type": "function", "function": {"name": "bazi"}},
        )
        chart_tool_content = next(
            json.loads(item["content"])
            for item in dayun_repair["messages"]
            if item["role"] == "tool"
        )
        self.assertEqual(len(chart_tool_content["result"]["四柱"]), 4)
        self.assertNotIn("四柱_truncated_count", chart_tool_content["result"])

        finalization_request = next(
            request for request in llm.requests if request.request_kind == "finalization_retry"
        )
        final_request = build_openai_chat_payload("gpt-5.4", finalization_request)
        tool_contents = [
            json.loads(item["content"])
            for item in final_request["messages"]
            if item["role"] == "tool"
        ]
        dayun_contents = [
            item
            for item in tool_contents
            if isinstance(item.get("result"), dict)
            and "大运列表" in item["result"]
        ]
        self.assertEqual(len(dayun_contents[0]["result"]["大运列表"]), 3)
        self.assertNotIn("藏干", dayun_contents[0]["result"]["大运列表"][0])
        self.assertEqual(
            dayun_contents[0]["result"]["大运列表"][0]["天干作用"],
            [
                "庚克甲（大运干克年干）",
                "丁克庚（日干克大运干）",
                "庚克甲（大运干克时干）",
            ],
        )
        self.assertEqual(
            dayun_contents[0]["result"]["应期逐年表"],
            [
                {
                    "流年": 2018,
                    "年龄": 25,
                    "干支": "戊戌",
                    "十神": "食神",
                    "所在大运": "庚午",
                    "大运十神": "正财",
                    "作用关系": ["辰戌相冲（与时柱）"],
                    "天干作用": [
                        "甲克戊（年干克流年干）",
                        "甲克戊（时干克流年干）",
                    ],
                    "同支伏吟": ["戌伏吟年支"],
                    "结构组合": [
                        "流年食神与年干正印、年支同步引动；天干关系：甲克戊",
                        "年支伏吟叠加其他柱位受合冲刑害",
                        "大运正财克年干正印，流年支多处引动",
                    ],
                    "关键神煞": ["驿马"],
                }
            ],
        )
        self.assertEqual(
            dayun_contents[0]["result"]["成年后结构组合摘要"],
            [
                {
                    "流年": 2018,
                    "年龄": 25,
                    "干支": "戊戌",
                    "所在大运": "庚午",
                    "结构组合": [
                        "流年食神与年干正印、年支同步引动；天干关系：甲克戊",
                        "年支伏吟叠加其他柱位受合冲刑害",
                        "大运正财克年干正印，流年支多处引动",
                    ],
                    "候选归属": [
                        "房屋/搬迁/工作环境变动（年支伏吟叠加其他宫位受作用）",
                        "母亲事务待核验（大运作用父母星，流年多宫引动；缺少流年干直接作用时不单独定健康）",
                    ],
                }
            ],
        )
        self.assertNotIn("小运", dayun_contents[0]["result"])
        repair_request = llm.requests[-1]
        self.assertEqual(repair_request.request_kind, "finalization_retry")
        self.assertEqual(len(repair_request.tool_history), 3)
        repair_payload = build_openai_chat_payload("gpt-5.4", repair_request)
        self.assertTrue(any(item["role"] == "tool" for item in repair_payload["messages"]))

    def test_compact_bazi_timing_years_has_bounded_provider_payload(self) -> None:
        cycles = [
            {
                "干支": "庚午",
                "十神": "正财",
                "流年列表": [
                    {
                        "流年": year,
                        "年龄": year - 1900,
                        "干支": "戊戌",
                        "十神": "食神",
                        "原局关系": [
                            {"描述": "辰戌相冲（与时柱）"},
                            {"描述": "甲庚相冲（与年柱）"},
                        ],
                        "神煞": ["驿马", "血刃", "无关神煞"],
                    }
                    for year in range(1901, 2027)
                ],
            }
        ]

        timing_years = _compact_bazi_timing_years(
            cycles,
            current_year=2026,
            pillars=["甲戌", "己巳", "丁巳", "甲辰"],
        )
        serialized = json.dumps(timing_years, ensure_ascii=False, separators=(",", ":"))

        self.assertEqual(len(timing_years), 126)
        self.assertLess(len(serialized.encode("utf-8")), 64 * 1024)
        self.assertEqual(len(_compact_bazi_structural_summary(timing_years)), 40)

    def test_structural_summary_ranks_all_adult_years_before_limiting(self) -> None:
        timing_years = [
            {
                "流年": 1900 + index,
                "年龄": 18 + index,
                "干支": "庚辰",
                "结构组合": ["普通结构引动"],
                **(
                    {"候选归属": ["父母家宅（年干与年支同动）", "事业/岗位平台变动（月柱或职业十神受作用）"]}
                    if index == 0
                    else {}
                ),
            }
            for index in range(50)
        ]

        summary = _compact_bazi_structural_summary(timing_years, limit=10)

        self.assertEqual(len(summary), 10)
        self.assertIn(1900, [item["流年"] for item in summary])

    def test_compact_bazi_timing_years_marks_star_palace_and_health_structures(self) -> None:
        cycles = [
            {
                "干支": "壬申",
                "十神": "正官",
                "流年列表": [
                    {
                        "流年": 2023,
                        "年龄": 30,
                        "干支": "癸卯",
                        "十神": "七杀",
                        "原局关系": [{"描述": "卯辰相害（与时柱）"}],
                    },
                    {
                        "流年": 2025,
                        "年龄": 32,
                        "干支": "乙巳",
                        "十神": "偏印",
                        "原局关系": [{"描述": "巳申六合（与大运）"}],
                    },
                ],
            }
        ]

        years = _compact_bazi_timing_years(
            cycles,
            current_year=2026,
            pillars=["甲戌", "己巳", "丁巳", "甲辰"],
            pillar_ten_gods=["正印", "食神", "-", "正印"],
            include_event_candidates=True,
        )

        self.assertIn("流年七杀克日干，日支或时支同步引动", years[0]["结构组合"])
        self.assertIn("流年偏印克月干食神，月日支伏吟", years[1]["结构组合"])
        self.assertIn("本人健康/检查（流年克日主，日时宫同步引动）", years[0]["候选归属"])
        self.assertIn("事业/岗位平台变动（月柱或职业十神受作用）", years[1]["候选归属"])

    def test_event_candidates_attribute_parent_and_environment_by_relations(self) -> None:
        father = _annual_event_candidates(
            annual_ten_god="劫财",
            dayun_ten_god="食神",
            gender="male",
            pillar_ten_gods=["偏财", "正官", "-", "比肩"],
            stem_relations=["辛克甲（流年干克年干）"],
            branch_relations=["丑刑年支戌"],
            repeated_branches=[],
            structure_hints=[],
            shensha=[],
        )
        environment = _annual_event_candidates(
            annual_ten_god="偏财",
            dayun_ten_god="食神",
            gender="male",
            pillar_ten_gods=["偏财", "正官", "-", "比肩"],
            stem_relations=[],
            branch_relations=["辰戌相冲（与年柱）"],
            repeated_branches=["辰伏吟时支"],
            structure_hints=[],
            shensha=[],
        )
        mother = _annual_event_candidates(
            annual_ten_god="七杀",
            dayun_ten_god="偏财",
            gender="male",
            pillar_ten_gods=["正印", "食神", "-", "正印"],
            stem_relations=[],
            branch_relations=[],
            repeated_branches=["巳伏吟月支", "巳伏吟日支"],
            structure_hints=["大运偏财克年干正印，流年支多处引动"],
            shensha=[],
        )

        self.assertIn("父亲事务/健康（父母星与年柱同动）", father)
        self.assertIn("房屋/搬迁/工作环境变动（年支受冲且时支同步引动）", environment)
        self.assertIn(
            "母亲事务待核验（大运作用父母星，流年多宫引动；缺少流年干直接作用时不单独定健康）",
            mother,
        )

        weak_father = _annual_event_candidates(
            annual_ten_god="偏财",
            dayun_ten_god="正官",
            gender="male",
            pillar_ten_gods=["正印", "食神", "-", "正印"],
            stem_relations=["辛克甲（流年干克年干）"],
            branch_relations=["丑刑年支戌"],
            repeated_branches=[],
            structure_hints=[],
            shensha=[],
        )
        self.assertNotIn("父亲事务/健康（父星出现并引动年柱）", weak_father)

    def test_ten_god_fallback_matches_yin_yang_and_five_element_relations(self) -> None:
        self.assertEqual(
            [_ten_god_for_stem("丁", stem) for stem in "甲乙丙戊己庚辛壬癸"],
            ["正印", "偏印", "劫财", "伤官", "食神", "正财", "偏财", "正官", "七杀"],
        )
        self.assertEqual(
            [_ten_god_for_stem("庚", stem) for stem in "甲乙丙丁戊己壬癸"],
            ["偏财", "正财", "七杀", "正官", "偏印", "正印", "食神", "伤官"],
        )

    def test_bazi_finalization_adds_every_missing_knowledge_citation(self) -> None:
        tools = ToolRegistry()
        tools.register(
            "bazi",
            lambda payload: {
                "ok": True,
                "action": payload["action"],
                "result": {"四柱": ["甲戌", "己巳", "丁巳", "甲辰"]},
            },
        )
        tools.register(
            "knowledge",
            lambda payload: {
                "ok": True,
                "action": "search",
                "results": [
                    {
                        "text": "theory one",
                        "source_id": "source-1",
                        "chunk_id": "chunk-1",
                        "source_title": "穷通宝鉴",
                        "heading": "调候方法",
                    },
                    {
                        "text": "theory two",
                        "source_id": "source-2",
                        "chunk_id": "chunk-2",
                        "source_title": "子平真诠",
                        "heading": "格局方法",
                    },
                    {
                        "text": "theory three",
                        "source_id": "source-3",
                        "chunk_id": "chunk-3",
                        "source_title": "滴天髓",
                        "heading": "病药方法",
                    },
                ],
            },
        )
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="bazi", tool_payload={"action": "resolve_pillars"}),
                LLMReply(
                    tool_name="knowledge",
                    tool_payload={
                        "action": "search",
                        "namespace": "bazi-theory",
                        "query": "丁火 巳月",
                    },
                ),
                contracted_final_reply("丁火生于巳月，火势偏旺。"),
            ]
        )
        runtime = RuntimeLoop(llm, tools, InMemoryRunHistory())

        events = runtime.run(
            session_id="session",
            message="分析四柱",
            agent=AgentSpec(
                agent_id="bazi",
                role="test",
                allowed_tools=["bazi", "knowledge"],
            ),
        )

        final_text = events[-1].payload["text"]
        for value in ("《穷通宝鉴》 · 调候方法", "《子平真诠》 · 格局方法", "《滴天髓》 · 病药方法"):
            self.assertIn(value, final_text)
        for value in ("source-1", "chunk-1", "source_id", "chunk_id"):
            self.assertNotIn(value, final_text)
        instruction = build_openai_chat_payload("gpt-5.4", llm.requests[-1])
        self.assertIn("排盘事实", str(instruction))
        self.assertIn("《子平真诠》·格局方法", str(instruction))
        self.assertIn("格局、旺衰、调候、病药", str(instruction))
        self.assertIn("原局格局喜用", str(instruction))
        self.assertIn("财富等级", str(instruction))
        self.assertIn("过三关", str(instruction))
        self.assertIn("具体公历年份", str(instruction))
        self.assertIn("待核验事件", str(instruction))
        self.assertIn("推算原因", str(instruction))
        self.assertIn("流年干支", str(instruction))
        self.assertIn("高中、大专、本科、顶级本科", str(instruction))
        self.assertIn("没有这些证据时完全省略二婚和外缘", str(instruction))
        self.assertIn("年支桃花只可作为一般社交信号", str(instruction))
        self.assertIn("寅午戌见卯、申子辰见酉、巳酉丑见午、亥卯未见子", str(instruction))
        self.assertIn("检查、治疗、住院或开刀经历", str(instruction))
        self.assertIn("父星、母星、年柱", str(instruction))
        self.assertIn("不为满足栏目数量而加入较弱事件", str(instruction))
        self.assertIn("300 万元小康", str(instruction))
        self.assertIn("低于 300 万元普通积累", str(instruction))
        self.assertIn("食伤生财或无财而暗成财局", str(instruction))
        self.assertIn("官杀、印、禄不得直接改称财星", str(instruction))
        self.assertIn("财富结构分：X/9", str(instruction))
        self.assertIn("命理年收入能力区间", str(instruction))
        self.assertIn("不等同现实收入", str(instruction))
        self.assertIn("1000 万元小富", str(instruction))
        self.assertIn("5000 万元中富", str(instruction))
        self.assertIn("月令本气、司令与透藏会局", str(instruction))
        self.assertIn("丁火以壬为正官、癸为七杀", str(instruction))
        self.assertIn("不能据此直接定食神格", str(instruction))
        self.assertIn("格局框架资料不能直接证明", str(instruction))
        self.assertIn("theory three", str(instruction))

    def test_bazi_finalization_replaces_incomplete_chart_pillar_rows(self) -> None:
        rendered = _ensure_bazi_citation_footer(
            "## 一、命盘\n**天干：** 甲　己　丁\n**地支：** 戌　巳",
            [
                ToolExchange(
                    tool_name="bazi",
                    tool_payload={"action": "chart"},
                    tool_result={
                        "ok": True,
                        "action": "chart",
                        "result": {
                            "四柱": [
                                {"柱": "年柱", "干支": "甲戌"},
                                {"柱": "月柱", "干支": "己巳"},
                                {"柱": "日柱", "干支": "丁巳"},
                                {"柱": "时柱", "干支": "甲辰"},
                            ]
                        },
                    },
                )
            ],
        )

        self.assertIn("**天干：** 甲　己　丁　甲", rendered)
        self.assertIn("**地支：** 戌　巳　巳　辰", rendered)
        self.assertNotIn("**天干：** 甲　己　丁\n", rendered)

    def test_bazi_finalization_inserts_verified_resolve_pillar_rows(self) -> None:
        rendered = _ensure_bazi_citation_footer(
            "## 原局\n丁火生于巳月。",
            [
                ToolExchange(
                    tool_name="bazi",
                    tool_payload={
                        "action": "resolve_pillars",
                        "yearPillar": "甲戌",
                        "monthPillar": "己巳",
                        "dayPillar": "丁巳",
                        "hourPillar": "甲辰",
                    },
                    tool_result={"ok": True, "action": "resolve_pillars"},
                )
            ],
        )

        self.assertTrue(rendered.startswith("## 命盘（排盘事实）"))
        self.assertIn("**天干：** 甲　己　丁　甲", rendered)
        self.assertIn("**地支：** 戌　巳　巳　辰", rendered)

    def test_bazi_citation_footer_recognizes_markdown_spacing_variants(self) -> None:
        final_text = "## 参考依据\n- **《穷通宝鉴》·调候方法**：支持调候分析。"
        tool_history = [
            ToolExchange(
                tool_name="knowledge",
                tool_payload={"action": "search", "namespace": "bazi-theory"},
                tool_result={
                    "ok": True,
                    "action": "search",
                    "results": [
                        {
                            "text": "reviewed theory",
                            "source_id": "source-1",
                            "chunk_id": "chunk-1",
                            "source_title": "穷通宝鉴",
                            "heading": "调候方法",
                        }
                    ],
                },
            )
        ]

        rendered = _ensure_bazi_citation_footer(final_text, tool_history)

        self.assertEqual(rendered.count("《穷通宝鉴》"), 1)
        self.assertNotIn("\n\n参考依据：", rendered)

    def test_bazi_finalization_repairs_crossed_citation_pairs(self) -> None:
        tools = ToolRegistry()
        tools.register(
            "bazi",
            lambda payload: {"ok": True, "action": payload["action"], "result": {}},
        )
        tools.register(
            "knowledge",
            lambda payload: {
                "ok": True,
                "action": "search",
                "results": [
                    {"text": "one", "source_id": "source-1", "chunk_id": "chunk-1", "source_title": "穷通宝鉴", "heading": "调候方法"},
                    {"text": "two", "source_id": "source-2", "chunk_id": "chunk-2", "source_title": "子平真诠", "heading": "格局方法"},
                ],
            },
        )
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="bazi", tool_payload={"action": "resolve_pillars"}),
                LLMReply(
                    tool_name="knowledge",
                    tool_payload={
                        "action": "search",
                        "namespace": "bazi-theory",
                        "query": "丁火",
                    },
                ),
                contracted_final_reply(
                    "交叉引用：source_id: source-1; chunk_id: chunk-2；"
                    "source_id: source-2; chunk_id: chunk-1"
                ),
            ]
        )

        events = RuntimeLoop(llm, tools, InMemoryRunHistory()).run(
            session_id="session",
            message="分析四柱",
            agent=AgentSpec(
                agent_id="bazi",
                role="test",
                allowed_tools=["bazi", "knowledge"],
            ),
        )

        final_text = events[-1].payload["text"]
        self.assertIn("《穷通宝鉴》 · 调候方法", final_text)
        self.assertIn("《子平真诠》 · 格局方法", final_text)
        self.assertNotIn("source_id", final_text)
        self.assertNotIn("chunk_id", final_text)

    def test_bazi_finalization_keeps_citations_inside_feishu_card_protocol(self) -> None:
        tools = ToolRegistry()
        tools.register(
            "bazi",
            lambda payload: {"ok": True, "action": payload["action"], "result": {}},
        )
        tools.register(
            "knowledge",
            lambda payload: {
                "ok": True,
                "action": "search",
                "results": [
                    {
                        "text": "theory",
                        "source_id": "source-card",
                        "chunk_id": "chunk-card",
                        "source_title": "穷通宝鉴",
                        "heading": "调候方法",
                    }
                ],
            },
        )
        card_reply = (
            "排盘完成。\n"
            "```feishu_card\n"
            '{"title":"八字分析","summary":"文化研究结论",'
            '"sections":[{"title":"排盘事实","items":["丁火日主"]}],'
            '"risk_notice":"文化研究边界"}\n'
            "```"
        )
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="bazi", tool_payload={"action": "resolve_pillars"}),
                LLMReply(
                    tool_name="knowledge",
                    tool_payload={
                        "action": "search",
                        "namespace": "bazi-theory",
                        "query": "丁火",
                    },
                ),
                contracted_final_reply(card_reply),
            ]
        )
        runtime = RuntimeLoop(llm, tools, InMemoryRunHistory())

        events = runtime.run(
            session_id="session",
            message="分析四柱",
            agent=AgentSpec(
                agent_id="bazi",
                role="test",
                allowed_tools=["bazi", "knowledge"],
            ),
        )

        raw_text = events[-1].payload["text"]
        durable_text = normalize_feishu_durable_text(raw_text)
        self.assertTrue(raw_text.rstrip().endswith("```"))
        self.assertIn("《穷通宝鉴》 · 调候方法", durable_text)
        self.assertNotIn("source-card", durable_text)
        self.assertNotIn("chunk-card", durable_text)

    def test_bazi_http_finalization_preserves_complete_markdown_inside_protocol_shell(self) -> None:
        raw = (
            "## 命盘\n命盘正文。\n"
            "```feishu_card\n"
            "## 原局格局喜用\n原局正文。\n"
            "## 大运\n大运正文。\n"
            "## 健康注意\n健康正文。\n"
            "## 学历\n学历正文。\n"
            "## 事业\n事业正文。\n"
            "## 婚姻\n婚姻正文。\n"
            "## 六亲\n六亲正文。\n"
            "## 财富等级\n财富正文。\n"
            "## 过三关\n2018｜搬家｜流年戊戌；大运壬申；原局辰戌冲。\n"
            "## 参考依据\n《滴天髓》·原文\n"
            "```"
        )

        rendered = _ensure_bazi_citation_footer(raw, [], channel_id="http")

        self.assertEqual(missing_bazi_sections(rendered), [])
        self.assertNotIn("```feishu_card", rendered)
        self.assertIn("## 原局格局喜用", rendered)
        self.assertIn("## 参考依据", rendered)

    def test_bazi_finalization_adds_bounded_parent_health_after_visible_cleanup(self) -> None:
        raw = (
            "## 八、六亲\n"
            "母亲：2021年家事操心较多。\n"
            "## 九、财富等级\n"
            "财富结构分：6/9。"
        )

        rendered = _ensure_bazi_citation_footer(raw, [], channel_id="http")

        self.assertIn("父亲：本轮未形成可靠高信号健康应期", rendered)
        self.assertIn("母亲：本轮未形成可靠高信号健康应期", rendered)

    def test_bazi_finalization_recovers_full_lark_card_json_without_visible_leak(self) -> None:
        tools = ToolRegistry()
        tools.register(
            "bazi",
            lambda payload: {"ok": True, "action": payload["action"], "result": {}},
        )
        tools.register(
            "knowledge",
            lambda payload: {
                "ok": True,
                "action": "search",
                "results": [
                    {
                        "text": "调候先看月令寒暖燥湿。",
                        "source_id": "source-lark",
                        "chunk_id": "chunk-lark",
                        "source_title": "穷通宝鉴",
                        "heading": "调候方法",
                    }
                ],
            },
        )
        full_card_json = (
            "排盘完成。\n```json\n"
            '{"config":{"wide_screen_mode":true},'
            '"header":{"title":{"tag":"plain_text","content":"八字文化分析"}},'
            '"elements":[{"tag":"markdown","content":"**一、命盘**\\n- 丁火日主"}]}'
            "\n```"
        )
        llm = ScriptedLLMClient(
            [
                LLMReply(tool_name="bazi", tool_payload={"action": "resolve_pillars"}),
                LLMReply(
                    tool_name="knowledge",
                    tool_payload={
                        "action": "search",
                        "namespace": "bazi-theory",
                        "query": "丁火 调候",
                    },
                ),
                contracted_final_reply(full_card_json),
            ]
        )

        events = RuntimeLoop(llm, tools, InMemoryRunHistory()).run(
            session_id="session",
            message="分析四柱",
            agent=AgentSpec(
                agent_id="bazi",
                role="test",
                allowed_tools=["bazi", "knowledge"],
            ),
        )

        raw_text = events[-1].payload["text"]
        card = render_final_reply_card(raw_text)
        body_text = "\n".join(
            str(item.get("content") or "") for item in card["body"]["elements"]
        )
        self.assertIn("《穷通宝鉴》 · 调候方法", body_text)
        self.assertIn("🗂️ 命盘", body_text)
        self.assertNotIn('"wide_screen_mode"', body_text)
        self.assertNotIn('"elements"', body_text)
        self.assertNotIn("source-lark", body_text)
        self.assertNotIn("chunk-lark", body_text)

    def test_bazi_finalization_removes_future_years_and_question_menu(self) -> None:
        content = (
            "月令当权，先看食伤、财与印比的作用。\n"
            "一、命盘\n甲戌　己巳　丁巳　甲辰\n"
            "二、原局格局喜用\n月令与透干形成食伤、财与印比的作用链。\n"
            "三、大运\n本轮未复算。\n"
            "四、健康注意\n注意作息。\n"
            "五、学历\n学习倾向待核验。\n"
            "六、事业\n适合专业输出。\n"
            "七、婚姻\n关系倾向待核验。\n"
            "八、父母\n家庭关系待核验。\n"
            "九、子女\n子女信息待核验。\n"
            "十、财富等级\n中等层级，取决于现实执行。\n"
            "十一、过三关\n缺少大运，无法可靠定位流年。\n"
            "2026-2028年：未来事业变化。\n"
            "哪几年适合结婚\n哪步运财运更强\n是否适合创业或换城市"
        )
        raw = (
            "排盘完成。\n```feishu_card\n"
            + '{"title":"八字分析","sections":[{"items":'
            + json.dumps([content], ensure_ascii=False)
            + "}]}\n```"
        )
        rendered = _ensure_bazi_citation_footer(raw, [])
        _, protocol = parse_feishu_card_protocol(rendered)

        self.assertIsNotNone(protocol)
        titles = [section.title for section in protocol.sections]
        self.assertEqual(
            titles,
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
            ],
        )
        durable = normalize_feishu_durable_text(rendered)
        self.assertIn("月令当权，先看食伤、财与印比的作用", durable)
        self.assertNotIn("2026-2028年", durable)
        self.assertIn("月令与透干形成食伤、财与印比的作用链", durable)
        self.assertIn("家庭关系待核验", durable)
        self.assertIn("子女信息待核验", durable)
        for forbidden in (
            "哪几年适合结婚",
            "哪步运财运更强",
            "是否适合创业或换城市",
            "详情",
        ):
            self.assertNotIn(forbidden, durable)

    def test_bazi_plain_markdown_builds_fixed_feishu_sections(self) -> None:
        headings = [
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
        ]
        text = "\n\n".join(
            f"{index}、{heading}\n{heading}内容。"
            for index, heading in enumerate(headings, start=1)
        )

        rendered = _ensure_bazi_citation_footer(text, [], channel_id="feishu")
        visible, protocol = parse_feishu_card_protocol(rendered)

        self.assertEqual(visible, "排盘与解读完成。")
        self.assertIsNotNone(protocol)
        self.assertEqual([section.title for section in protocol.sections], headings)
        self.assertNotIn("详情", normalize_feishu_durable_text(rendered))

    def test_bazi_verification_items_render_year_titles_without_literal_markers(self) -> None:
        text = (
            "十、过三关\n"
            "- **2012年 | 学业结果或升学分流明显 | **流年壬辰，处辛未大运。\n"
            "- **2020年 | 感情推进或工作压力增大 | **流年庚子，处壬申大运。"
        )

        rendered = _ensure_bazi_citation_footer(text, [], channel_id="feishu")
        _, protocol = parse_feishu_card_protocol(rendered)
        card = render_final_reply_card(rendered)
        body_text = "\n".join(
            str(item.get("content") or "") for item in card["body"]["elements"]
        )

        self.assertIsNotNone(protocol)
        section = next(item for item in protocol.sections if item.title == "过三关")
        self.assertEqual(len(section.items), 2)
        self.assertEqual(
            section.items[0],
            "**2012年**｜学业结果｜流年壬辰，处辛未大运。",
        )
        self.assertIn("- **2012年**｜学业结果", body_text)
        self.assertNotIn("**2012年 |", body_text)
        self.assertNotIn("| **流年", body_text)

    def test_bazi_verification_items_split_multiple_inline_years(self) -> None:
        text = (
            "十、过三关\n"
            "2012-2013｜升学方向调整｜辛未大运引动原局。 "
            "2016｜工作环境切换｜壬申大运启动。 "
            "2024｜岗位或关系调整｜甲辰流年引动原局。"
        )

        rendered = _ensure_bazi_citation_footer(text, [], channel_id="feishu")
        _, protocol = parse_feishu_card_protocol(rendered)
        section = next(item for item in protocol.sections if item.title == "过三关")

        self.assertEqual(len(section.items), 3)
        self.assertTrue(section.items[0].startswith("**2012-2013**｜"))
        self.assertTrue(section.items[1].startswith("**2016**｜"))
        self.assertTrue(section.items[2].startswith("**2024**｜"))

    def test_bazi_verification_items_split_inline_markdown_bullets(self) -> None:
        text = (
            "十、过三关\n"
            "- **2014**｜待核验恋爱机会｜流年：甲午；大运：辛未；原局：午为桃花。 "
            "- 2018｜待核验父亲脾胃检查｜流年：戊戌；大运：壬申；原局：年柱伏吟。 "
            "- 2024｜待核验母亲脾胃检查｜流年：甲辰；大运：壬申；原局：辰戌冲。"
        )

        rendered = _ensure_bazi_citation_footer(text, [], channel_id="feishu")
        _, protocol = parse_feishu_card_protocol(rendered)
        section = next(item for item in protocol.sections if item.title == "过三关")

        self.assertEqual(len(section.items), 3)
        self.assertTrue(section.items[0].startswith("**2014**｜"))
        self.assertTrue(section.items[1].startswith("**2018**｜"))
        self.assertTrue(section.items[2].startswith("**2024**｜"))

    def test_bazi_verification_items_keep_one_concrete_event(self) -> None:
        text = (
            "十、过三关\n"
            "- 2017｜工作起步或社会身份进入新阶段｜"
            "推算原因：流年：丁酉；大运：壬申；原局：财官入局。"
        )

        rendered = _ensure_bazi_citation_footer(text, [], channel_id="feishu")
        _, protocol = parse_feishu_card_protocol(rendered)
        section = next(item for item in protocol.sections if item.title == "过三关")

        self.assertEqual(
            section.items,
            ["**2017**｜工作起步｜推算原因：流年：丁酉；大运：壬申；原局：财官入局。"],
        )

    def test_bazi_verification_items_expand_bare_topic(self) -> None:
        text = (
            "十、过三关\n"
            "- 2024｜母亲或家宅事务变化｜"
            "推算原因：流年：甲辰；大运：壬申；原局：父母宫被引动。"
        )

        rendered = _ensure_bazi_citation_footer(text, [], channel_id="feishu")
        _, protocol = parse_feishu_card_protocol(rendered)
        section = next(item for item in protocol.sections if item.title == "过三关")

        self.assertEqual(
            section.items,
            ["**2024**｜母亲健康出现需核验事项｜推算原因：流年：甲辰；大运：壬申；原局：父母宫被引动。"],
        )


if __name__ == "__main__":
    unittest.main()
