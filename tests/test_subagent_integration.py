import time
import unittest
from threading import Event

from fastapi.testclient import TestClient

from marten_runtime.runtime.llm_client import LLMReply
from marten_runtime.runtime.usage_models import NormalizedUsage
from tests.http_app_support import build_test_app


class SubagentEndToEndLLM:
    provider_name = "subagent-e2e"
    model_name = "subagent-e2e-local"

    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        if request.request_kind == "subagent":
            return LLMReply(final_text="child finished")
        if request.tool_result is None:
            return LLMReply(
                tool_name="spawn_subagent",
                tool_payload={
                    "task": "run child repo inspection",
                    "label": "repo-child",
                },
            )
        return LLMReply(final_text="background subagent accepted")


class SubagentUsageEndToEndLLM:
    provider_name = "subagent-usage-e2e"
    model_name = "subagent-usage-e2e-local"

    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        if request.request_kind == "subagent":
            return LLMReply(
                final_text="child finished with usage",
                usage=NormalizedUsage(
                    input_tokens=321,
                    output_tokens=45,
                    total_tokens=366,
                    provider_name="subagent-usage-e2e",
                    model_name="subagent-usage-e2e-local",
                ),
            )
        if request.tool_result is None:
            return LLMReply(
                tool_name="spawn_subagent",
                tool_payload={
                    "task": "run child repo inspection",
                    "label": "repo-child-usage",
                },
            )
        return LLMReply(final_text="background subagent accepted")


class InvalidSubagentAgentIdLLM:
    provider_name = "subagent-invalid-agent-id"
    model_name = "subagent-invalid-agent-id-local"

    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        if request.request_kind == "subagent":
            return LLMReply(final_text="child finished after invalid agent fallback")
        if request.tool_result is None:
            return LLMReply(
                tool_name="spawn_subagent",
                tool_payload={
                    "task": "run child repo inspection",
                    "label": "repo-child-invalid-agent",
                    "tool_profile": "mcp:github-or-web",
                    "agent_id": "github-subagent",
                },
            )
        return LLMReply(final_text="background subagent accepted")


