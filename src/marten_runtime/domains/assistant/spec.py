from marten_runtime.agents.specs import AgentSpec


def build_assistant_spec() -> AgentSpec:
    return AgentSpec(
        agent_id="assistant",
        role="general_assistant",
        app_id="example_assistant",
        allowed_tools=["time"],
    )
