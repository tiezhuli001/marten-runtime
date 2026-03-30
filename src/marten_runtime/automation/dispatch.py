from __future__ import annotations

from pydantic import BaseModel

from marten_runtime.automation.models import AutomationJob


class AutomationDispatch(BaseModel):
    automation_id: str
    session_id: str
    app_id: str
    agent_id: str
    skill_id: str
    prompt_template: str
    delivery_channel: str
    delivery_target: str
    session_target: str = "isolated"
    scheduled_for: str
    trace_id: str


def build_dispatch(job: AutomationJob, *, scheduled_for: str, trace_id: str) -> AutomationDispatch:
    return AutomationDispatch(
        automation_id=job.automation_id,
        session_id=f"automation:{job.automation_id}:{scheduled_for}",
        app_id=job.app_id,
        agent_id=job.agent_id,
        skill_id=job.skill_id,
        prompt_template=job.prompt_template,
        delivery_channel=job.delivery_channel,
        delivery_target=job.delivery_target,
        session_target=job.session_target,
        scheduled_for=scheduled_for,
        trace_id=trace_id,
    )
