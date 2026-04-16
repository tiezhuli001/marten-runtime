import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient

from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.self_improve.recorder import SelfImproveRecorder
from marten_runtime.self_improve.review_dispatcher import SelfImproveReviewDispatcher
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from tests.http_app_support import build_test_app
from tests.support.feishu_builders import FakeDeliveryClient


class SelfImproveIntegrationTests(unittest.TestCase):
    def test_successful_turn_can_trigger_hidden_review_and_persist_skill_candidate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            app = build_test_app()
            runtime = app.state.runtime
            isolated_store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            recorder = SelfImproveRecorder(isolated_store)
            dispatcher = SelfImproveReviewDispatcher(
                store=isolated_store,
                subagent_service=runtime.subagent_service,
                run_history=runtime.run_history,
                skill_service=runtime.skill_service,
                app_id=runtime.app_manifest.app_id,
                agent_id=runtime.default_agent.agent_id,
            )
            runtime.self_improve_store = isolated_store
            runtime.runtime_loop.self_improve_recorder = recorder
            runtime.runtime_loop.self_improve_post_commit_callback = dispatcher.dispatch_pending_triggers
            runtime.subagent_service.set_terminal_callback(dispatcher.handle_terminal_task)

            scripted = ScriptedLLMClient(
                [
                    LLMReply(final_text="已经处理完成。"),
                    LLMReply(
                        final_text=(
                            '{"lesson_proposals":[],"skill_proposals":[{"title":"Provider Timeout Recovery","slug":"provider-timeout-recovery","summary":"Narrow the path after repeated timeout.","trigger_conditions":["repeated provider timeout"],"body_markdown":"# Provider Timeout Recovery\\n\\n- Keep the path narrow.","rationale":"Observed repeated timeout followed by a successful narrow retry.","source_run_ids":["run_source"],"source_fingerprints":["main|请总结今天的问题"],"confidence":0.94}],"confidence":0.94,"classification_rationale":"Reusable workflow"}'
                        )
                    ),
                ]
            )
            runtime.runtime_loop.llm = scripted
            runtime.llm_client_factory.cache_client("default", scripted)
            runtime.llm_client_factory.cache_client("minimax_coding", scripted)

            runtime.session_store.create(
                session_id="sess_seed",
                conversation_id="seed-conv",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            seeded_run_1 = runtime.run_history.start(
                session_id="sess_seed",
                trace_id="trace_fail_1",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            runtime.run_history.finish(seeded_run_1.run_id, delivery_status="error")
            seeded_run_2 = runtime.run_history.start(
                session_id="sess_seed",
                trace_id="trace_fail_2",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            runtime.run_history.finish(seeded_run_2.run_id, delivery_status="error")
            recorder.record_failure(
                agent_id="main",
                run_id=seeded_run_1.run_id,
                trace_id="trace_fail_1",
                session_id="sess_seed",
                error_code="PROVIDER_TIMEOUT",
                error_stage="llm",
                summary="provider timed out",
                provider_name="minimax",
                message="请总结今天的问题",
            )
            recorder.record_failure(
                agent_id="main",
                run_id=seeded_run_2.run_id,
                trace_id="trace_fail_2",
                session_id="sess_seed",
                error_code="PROVIDER_TIMEOUT",
                error_stage="llm",
                summary="provider timed out again",
                provider_name="minimax",
                message="请总结今天的问题",
            )

            with TestClient(app) as client:
                response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "self-improve-review",
                        "message_id": "msg_self_improve",
                        "body": "请总结今天的问题",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("已经处理完成", response.json()["events"][-1]["payload"]["text"])

                for _ in range(50):
                    skill_candidates = runtime.self_improve_store.list_skill_candidates(
                        agent_id="main",
                        limit=10,
                        status="pending",
                    )
                    processed = runtime.self_improve_store.list_review_triggers(
                        agent_id="main",
                        limit=10,
                        status="processed",
                    )
                    if skill_candidates and processed:
                        break
                    time.sleep(0.02)

            self.assertEqual(len(skill_candidates), 1)
            self.assertEqual(skill_candidates[0].slug, "provider-timeout-recovery")
            self.assertTrue(processed)

    def test_feishu_turn_keeps_main_reply_clean_and_emits_followup_skill_candidate_notification(self) -> None:
        with TemporaryDirectory() as tmpdir:
            app = build_test_app()
            runtime = app.state.runtime
            isolated_store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            recorder = SelfImproveRecorder(isolated_store)
            fake_delivery = FakeDeliveryClient()
            dispatcher = SelfImproveReviewDispatcher(
                store=isolated_store,
                subagent_service=runtime.subagent_service,
                run_history=runtime.run_history,
                skill_service=runtime.skill_service,
                feishu_delivery=fake_delivery,
                app_id=runtime.app_manifest.app_id,
                agent_id=runtime.default_agent.agent_id,
            )
            runtime.self_improve_store = isolated_store
            runtime.feishu_delivery = fake_delivery
            runtime.feishu_socket_service.delivery_client = fake_delivery
            runtime.subagent_service.feishu_delivery = fake_delivery
            runtime.runtime_loop.self_improve_recorder = recorder
            runtime.runtime_loop.self_improve_post_commit_callback = dispatcher.dispatch_pending_triggers
            runtime.subagent_service.set_terminal_callback(dispatcher.handle_terminal_task)

            scripted = ScriptedLLMClient(
                [
                    LLMReply(final_text="已经处理完成。"),
                    LLMReply(
                        final_text=(
                            '{"lesson_proposals":[],"skill_proposals":[{"title":"Provider Timeout Recovery","slug":"provider-timeout-recovery","summary":"Narrow the path after repeated timeout.","trigger_conditions":["repeated provider timeout"],"body_markdown":"# Provider Timeout Recovery\\n\\n- Keep the path narrow.","rationale":"Observed repeated timeout followed by a successful narrow retry.","source_run_ids":["run_source"],"source_fingerprints":["main|请总结今天的问题"],"confidence":0.94}],"confidence":0.94,"classification_rationale":"Reusable workflow"}'
                        )
                    ),
                ]
            )
            runtime.runtime_loop.llm = scripted
            runtime.llm_client_factory.cache_client("default", scripted)
            runtime.llm_client_factory.cache_client("minimax_coding", scripted)

            runtime.session_store.create(
                session_id="sess_seed",
                conversation_id="oc_self_improve_chat",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            seeded_run_1 = runtime.run_history.start(
                session_id="sess_seed",
                trace_id="trace_fail_1",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            runtime.run_history.finish(seeded_run_1.run_id, delivery_status="error")
            seeded_run_2 = runtime.run_history.start(
                session_id="sess_seed",
                trace_id="trace_fail_2",
                config_snapshot_id="cfg_bootstrap",
                bootstrap_manifest_id="boot_default",
            )
            runtime.run_history.finish(seeded_run_2.run_id, delivery_status="error")
            recorder.record_failure(
                agent_id="main",
                run_id=seeded_run_1.run_id,
                trace_id="trace_fail_1",
                session_id="sess_seed",
                channel_id="feishu",
                error_code="PROVIDER_TIMEOUT",
                error_stage="llm",
                summary="provider timed out",
                provider_name="minimax",
                message="请总结今天的问题",
            )
            recorder.record_failure(
                agent_id="main",
                run_id=seeded_run_2.run_id,
                trace_id="trace_fail_2",
                session_id="sess_seed",
                channel_id="feishu",
                error_code="PROVIDER_TIMEOUT",
                error_stage="llm",
                summary="provider timed out again",
                provider_name="minimax",
                message="请总结今天的问题",
            )

            payload = {
                "schema": "2.0",
                "header": {
                    "event_id": "evt_self_improve_feishu_1",
                    "event_type": "im.message.receive_v1",
                },
                "event": {
                    "sender": {
                        "sender_type": "user",
                        "sender_id": {
                            "user_id": "user_self_improve_1",
                        },
                    },
                    "message": {
                        "message_id": "msg_self_improve_1",
                        "chat_id": "oc_self_improve_chat",
                        "chat_type": "p2p",
                        "content": json.dumps({"text": "请总结今天的问题"}),
                    },
                },
            }

            result = runtime.feishu_socket_service.handle_event_payload(payload)
            self.assertEqual(result.status, "accepted")

            for _ in range(80):
                skill_candidates = runtime.self_improve_store.list_skill_candidates(
                    agent_id="main",
                    limit=10,
                    status="pending",
                )
                if skill_candidates and len(fake_delivery.payloads) >= 2:
                    break
                time.sleep(0.02)

            session_id = result.body["session_id"]
            session = runtime.session_store.get(session_id)
            visible_history = [item.content for item in session.history]

        self.assertEqual(len(skill_candidates), 1)
        self.assertEqual(skill_candidates[0].slug, "provider-timeout-recovery")
        self.assertGreaterEqual(len(fake_delivery.payloads), 2)
        main_payload_texts = [item.text for item in fake_delivery.payloads if "已经处理完成" in item.text]
        review_payload_texts = [
            item.text for item in fake_delivery.payloads if "provider-timeout-recovery" in item.text
        ]
        self.assertTrue(main_payload_texts)
        self.assertTrue(review_payload_texts)
        self.assertFalse(
            any("subagent task completed: self-improve-review" in item for item in visible_history)
        )


if __name__ == "__main__":
    unittest.main()
