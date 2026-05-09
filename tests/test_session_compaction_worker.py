import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from marten_runtime.interfaces.http.app import create_app
from marten_runtime.interfaces.http.bootstrap_runtime import (
    CachedLLMClientFactory,
    build_http_runtime,
)
from marten_runtime.runtime.llm_client import LLMReply, LLMRequest, ScriptedLLMClient
from marten_runtime.runtime.provider_retry import ProviderTransportError
from marten_runtime.session.compaction_worker import SessionCompactionWorker
from marten_runtime.session.models import SessionMessage
from tests.support.session_store_fixtures import temporary_sqlite_session_store


class _FailingLLM:
    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("compact failed")


class _RetryableProviderFailingLLM:
    provider_name = "openai"
    model_name = "gpt-4.1"
    profile_name = "openai_gpt_5_4"

    def complete(self, request):  # noqa: ANN001
        raise ProviderTransportError(
            "PROVIDER_UPSTREAM_UNAVAILABLE",
            "provider_http_error:502:bad gateway",
            retryable=True,
        )


class _SuccessfulLLM:
    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str,
        profile_name: str,
        final_text: str,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.profile_name = profile_name
        self.final_text = final_text
        self.requests = []

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        return LLMReply(final_text=self.final_text)


class _FakeFactory:
    def __init__(self, isolated_client) -> None:  # noqa: ANN001
        self.isolated_client = isolated_client
        self.isolated_requests: list[str | None] = []

    def create_isolated(self, profile_name):  # noqa: ANN001
        self.isolated_requests.append(profile_name)
        return self.isolated_client


class _CountingWorker:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.start_count = 0
        self.stop_count = 0
        self.args = args
        self.kwargs = kwargs

    def start(self) -> None:
        self.start_count += 1

    def stop(self) -> None:
        self.stop_count += 1


class _NoopObserver:
    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


class _NoopFeishuSocket:
    async def stop_background(self) -> None:
        return None


class _NoopSubagentService:
    def shutdown(self) -> None:
        return None


