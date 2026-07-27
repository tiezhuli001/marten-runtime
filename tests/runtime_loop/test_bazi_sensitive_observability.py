from __future__ import annotations

import json
import unittest

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.observability.langfuse import build_langfuse_observer
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.runtime.observation_policy import REDACTED_TEXT, project_tool_result
from marten_runtime.tools.registry import ToolRegistry
from tests.support.finalization_contracts import contracted_final_reply
from tests.support.langfuse_fakes import FakeLangfuseClient


MESSAGE = "1988-02-15 23:30，出生地四川省成都市武侯区，咨询事业变化"
PLACE = "四川省成都市武侯区"
FINAL_TEXT = "完整解盘：辛丑日主，事业咨询结论"
FULL_CHART = "完整命盘-戊辰-甲寅-辛丑-戊子"


def bazi_payload() -> dict:
    return {
        "action": "chart",
        "gender": "male",
        "birthYear": 1988,
        "birthMonth": 2,
        "birthDay": 15,
        "birthHour": 23,
        "birthMinute": 30,
        "birthPlace": PLACE,
        "timeBasis": "true_solar",
    }


def bazi_result() -> dict:
    return {
        "ok": True,
        "protocolVersion": "1",
        "requestId": "bazi_sensitive_request",
        "action": "chart",
        "resultSchemaVersion": "bazi.chart.v1",
        "engine": {"name": "taibu-core-marten", "version": "3.4.0-marten.1"},
        "inputFingerprint": "sha256:" + "a" * 64,
        "timeBasis": {
            "requested": "true_solar",
            "timezone": "Asia/Shanghai",
            "sourceTimeStandard": "recorded_civil",
            "sourceUtcOffsetMinutes": 480,
            "dstAdjustmentMinutes": 0,
            "sourceCalendarType": "solar",
            "sourceIsLeapMonth": False,
            "effectiveCalendarType": "solar",
            "effectiveBirthDateTime": "1988-02-15T22:12:00",
            "trueSolarAlgorithm": "taibu_true_solar_v1",
            "dayBoundaryPolicy": "lunar_javascript_sect1",
            "qiyunMethod": "lunar_javascript_yun_sect1",
            "placeResolution": {
                "provider": "amap",
                "resolverVersion": "taibu-14860a2-marten-v1",
                "formattedAddress": PLACE,
                "adcode": "510107",
                "level": "区县",
                "coordinateSystem": "gcj02",
                "resolvedLongitude": 104.040123,
                "resolvedLatitude": 30.640456,
            },
        },
        "result": {"完整命盘": FULL_CHART},
        "result_text": FINAL_TEXT,
        "degradedDiagnostics": [],
    }


class RecordingSelfImprove:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def record_failure(self, **kwargs) -> None:
        self.calls.append(("failure", kwargs))

    def record_recovery(self, **kwargs) -> None:
        self.calls.append(("recovery", kwargs))

    def record_successful_tool_episode(self, **kwargs) -> None:
        self.calls.append(("success", kwargs))