class SubagentHTTPIntegrationTests(unittest.TestCase):
    def _configure_runtime_with_llm(self, llm):  # noqa: ANN001
        app = build_test_app()
        runtime = app.state.runtime
        runtime.runtime_loop.llm = llm
        runtime.llm_client_factory.cache_client("openai_gpt5", llm)
        runtime.llm_client_factory.cache_client("minimax_m25", llm)
        return app

    def _wait_for_task_status(self, client: TestClient, task_id: str, expected: set[str], *, timeout: float = 2.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            response = client.get(f"/diagnostics/subagent/{task_id}")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            if payload["status"] in expected:
                return payload
            time.sleep(0.05)
        self.fail(f"task {task_id} did not reach one of {sorted(expected)}")

    def test_http_message_path_spawns_child_and_observes_completion(self) -> None:
        app = self._configure_runtime_with_llm(SubagentEndToEndLLM())
        llm = app.state.runtime.runtime_loop.llm

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "test",
                    "user_id": "u1",
                    "conversation_id": "conv-subagent-http",
                    "message_id": "msg-1",
                    "body": "please inspect this repo in background",
                },
            )
            self.assertEqual(response.status_code, 200)
            session_id = response.json()["session_id"]
            for _ in range(30):
                tasks = client.get("/diagnostics/subagents")
                self.assertEqual(tasks.status_code, 200)
                items = tasks.json()["items"]
                if items and items[0]["status"] == "succeeded":
                    task = items[0]
                    break
                time.sleep(0.05)
            else:
                self.fail("subagent task did not reach succeeded state")

            self.assertEqual(task["parent_session_id"], session_id)
            self.assertTrue(task["child_session_id"])
            self.assertTrue(task["child_run_id"])

            parent_session = client.get(f"/diagnostics/session/{session_id}")
            self.assertEqual(parent_session.status_code, 200)
            history = parent_session.json()["history"]
            self.assertEqual(history[-1]["role"], "system")
            self.assertIn("subagent task completed", history[-1]["content"])

            child_run = client.get(f"/diagnostics/run/{task['child_run_id']}")
            self.assertEqual(child_run.status_code, 200)
            self.assertEqual(child_run.json()["parent_run_id"], response.json()["events"][-1]["run_id"])

        self.assertTrue(any(req.request_kind == "subagent" for req in llm.requests))
        self.assertTrue(any(req.request_kind == "interactive" for req in llm.requests))

    def test_http_message_path_returns_parent_ack_while_child_still_running(self) -> None:
        class BlockingChildLLM:
            provider_name = "subagent-blocking"
            model_name = "subagent-blocking-local"

            def __init__(self) -> None:
                self.requests = []
                self.release = Event()

            def complete(self, request):  # noqa: ANN001
                self.requests.append(request)
                if request.request_kind == "subagent":
                    self.release.wait(timeout=2.0)
                    return LLMReply(final_text="child finished after parent ack")
                if request.tool_result is None:
                    return LLMReply(
                        tool_name="spawn_subagent",
                        tool_payload={
                            "task": "run child repo inspection",
                            "label": "repo-child-blocking",
                        },
                    )
                return LLMReply(final_text="parent followup should not run")

        llm = BlockingChildLLM()
        app = self._configure_runtime_with_llm(llm)

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "test",
                    "user_id": "u1",
                    "conversation_id": "conv-subagent-http-blocking",
                    "message_id": "msg-1",
                    "body": "please inspect this repo in background",
                },
            )
            self.assertEqual(response.status_code, 200)
            final_text = response.json()["events"][-1]["payload"]["text"]
            self.assertEqual(final_text, "parent followup should not run")
            interactive_requests = [item for item in llm.requests if item.request_kind == "interactive"]
            self.assertEqual(len(interactive_requests), 2)

            tasks = client.get("/diagnostics/subagents")
            self.assertEqual(tasks.status_code, 200)
            task = tasks.json()["items"][0]
            self.assertIn(task["status"], {"queued", "running"})
            self.assertNotEqual(task["status"], "succeeded")
            task_id = task["task_id"]

            llm.release.set()
            self._wait_for_task_status(client, task_id, {"succeeded"})

    def test_http_message_path_syncs_child_session_latest_actual_usage(self) -> None:
        app = self._configure_runtime_with_llm(SubagentUsageEndToEndLLM())

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "test",
                    "user_id": "u1",
                    "conversation_id": "conv-subagent-usage-http",
                    "message_id": "msg-usage-1",
                    "body": "please inspect this repo in background",
                },
            )
            self.assertEqual(response.status_code, 200)
            task = self._wait_for_task_status(
                client,
                client.get("/diagnostics/subagents").json()["items"][0]["task_id"],
                {"succeeded"},
            )

            child_session = client.get(f"/diagnostics/session/{task['child_session_id']}")
            self.assertEqual(child_session.status_code, 200)
            latest_usage = child_session.json()["latest_actual_usage"]
            self.assertIsNotNone(latest_usage)
            self.assertEqual(latest_usage["input_tokens"], 321)
            self.assertEqual(latest_usage["output_tokens"], 45)
            self.assertEqual(latest_usage["total_tokens"], 366)

    def test_http_message_path_survives_invalid_spawn_agent_id_from_model(self) -> None:
        app = self._configure_runtime_with_llm(InvalidSubagentAgentIdLLM())

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "test",
                    "user_id": "u1",
                    "conversation_id": "conv-subagent-invalid-agent",
                    "message_id": "msg-invalid-agent",
                    "body": "please inspect this repo in background",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["events"][-1]["payload"]["text"],
                "background subagent accepted",
            )

            task = self._wait_for_task_status(
                client,
                client.get("/diagnostics/subagents").json()["items"][0]["task_id"],
                {"succeeded"},
            )
            self.assertEqual(task["agent_id"], "main")

    def test_default_runtime_allows_five_concurrent_children_before_queueing_the_sixth(self) -> None:
        class ManyBlockingChildrenLLM:
            provider_name = "subagent-five-concurrency"
            model_name = "subagent-five-concurrency-local"

            def __init__(self) -> None:
                self.requests = []
                self.spawn_count = 0
                self.child_call_count = 0
                self.releases = [Event() for _ in range(6)]

            def complete(self, request):  # noqa: ANN001
                self.requests.append(request)
                if request.request_kind == "subagent":
                    index = self.child_call_count
                    self.child_call_count += 1
                    self.releases[index].wait(timeout=2.0)
                    return LLMReply(final_text=f"child-{index + 1} finished")
                if request.tool_result is None:
                    self.spawn_count += 1
                    return LLMReply(
                        tool_name="spawn_subagent",
                        tool_payload={
                            "task": f"run child repo inspection {self.spawn_count}",
                            "label": f"repo-child-{self.spawn_count}",
                        },
                    )
                return LLMReply(final_text="unexpected parent followup")

        llm = ManyBlockingChildrenLLM()
        app = self._configure_runtime_with_llm(llm)
        self.assertEqual(app.state.runtime.subagent_service.max_concurrent_subagents, 5)

        with TestClient(app) as client:
            for index in range(5):
                response = client.post(
                    "/messages",
                    json={
                        "channel_id": "test",
                        "user_id": f"u{index + 1}",
                        "conversation_id": f"conv-subagent-default-{index + 1}",
                        "message_id": f"msg-{index + 1}",
                        "body": "please inspect this repo in background",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json()["events"][-1]["payload"]["text"],
                    "unexpected parent followup",
                )

            deadline = time.time() + 2.0
            while time.time() < deadline:
                listing = client.get("/diagnostics/subagents")
                self.assertEqual(listing.status_code, 200)
                items = listing.json()["items"]
                running = [item for item in items if item["status"] == "running"]
                if len(running) == 5:
                    break
                time.sleep(0.05)
            else:
                self.fail("first five child tasks did not reach running state")

            sixth = client.post(
                "/messages",
                json={
                    "channel_id": "test",
                    "user_id": "u6",
                    "conversation_id": "conv-subagent-default-6",
                    "message_id": "msg-6",
                    "body": "please inspect this repo in background",
                },
            )
            self.assertEqual(sixth.status_code, 200)
            self.assertEqual(
                sixth.json()["events"][-1]["payload"]["text"],
                "unexpected parent followup",
            )

            deadline = time.time() + 2.0
            tasks = []
            while time.time() < deadline:
                listing = client.get("/diagnostics/subagents")
                self.assertEqual(listing.status_code, 200)
                tasks = sorted(listing.json()["items"], key=lambda item: item["created_at"])
                if len(tasks) == 6:
                    running = [item for item in tasks if item["status"] == "running"]
                    queued = [item for item in tasks if item["status"] == "queued"]
                    if len(running) == 5 and len(queued) == 1:
                        break
                time.sleep(0.05)
            self.assertEqual(len(tasks), 6)
            self.assertEqual(len([item for item in tasks if item["status"] == "running"]), 5)
            self.assertEqual(len([item for item in tasks if item["status"] == "queued"]), 1)
            queued_task = next(item for item in tasks if item["status"] == "queued")

            for release in llm.releases[:5]:
                release.set()
            self._wait_for_task_status(client, queued_task["task_id"], {"running", "succeeded"})
            llm.releases[5].set()
            final_sixth = self._wait_for_task_status(client, queued_task["task_id"], {"succeeded"})
            self.assertEqual(final_sixth["status"], "succeeded")

    def test_http_message_path_queues_second_child_until_capacity_frees(self) -> None:
        class TwoBlockingChildrenLLM:
            provider_name = "subagent-queue"
            model_name = "subagent-queue-local"

            def __init__(self) -> None:
                self.requests = []
                self.spawn_count = 0
                self.child_call_count = 0
                self.releases = [Event(), Event()]

            def complete(self, request):  # noqa: ANN001
                self.requests.append(request)
                if request.request_kind == "subagent":
                    index = self.child_call_count
                    self.child_call_count += 1
                    self.releases[index].wait(timeout=2.0)
                    return LLMReply(final_text=f"child-{index + 1} finished")
                if request.tool_result is None:
                    self.spawn_count += 1
                    return LLMReply(
                        tool_name="spawn_subagent",
                        tool_payload={
                            "task": f"run child repo inspection {self.spawn_count}",
                            "label": f"repo-child-{self.spawn_count}",
                        },
                    )
                return LLMReply(final_text="unexpected parent followup")

        llm = TwoBlockingChildrenLLM()
        app = self._configure_runtime_with_llm(llm)
        app.state.runtime.subagent_service.max_concurrent_subagents = 1

        with TestClient(app) as client:
            first = client.post(
                "/messages",
                json={
                    "channel_id": "test",
                    "user_id": "u1",
                    "conversation_id": "conv-subagent-queue-1",
                    "message_id": "msg-1",
                    "body": "please inspect this repo in background",
                },
            )
            self.assertEqual(first.status_code, 200)
            self.assertEqual(
                first.json()["events"][-1]["payload"]["text"],
                "unexpected parent followup",
            )

            deadline = time.time() + 2.0
            first_task_id = None
            while time.time() < deadline:
                listing = client.get("/diagnostics/subagents")
                self.assertEqual(listing.status_code, 200)
                items = listing.json()["items"]
                if items:
                    first_task_id = items[0]["task_id"]
                    if items[0]["status"] == "running":
                        break
                time.sleep(0.05)
            self.assertIsNotNone(first_task_id)

            second = client.post(
                "/messages",
                json={
                    "channel_id": "test",
                    "user_id": "u1",
                    "conversation_id": "conv-subagent-queue-2",
                    "message_id": "msg-2",
                    "body": "please inspect another repo in background",
                },
            )
            self.assertEqual(second.status_code, 200)
            self.assertEqual(
                second.json()["events"][-1]["payload"]["text"],
                "unexpected parent followup",
            )

            deadline = time.time() + 2.0
            tasks = []
            while time.time() < deadline:
                listing = client.get("/diagnostics/subagents")
                self.assertEqual(listing.status_code, 200)
                tasks = sorted(listing.json()["items"], key=lambda item: item["created_at"])
                if len(tasks) == 2:
                    break
                time.sleep(0.05)
            self.assertEqual(len(tasks), 2)
            self.assertEqual(tasks[0]["status"], "running")
            self.assertEqual(tasks[1]["status"], "queued")

            llm.releases[0].set()
            first_task = self._wait_for_task_status(client, tasks[0]["task_id"], {"succeeded"})
            second_running = self._wait_for_task_status(client, tasks[1]["task_id"], {"running", "succeeded"})
            self.assertEqual(first_task["status"], "succeeded")
            self.assertIn(second_running["status"], {"running", "succeeded"})
            self.assertIsNotNone(second_running["started_at"])
            self.assertLessEqual(first_task["finished_at"], second_running["started_at"])

            llm.releases[1].set()
            second_task = self._wait_for_task_status(client, tasks[1]["task_id"], {"succeeded"})
            self.assertEqual(second_task["status"], "succeeded")

    def test_http_message_path_can_cancel_running_child_via_runtime_tool(self) -> None:
        class SpawnThenCancelLLM:
            provider_name = "subagent-cancel"
            model_name = "subagent-cancel-local"

            def __init__(self) -> None:
                self.requests = []
                self.release = Event()
                self.cancel_task_id = ""

            def complete(self, request):  # noqa: ANN001
                self.requests.append(request)
                if request.request_kind == "subagent":
                    self.release.wait(timeout=2.0)
                    return LLMReply(final_text="child finished too late")
                if request.tool_result is None:
                    if "取消" in request.message:
                        return LLMReply(
                            tool_name="cancel_subagent",
                            tool_payload={"task_id": self.cancel_task_id},
                        )
                    return LLMReply(
                        tool_name="spawn_subagent",
                        tool_payload={
                            "task": "run child repo inspection",
                            "label": "repo-child-cancel",
                        },
                    )
                return LLMReply(final_text="cancel accepted")

        llm = SpawnThenCancelLLM()
        app = self._configure_runtime_with_llm(llm)

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "test",
                    "user_id": "u1",
                    "conversation_id": "conv-subagent-cancel",
                    "message_id": "msg-1",
                    "body": "please inspect this repo in background",
                },
            )
            self.assertEqual(response.status_code, 200)

            listing = client.get("/diagnostics/subagents")
            self.assertEqual(listing.status_code, 200)
            task = listing.json()["items"][0]
            llm.cancel_task_id = task["task_id"]

            cancel = client.post(
                "/messages",
                json={
                    "channel_id": "test",
                    "user_id": "u1",
                    "conversation_id": "conv-subagent-cancel",
                    "message_id": "msg-2",
                    "body": "取消刚才的子代理任务",
                },
            )
            self.assertEqual(cancel.status_code, 200)
            self.assertEqual(cancel.json()["events"][-1]["payload"]["text"], "cancel accepted")

            cancelled = self._wait_for_task_status(client, task["task_id"], {"cancelled"})
            self.assertEqual(cancelled["status"], "cancelled")

            llm.release.set()
            time.sleep(0.1)
            still_cancelled = client.get(f"/diagnostics/subagent/{task['task_id']}")
            self.assertEqual(still_cancelled.status_code, 200)
            self.assertEqual(still_cancelled.json()["status"], "cancelled")

            session = client.get(f"/diagnostics/session/{response.json()['session_id']}")
            self.assertEqual(session.status_code, 200)
            self.assertTrue(
                any("subagent task cancelled" in item["content"] for item in session.json()["history"] if item["role"] == "system")
            )

    def test_http_message_path_marks_child_timeout_via_runtime_path(self) -> None:
        class TimeoutChildLLM:
            provider_name = "subagent-timeout"
            model_name = "subagent-timeout-local"

            def __init__(self) -> None:
                self.requests = []
                self.release = Event()

            def complete(self, request):  # noqa: ANN001
                self.requests.append(request)
                if request.request_kind == "subagent":
                    self.release.wait(timeout=2.0)
                    return LLMReply(final_text="child finished after timeout")
                if request.tool_result is None:
                    return LLMReply(
                        tool_name="spawn_subagent",
                        tool_payload={
                            "task": "run child repo inspection",
                            "label": "repo-child-timeout",
                        },
                    )
                return LLMReply(final_text="unexpected parent followup")

        llm = TimeoutChildLLM()
        app = self._configure_runtime_with_llm(llm)
        app.state.runtime.subagent_service.subagent_timeout_seconds = 0

        with TestClient(app) as client:
            response = client.post(
                "/messages",
                json={
                    "channel_id": "test",
                    "user_id": "u1",
                    "conversation_id": "conv-subagent-timeout",
                    "message_id": "msg-1",
                    "body": "please inspect this repo in background",
                },
            )
            self.assertEqual(response.status_code, 200)

            listing = client.get("/diagnostics/subagents")
            self.assertEqual(listing.status_code, 200)
            task_id = listing.json()["items"][0]["task_id"]
            timed_out = self._wait_for_task_status(client, task_id, {"timed_out"})
            self.assertEqual(timed_out["status"], "timed_out")

            session = client.get(f"/diagnostics/session/{response.json()['session_id']}")
            self.assertEqual(session.status_code, 200)
            self.assertIn("subagent task timed out", session.json()["history"][-1]["content"])

            llm.release.set()
            time.sleep(0.1)
            final_state = client.get(f"/diagnostics/subagent/{task_id}")
            self.assertEqual(final_state.status_code, 200)
            self.assertEqual(final_state.json()["status"], "timed_out")


if __name__ == "__main__":
    unittest.main()