class SessionCompactionWorkerTests(unittest.TestCase):
    def _store(self):
        return self.enterContext(temporary_sqlite_session_store())

    def test_worker_run_once_uses_isolated_client_and_marks_job_succeeded(self) -> None:
        store = self._store()
        session = store.create(
            session_id="sess_source",
            conversation_id="conv-source",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        store.append_message(session.session_id, SessionMessage.user("历史 1"))
        store.append_message(session.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(session.session_id, SessionMessage.user("历史 2"))
        store.append_message(session.session_id, SessionMessage.assistant("历史 2 完成"))
        store.enqueue_compaction_job(
            source_session_id=session.session_id,
            current_message="切换会话",
            preserved_tail_user_turns=1,
            source_message_range=[0, 2],
            snapshot_message_count=len(store.get(session.session_id).history),
            compaction_profile_name="minimax_m2_7_highspeed",
        )
        shared_client = ScriptedLLMClient([LLMReply(final_text="shared should stay idle")])
        isolated_client = ScriptedLLMClient([LLMReply(final_text="当前进展：已压缩。")])
        factory = _FakeFactory(isolated_client)
        worker = SessionCompactionWorker(
            session_store=store,
            llm_client_factory=factory,
            profile_name="openai_gpt_5_4",
        )

        processed = worker.run_once()
        job = store.list_compaction_jobs()[0]

        self.assertTrue(processed)
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["result_reason"], "generated")
        self.assertGreaterEqual(job["compaction_llm_ms"], 0)
        self.assertGreaterEqual(job["persist_ms"], 0)
        self.assertTrue(job["write_applied"])
        self.assertEqual(len(isolated_client.requests), 1)
        self.assertEqual(len(shared_client.requests), 0)
        self.assertEqual(factory.isolated_requests, ["minimax_m2_7_highspeed"])

    def test_worker_run_once_uses_enqueued_snapshot_instead_of_later_messages(self) -> None:
        store = self._store()
        session = store.create(
            session_id="sess_source",
            conversation_id="conv-source",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        store.append_message(session.session_id, SessionMessage.user("历史 1"))
        store.append_message(session.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(session.session_id, SessionMessage.user("历史 2"))
        store.append_message(session.session_id, SessionMessage.assistant("历史 2 完成"))
        snapshot_count = len(store.get(session.session_id).history)
        store.enqueue_compaction_job(
            source_session_id=session.session_id,
            current_message="切换会话",
            preserved_tail_user_turns=1,
            source_message_range=[0, 2],
            snapshot_message_count=snapshot_count,
        )
        store.append_message(session.session_id, SessionMessage.user("排队后新增"))
        store.append_message(session.session_id, SessionMessage.assistant("排队后新增完成"))
        isolated_client = ScriptedLLMClient([LLMReply(final_text="当前进展：只压缩旧快照。")])
        worker = SessionCompactionWorker(
            session_store=store,
            llm_client_factory=_FakeFactory(isolated_client),
            profile_name="openai_gpt_5_4",
        )

        processed = worker.run_once()
        request = isolated_client.requests[0]
        compacted = store.get(session.session_id).latest_compacted_context

        self.assertTrue(processed)
        self.assertEqual(
            [item.content for item in request.conversation_messages],
            ["历史 1", "历史 1 完成"],
        )
        self.assertIsNotNone(compacted)
        assert compacted is not None
        self.assertEqual(compacted.source_message_range, [0, 3])

    def test_worker_run_once_marks_job_failed_when_generation_raises(self) -> None:
        store = self._store()
        session = store.create(
            session_id="sess_source",
            conversation_id="conv-source",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        store.append_message(session.session_id, SessionMessage.user("历史 1"))
        store.append_message(session.session_id, SessionMessage.assistant("历史 1 完成"))
        store.append_message(session.session_id, SessionMessage.user("历史 2"))
        store.append_message(session.session_id, SessionMessage.assistant("历史 2 完成"))
        store.enqueue_compaction_job(
            source_session_id=session.session_id,
            current_message="切换会话",
            preserved_tail_user_turns=1,
            source_message_range=[0, 2],
            snapshot_message_count=len(store.get(session.session_id).history),
        )
        worker = SessionCompactionWorker(
            session_store=store,
            llm_client_factory=_FakeFactory(_FailingLLM()),
            profile_name="openai_gpt_5_4",
        )

        processed = worker.run_once()
        job = store.list_compaction_jobs()[0]

        self.assertTrue(processed)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["result_reason"], "generation_failed")
        self.assertIn("compact failed", job["error_text"])

    def test_cached_llm_client_factory_create_isolated_builds_new_client(self) -> None:
        factory = CachedLLMClientFactory(
            models_config=SimpleNamespace(
                default_profile="openai_gpt_5_4",
                profiles={
                    "openai_gpt_5_4": SimpleNamespace(
                        provider_ref="openai",
                        model="gpt-4.1",
                        tokenizer_family="openai_o200k",
                    )
                },
            ),
            providers_config=SimpleNamespace(providers={}),
            env={"OPENAI_API_KEY": "test-key"},
            primary_profile_name="openai_gpt_5_4",
        )
        shared = object()
        isolated = _SuccessfulLLM(
            provider_name="openai",
            model_name="gpt-4.1",
            profile_name="openai_gpt_5_4",
            final_text="isolated-ok",
        )
        factory.cache_client("openai_gpt_5_4", shared)
        with patch(
            "marten_runtime.interfaces.http.bootstrap_runtime.build_llm_client",
            return_value=isolated,
        ) as mocked_build:
            created = factory.create_isolated("openai_gpt_5_4")
            reply = created.complete(
                LLMRequest(
                    session_id="sess_isolated",
                    trace_id="trace_isolated",
                    message="hi",
                    agent_id="compaction",
                    app_id="compaction",
                )
            )

        self.assertEqual(reply.final_text, "isolated-ok")
        self.assertIsNot(created, isolated)
        self.assertIsNot(created, shared)
        self.assertEqual(mocked_build.call_count, 1)

    def test_cached_llm_client_factory_create_isolated_honors_fallback_profiles(self) -> None:
        factory = CachedLLMClientFactory(
            models_config=SimpleNamespace(
                default_profile="openai_gpt_5_4",
                profiles={
                    "openai_gpt_5_4": SimpleNamespace(
                        provider_ref="openai",
                        model="gpt-4.1",
                        tokenizer_family="openai_o200k",
                        fallback_profiles=["minimax_m2_7_highspeed"],
                    ),
                    "minimax_m2_7_highspeed": SimpleNamespace(
                        provider_ref="minimax",
                        model="MiniMax-M2.5",
                        tokenizer_family="openai_o200k",
                        fallback_profiles=[],
                    ),
                },
            ),
            providers_config=SimpleNamespace(providers={}),
            env={"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            primary_profile_name="openai_gpt_5_4",
        )
        failing = _RetryableProviderFailingLLM()
        fallback = _SuccessfulLLM(
            provider_name="minimax",
            model_name="MiniMax-M2.5",
            profile_name="minimax_m2_7_highspeed",
            final_text="当前进展：已压缩。",
        )
        shared = object()
        factory.cache_client("openai_gpt_5_4", shared)

        def fake_build_llm_client(*, profile_name, profile, providers_config, env):  # noqa: ANN001
            del profile, providers_config, env
            if profile_name == "openai_gpt_5_4":
                return failing
            if profile_name == "minimax_m2_7_highspeed":
                return fallback
            raise AssertionError(profile_name)

        with patch(
            "marten_runtime.interfaces.http.bootstrap_runtime.build_llm_client",
            side_effect=fake_build_llm_client,
        ):
            created = factory.create_isolated("openai_gpt_5_4")
            reply = created.complete(
                LLMRequest(
                    session_id="sess_compaction",
                    trace_id="trace_compaction",
                    message="请生成交接摘要。",
                    agent_id="compaction",
                    app_id="compaction",
                )
            )

        self.assertEqual(reply.final_text, "当前进展：已压缩。")
        self.assertEqual(len(fallback.requests), 1)

    def test_create_compaction_client_reuses_shared_client_without_fallback(self) -> None:
        factory = CachedLLMClientFactory(
            models_config=SimpleNamespace(
                default_profile="minimax_m2_7_highspeed",
                profiles={
                    "minimax_m2_7_highspeed": SimpleNamespace(
                        provider_ref="minimax",
                        model="MiniMax-M2.5",
                        tokenizer_family="openai_o200k",
                        fallback_profiles=[],
                    )
                },
            ),
            providers_config=SimpleNamespace(providers={}),
            env={"MINIMAX_API_KEY": "test-key"},
            primary_profile_name="minimax_m2_7_highspeed",
        )
        shared = object()

        created = factory.create_compaction_client(
            "minimax_m2_7_highspeed",
            shared_client=shared,
        )

        self.assertIs(created, shared)

    def test_create_compaction_client_uses_isolated_when_profile_has_fallback(self) -> None:
        factory = CachedLLMClientFactory(
            models_config=SimpleNamespace(
                default_profile="openai_gpt_5_4",
                profiles={
                    "openai_gpt_5_4": SimpleNamespace(
                        provider_ref="openai",
                        model="gpt-4.1",
                        tokenizer_family="openai_o200k",
                        fallback_profiles=["minimax_m2_7_highspeed"],
                    ),
                    "minimax_m2_7_highspeed": SimpleNamespace(
                        provider_ref="minimax",
                        model="MiniMax-M2.5",
                        tokenizer_family="openai_o200k",
                        fallback_profiles=[],
                    ),
                },
            ),
            providers_config=SimpleNamespace(providers={}),
            env={"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            primary_profile_name="openai_gpt_5_4",
        )
        shared = object()
        isolated = object()

        with patch.object(factory, "create_isolated", return_value=isolated) as mocked:
            created = factory.create_compaction_client(
                "openai_gpt_5_4",
                shared_client=shared,
            )

        self.assertIs(created, isolated)
        mocked.assert_called_once_with("openai_gpt_5_4")

    def test_build_http_runtime_attaches_and_starts_compaction_worker(self) -> None:
        with patch(
            "marten_runtime.interfaces.http.bootstrap_runtime.SessionCompactionWorker",
            _CountingWorker,
        ):
            runtime = build_http_runtime(
                env={"MINIMAX_API_KEY": "test-key", "OPENAI_API_KEY": "test-key"},
                load_env_file=False,
            )

        self.assertTrue(hasattr(runtime, "compaction_worker"))
        self.assertEqual(runtime.compaction_worker.start_count, 1)

    def test_create_app_lifespan_stops_compaction_worker_once(self) -> None:
        fake_runtime = SimpleNamespace(
            channels_config=SimpleNamespace(
                feishu=SimpleNamespace(enabled=False, connection_mode="websocket", auto_start=False)
            ),
            compaction_worker=_CountingWorker(),
            subagent_service=_NoopSubagentService(),
            feishu_socket_service=_NoopFeishuSocket(),
            langfuse_observer=_NoopObserver(),
        )
        with patch("marten_runtime.interfaces.http.app.build_http_runtime", return_value=fake_runtime):
            app = create_app(env={"MINIMAX_API_KEY": "test-key"}, load_env_file=False)
            with TestClient(app):
                pass

        self.assertEqual(fake_runtime.compaction_worker.stop_count, 1)


if __name__ == "__main__":
    unittest.main()