class BaziSensitiveObservabilityTests(unittest.TestCase):
    def _observer(self, client: FakeLangfuseClient):
        return build_langfuse_observer(
            env={
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "https://langfuse.example",
            },
            client=client,
        )

    def _run_success(self, *, agent_policy: str = "sensitive_bazi"):
        client = FakeLangfuseClient()
        history = InMemoryRunHistory()
        tools = ToolRegistry()
        tools.register(
            "bazi",
            lambda payload: bazi_result(),
            observation_policy="sensitive_bazi",
        )
        recorder = RecordingSelfImprove()
        runtime = RuntimeLoop(
            ScriptedLLMClient(
                [
                    LLMReply(tool_name="bazi", tool_payload=bazi_payload()),
                    contracted_final_reply(FINAL_TEXT),
                ]
            ),
            tools,
            history,
            langfuse_observer=self._observer(client),
            self_improve_recorder=recorder,
        )
        events = runtime.run(
            session_id="sess_sensitive",
            message=MESSAGE,
            trace_id="trace_sensitive",
            agent=AgentSpec(
                agent_id="bazi",
                role="bazi_consultant",
                allowed_tools=["bazi"],
                observation_policy=agent_policy,
            ),
        )
        return client, history.get(events[-1].run_id), recorder, events

    def test_sensitive_agent_projects_trace_generation_tool_history_and_finalization(self) -> None:
        client, run, recorder, events = self._run_success()

        self.assertEqual(events[-1].payload["text"], FINAL_TEXT)
        self.assertEqual(client.traces[0]["input_text"], REDACTED_TEXT)
        self.assertTrue(
            all(item["input_payload"]["message"] == REDACTED_TEXT for item in client.generations)
        )
        self.assertEqual(client.finalizations[0]["final_text"], REDACTED_TEXT)
        self.assertEqual(run.final_text, REDACTED_TEXT)
        self.assertEqual(run.observation_policy, "sensitive_bazi")
        self.assertEqual(run.tool_calls[0]["tool_payload"]["action"], "chart")
        self.assertTrue(run.tool_calls[0]["tool_result"]["resultPresent"])
        self.assertEqual(run.tool_outcome_summaries, [])
        self.assertEqual(recorder.calls, [])

        observed = json.dumps(
            {
                "traces": client.traces,
                "generations": client.generations,
                "tool_spans": client.tool_spans,
                "finalizations": client.finalizations,
                "history": run.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        for sensitive in (
            MESSAGE,
            PLACE,
            "1988-02-15",
            "23:30",
            "104.040123",
            "30.640456",
            FULL_CHART,
            FINAL_TEXT,
        ):
            self.assertNotIn(sensitive, observed)

    def test_sensitive_tool_descriptor_projects_payload_and_result_for_standard_agent(self) -> None:
        client, run, _, _ = self._run_success(agent_policy="standard")

        tool_observation = json.dumps(
            {"span": client.tool_spans, "history": run.tool_calls},
            ensure_ascii=False,
        )
        self.assertNotIn(PLACE, tool_observation)
        self.assertNotIn("104.040123", tool_observation)
        self.assertNotIn(FULL_CHART, tool_observation)
        self.assertEqual(run.final_text, FINAL_TEXT)

    def test_sensitive_tool_failure_overrides_standard_agent_observation_policy(self) -> None:
        client = FakeLangfuseClient()
        history = InMemoryRunHistory()
        tools = ToolRegistry()

        def fail(payload: dict) -> dict:
            raise RuntimeError(f"failed for {PLACE} at 1988-02-15 23:30")

        tools.register("bazi", fail, observation_policy="sensitive_bazi")
        recorder = RecordingSelfImprove()
        runtime = RuntimeLoop(
            ScriptedLLMClient([LLMReply(tool_name="bazi", tool_payload=bazi_payload())]),
            tools,
            history,
            langfuse_observer=self._observer(client),
            self_improve_recorder=recorder,
        )

        events = runtime.run(
            session_id="sess_sensitive_failure",
            message=MESSAGE,
            agent=AgentSpec(
                agent_id="main",
                role="test",
                allowed_tools=["bazi"],
                observation_policy="standard",
            ),
        )

        self.assertEqual(events[-1].event_type, "error")
        self.assertEqual(len(recorder.calls), 1)
        evidence = json.dumps(recorder.calls, ensure_ascii=False)
        self.assertIn(REDACTED_TEXT, evidence)
        self.assertNotIn(PLACE, evidence)
        self.assertNotIn("1988-02-15", evidence)

    def test_sensitive_projection_keeps_only_knowledge_citation_identifiers(self) -> None:
        projected = project_tool_result(
            {
                "ok": True,
                "retrieval_mode": "hybrid_rerank",
                "vector_status": "available",
                "rerank_status": "available",
                "results": [
                    {
                        "source_id": "ksrc_theory",
                        "chunk_id": "kchk_rule",
                        "text": "sensitive theory body",
                        "score": 0.99,
                    }
                ],
            },
            "sensitive_bazi",
        )

        self.assertEqual(
            projected["results"],
            [{"source_id": "ksrc_theory", "chunk_id": "kchk_rule"}],
        )
        self.assertEqual(projected["vector_status"], "available")
        self.assertEqual(projected["retrieval_mode"], "hybrid_rerank")
        self.assertNotIn("sensitive theory body", json.dumps(projected))


if __name__ == "__main__":
    unittest.main()
