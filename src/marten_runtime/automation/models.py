from pydantic import BaseModel


class AutomationJob(BaseModel):
    automation_id: str
    app_id: str
    agent_id: str
    prompt: str
    schedule_type: str
    schedule_value: str
    timezone: str = "UTC"
    session_target: str = "isolated"
    delivery_mode: str = "none"
    payload_kind: str = "prompt"
    enabled: bool = True
