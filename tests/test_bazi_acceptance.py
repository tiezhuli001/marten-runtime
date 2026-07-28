from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from marten_runtime.evals.scripted_runtime import ScriptedEvalLLMClient
from marten_runtime.knowledge.embeddings import FakeEmbeddingAdapter
from marten_runtime.knowledge.rerankers import FakeReranker
from tests.http_app_support import build_test_app
from tests.support.feishu_builders import FakeDeliveryClient


REPO_ROOT = Path(__file__).resolve().parents[1]
TOKEN = "bazi-operator-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BIRTH_REQUEST = (
    "男，农历1988年2月15日上午10点20分，四川省成都市武侯区。"
    "请按子平格局法和盲派分析。"
)


class BaziVerticalSliceAcceptanceTests(unittest.TestCase):
    def _app(self):
        app = build_test_app(env_overrides={"KNOWLEDGE_OPERATOR_TOKEN": TOKEN})
        runtime = app.state.runtime
        service = runtime.knowledge_service
        service.embedding_adapter = FakeEmbeddingAdapter(
            dimension=service.config.embedding.dimension,
            model_id=service.config.embedding.model,
        )
        service.reranker_adapter = FakeReranker(model_id=service.config.reranker.model)
        runtime.bazi_bridge_manager.bridge_path = (
            REPO_ROOT / "third_party" / "taibu_bridge" / "index.mjs"
        )
        return app

    def _configure_llm(self, runtime) -> ScriptedEvalLLMClient:  # noqa: ANN001
        llm = ScriptedEvalLLMClient(
            case_id="bazi_theory_citation_cn",
            provider_name="scripted-bazi",
            model_name="scripted-bazi-local",
            context={},
        )
        runtime.runtime_loop.llm = llm
        for profile_name in runtime.models_config.profiles:
            runtime.llm_client_factory.cache_client(profile_name, llm)
        return llm

    def _upload_theory(self, client: TestClient, runtime) -> tuple[str, str]:  # noqa: ANN001
        response = client.post(
            "/knowledge/namespaces/bazi-theory/uploads",
            headers=AUTH,
            data={
                "title": "Marten 八字方法纲要（调候）",
                "uri": "repo://tests/fixtures/knowledge/bazi_theory_minimal.md",
                "version": "1.0.0",
                "corpus_type": "theory",
                "school": "engine-neutral",
                "review_status": "reviewed",
                "license": "CC0-1.0",
                "provenance": "Original Marten deterministic acceptance fixture",
                "calculation_scope": "four-pillars-and-dayun-output-boundaries",
                "method": "separate-calendar-facts-from-interpretation",
            },
            files={
                "file": (
                    "bazi_theory_minimal.md",
                    (REPO_ROOT / "tests" / "fixtures" / "knowledge" / "bazi_theory_minimal.md").read_bytes(),
                    "text/markdown",
                )
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        deadline = time.monotonic() + 3
        status = {}
        while time.monotonic() < deadline:
            status = runtime.knowledge_service.ingest_status(
                namespace="bazi-theory", job_id=body["job_id"]
            )
            if status.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)
        self.assertEqual(status.get("status"), "completed", status)
        source = runtime.knowledge_service.store.get_source(
            "bazi-theory", body["source_id"]
        )
        self.assertEqual(source.metadata["corpus_type"], "theory")
        self.assertEqual(source.metadata["review_status"], "reviewed")
        chunks = runtime.knowledge_service.store.list_chunks(
            "bazi-theory", source_id=body["source_id"]
        )
        self.assertTrue(chunks)
        return body["source_id"], chunks[0].chunk_id

    def test_operator_upload_http_and_feishu_share_bazi_rag_contract(self) -> None:
        app = self._app()
        runtime = app.state.runtime
        self._configure_llm(runtime)
        delivery = FakeDeliveryClient()
        runtime.feishu_delivery = delivery
        runtime.feishu_socket_service.delivery_client = delivery

        with TestClient(app) as client:
            source_id, _ = self._upload_theory(client, runtime)
            http = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "bazi-http-user",
                    "conversation_id": "bazi-http-acceptance",
                    "message_id": "bazi-http-1",
                    "body": BIRTH_REQUEST,
                },
            )
            self.assertEqual(http.status_code, 200, http.text)
            http_body = http.json()
            http_final = http_body["events"][-1]["payload"]["text"]
            self.assertIn("《Marten 八字方法纲要（调候）》", http_final)
            self.assertNotIn(source_id, http_final)
            self.assertNotIn("chunk_id", http_final)
            second_http = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "bazi-http-user",
                    "conversation_id": "bazi-http-acceptance",
                    "message_id": "bazi-http-2",
                    "body": BIRTH_REQUEST,
                },
            )
            self.assertEqual(second_http.status_code, 200, second_http.text)
            self.assertNotEqual(
                second_http.json()["route_run_id"],
                http_body["route_run_id"],
            )

            feishu_result = runtime.feishu_socket_service.handle_event_payload(
                {
                    "schema": "2.0",
                    "header": {
                        "event_id": "evt_bazi_feishu_acceptance",
                        "event_type": "im.message.receive_v1",
                    },
                    "event": {
                        "sender": {
                            "sender_type": "user",
                            "sender_id": {"user_id": "bazi-feishu-user"},
                        },
                        "message": {
                            "message_id": "msg_bazi_feishu_acceptance",
                            "chat_id": "oc_bazi_consultation",
                            "chat_type": "p2p",
                            "content": json.dumps(
                                {"text": BIRTH_REQUEST}
                            ),
                        },
                    },
                }
            )

        self.assertEqual(feishu_result.status, "accepted")
        final_deliveries = [item for item in delivery.payloads if item.event_type == "final"]
        self.assertEqual(len(final_deliveries), 1)
        self.assertIn("《Marten 八字方法纲要（调候）》", final_deliveries[0].text)
        self.assertNotIn(source_id, final_deliveries[0].text)
        self.assertIsNotNone(final_deliveries[0].card)
        card_text = "\n".join(
            str(item.get("content") or "")
            for item in final_deliveries[0].card["body"]["elements"]
        )
        for section in (
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
        ):
            self.assertIn(f"🗂️ {section}", card_text)
        self.assertNotIn("🗂️ 详情", card_text)

        http_run_id = http_body["events"][-1]["run_id"]
        feishu_run_id = final_deliveries[0].run_id
        http_run = runtime.run_history.get(http_run_id)
        feishu_run = runtime.run_history.get(feishu_run_id)
        self.assertEqual(http_body["routed_agent_id"], "bazi")
        self.assertEqual(http_run.observation_policy, "sensitive_bazi")
        self.assertEqual(feishu_run.observation_policy, "sensitive_bazi")
        self.assertEqual(
            _fingerprint(http_run.tool_calls),
            _fingerprint(feishu_run.tool_calls),
        )
        for run in (http_run, feishu_run):
            self.assertEqual(run.bootstrap_manifest_id, "agent_bazi_full")
            self.assertIsNotNone(run.parent_run_id)
            route_run = runtime.run_history.get(run.parent_run_id)
            self.assertEqual(route_run.observation_policy, "metadata_only")
            self.assertEqual(route_run.bootstrap_manifest_id, "agent_main_routing")
            self.assertEqual(route_run.final_text, "[REDACTED:metadata_only]")
            self.assertEqual(_tool_call_count(run.tool_calls, "bazi"), 2)
            self.assertEqual(_tool_call_count(run.tool_calls, "knowledge"), 1)
            self.assertEqual(
                len(set(_bazi_fingerprints(run.tool_calls))),
                1,
            )
            citations = _citations(run.tool_calls)
            self.assertTrue(citations)
            self.assertTrue(all(item[0] == source_id for item in citations))
            trace = runtime.trace_index[run.trace_id]
            self.assertEqual(trace["run_ids"], [route_run.run_id, run.run_id])
            self.assertIn(run.run_id, trace["run_ids"])
            session = runtime.session_store.get(run.session_id)
            roles = [item.role for item in session.history]
            expected_turns = 2 if run.session_id == http_run.session_id else 1
            self.assertEqual(roles.count("user"), expected_turns)
            self.assertEqual(roles.count("assistant"), expected_turns)
            self.assertEqual(session.active_agent_id, "main")


def _fingerprint(tool_calls: list[dict[str, object]]) -> str:
    for call in tool_calls:
        if call.get("tool_name") == "bazi":
            result = call.get("tool_result") or {}
            return str(result.get("inputFingerprint") or "")
    return ""


def _bazi_fingerprints(tool_calls: list[dict[str, object]]) -> list[str]:
    return [
        str((call.get("tool_result") or {}).get("inputFingerprint") or "")
        for call in tool_calls
        if call.get("tool_name") == "bazi"
    ]


def _citations(tool_calls: list[dict[str, object]]) -> list[tuple[str, str]]:
    citations = []
    for call in tool_calls:
        if call.get("tool_name") != "knowledge":
            continue
        result = call.get("tool_result") or {}
        citations.extend(
            (str(item.get("source_id") or ""), str(item.get("chunk_id") or ""))
            for item in result.get("results") or []
        )
    return citations


def _tool_call_count(tool_calls: list[dict[str, object]], tool_name: str) -> int:
    return sum(1 for call in tool_calls if call.get("tool_name") == tool_name)


if __name__ == "__main__":
    unittest.main()
