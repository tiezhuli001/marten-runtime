import hashlib
import json

from pydantic import BaseModel, Field
from marten_runtime.automation.skill_ids import canonicalize_automation_skill_id


class AutomationJob(BaseModel):
    automation_id: str
    name: str = ""
    app_id: str
    agent_id: str
    prompt_template: str = ""
    schedule_kind: str = "daily"
    schedule_expr: str = "10:00"
    timezone: str = "UTC"
    session_target: str = "isolated"
    delivery_channel: str = "feishu"
    delivery_target: str = ""
    skill_id: str = ""
    delivery_mode: str = "final_only"
    payload_kind: str = "digest"
    enabled: bool = True
    internal: bool = False
    semantic_fingerprint: str = ""

    prompt: str = Field(default="", exclude=True)
    schedule_type: str = Field(default="", exclude=True)
    schedule_value: str = Field(default="", exclude=True)

    def model_post_init(self, __context: object) -> None:
        self.skill_id = canonicalize_automation_skill_id(self.skill_id)
        if not self.name:
            self.name = self.automation_id
        if not self.prompt_template and self.prompt:
            self.prompt_template = self.prompt
        if not self.prompt:
            self.prompt = self.prompt_template
        if not self.schedule_kind and self.schedule_type:
            self.schedule_kind = self.schedule_type
        if not self.schedule_type:
            self.schedule_type = self.schedule_kind
        if not self.schedule_expr and self.schedule_value:
            self.schedule_expr = self.schedule_value
        if not self.schedule_value:
            self.schedule_value = self.schedule_expr
        if not self.semantic_fingerprint:
            self.semantic_fingerprint = build_automation_semantic_fingerprint(self)


def build_automation_semantic_fingerprint(job: "AutomationJob | dict[str, object]") -> str:
    if isinstance(job, AutomationJob):
        source = {
            "app_id": job.app_id,
            "agent_id": job.agent_id,
            "delivery_channel": job.delivery_channel,
            "delivery_target": job.delivery_target,
            "skill_id": canonicalize_automation_skill_id(job.skill_id),
            "schedule_kind": job.schedule_kind,
            "schedule_expr": job.schedule_expr,
            "timezone": job.timezone,
            "prompt_template": job.prompt_template,
            "session_target": job.session_target,
        }
    else:
        source = {
            "app_id": str(job.get("app_id", "")),
            "agent_id": str(job.get("agent_id", "")),
            "delivery_channel": str(job.get("delivery_channel", "")),
            "delivery_target": str(job.get("delivery_target", "")),
            "skill_id": canonicalize_automation_skill_id(str(job.get("skill_id", ""))),
            "schedule_kind": str(job.get("schedule_kind", "")),
            "schedule_expr": str(job.get("schedule_expr", "")),
            "timezone": str(job.get("timezone", "")),
            "prompt_template": str(job.get("prompt_template", "")),
            "session_target": str(job.get("session_target", "")),
        }
    normalized = json.dumps(source, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
