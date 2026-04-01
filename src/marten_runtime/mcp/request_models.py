from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class NormalizedMCPRequest(BaseModel):
    action: str
    server_id: str | None = None
    tool_name: str | None = None
    arguments: dict = Field(default_factory=dict)

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("action is required")
        return normalized
