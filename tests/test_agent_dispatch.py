import unittest

from marten_runtime.agents.dispatch import AgentDispatchService
from marten_runtime.agents.registry import AgentRegistry
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.observability.langfuse import build_langfuse_observer
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.session.models import SessionMessage


class AgentDispatchTests(unittest.TestCase):
    def _registry(self) -> AgentRegistry:
        registry = AgentRegistry()
        registry.register(
            AgentSpec(
                agent_id="main",
                role="general_assistant",
                routing_description="general",
                allowed_handoff_agents=["bazi"],
            )
        )
        registry.register(
            AgentSpec(
                agent_id="bazi",
                role="bazi_consultant",
                routing_description="bazi, four pillars and dayun",
            )
        )
        registry.validate_handoff_catalog()
        return registry

    def test_routes_lunar_birth_request_to_bazi_with_metadata_only_history(self) -> None:
        history = InMemoryRunHistory()
        llm = ScriptedLLMClient([])
        service = AgentDispatchService(
            registry=self._registry(),
            run_history=history,
            observer=build_langfuse_observer(env={}),
        )

        result = service.dispatch(
            source_agent_id="main",
            session_id="sess_route",
            trace_id="trace_route",
            message="男，农历1988年2月15日，请按子平格局法分析",
            recent_messages=[SessionMessage.assistant("上一轮正在讨论八字。")],
            llm_client=llm,
            model_profile_name="test",
            tokenizer_family="openai_o200k",
            config_snapshot_id="cfg_test",
        )

        self.assertEqual(result.target_agent_id, "bazi")
        request = llm.requests[0]
        self.assertEqual(request.request_kind, "agent_routing")
        self.assertEqual(request.requested_tool_name, "agent_route")
        self.assertIn("bazi", request.system_prompt or "")
        run = history.get(result.route_run_id)
        self.assertEqual(run.observation_policy, "metadata_only")
        self.assertEqual(run.delivery_status, "internal")
        self.assertEqual(run.final_text, "[REDACTED:metadata_only]")
        self.assertEqual(
            run.tool_calls[0]["tool_payload"],
            {"target_agent_id": "bazi"},
        )

    def test_routes_general_request_to_main(self) -> None:
        service = AgentDispatchService(
            registry=self._registry(),
            run_history=InMemoryRunHistory(),
            observer=build_langfuse_observer(env={}),
        )

        result = service.dispatch(
            source_agent_id="main",
            session_id="sess_main",
            trace_id="trace_main",
            message="帮我解释这段代码",
            recent_messages=[],
            llm_client=ScriptedLLMClient([]),
            model_profile_name="test",
            tokenizer_family="openai_o200k",
            config_snapshot_id="cfg_test",
        )

        self.assertEqual(result.target_agent_id, "main")

    def test_rejects_reply_outside_authorized_catalog(self) -> None:
        class InvalidRoutingLLM:
            provider_name = "test"
            model_name = "test"

            def complete(self, request):  # noqa: ANN001
                return LLMReply(
                    tool_name="agent_route",
                    tool_payload={"target_agent_id": "ops"},
                )

        history = InMemoryRunHistory()
        service = AgentDispatchService(
            registry=self._registry(),
            run_history=history,
            observer=build_langfuse_observer(env={}),
        )

        with self.assertRaisesRegex(ValueError, "unauthorized target ops"):
            service.dispatch(
                source_agent_id="main",
                session_id="sess_invalid",
                trace_id="trace_invalid",
                message="route me",
                recent_messages=[],
                llm_client=InvalidRoutingLLM(),
                model_profile_name="test",
                tokenizer_family="openai_o200k",
                config_snapshot_id="cfg_test",
            )
        self.assertEqual(history.list_runs()[0].status, "failed")


if __name__ == "__main__":
    unittest.main()
