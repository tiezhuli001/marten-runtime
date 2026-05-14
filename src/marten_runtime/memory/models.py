from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from marten_runtime.agents.ids import canonicalize_runtime_agent_id

MemoryScope = Literal["global", "agent", "workspace"]
MemoryType = Literal["preference", "fact", "constraint", "workflow_hint"]
MemoryStatus = Literal["active", "superseded", "deleted"]


class MemoryDocument(BaseModel):
    user_id: str
    path: Path
    available: bool = True
    text: str = ""
    sections: dict[str, list[str]] = Field(default_factory=dict)
    items: list["MemoryItem"] = Field(default_factory=list)


class MemoryItem(BaseModel):
    memory_id: str
    user_id: str
    scope: MemoryScope
    agent_id: str | None = None
    workspace_id: str | None = None
    type: MemoryType
    section: str
    content: str
    source_excerpt: str = ""
    source_run_id: str | None = None
    status: MemoryStatus = "active"
    priority: int = 50
    created_at: str
    updated_at: str

    @classmethod
    def new(
        cls,
        *,
        user_id: str,
        scope: str,
        type: str,
        section: str,
        content: str,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        source_excerpt: str = "",
        source_run_id: str | None = None,
        status: str = "active",
        priority: int = 50,
        memory_id: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> "MemoryItem":
        now = _utc_now_iso()
        return cls(
            memory_id=memory_id or uuid4().hex,
            user_id=user_id,
            scope=scope,
            agent_id=agent_id,
            workspace_id=workspace_id,
            type=type,
            section=section,
            content=content,
            source_excerpt=source_excerpt,
            source_run_id=source_run_id,
            status=status,
            priority=priority,
            created_at=created_at or now,
            updated_at=updated_at or now,
        )

    @model_validator(mode="before")
    @classmethod
    def _normalize_values(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        normalized["user_id"] = _normalize_required(normalized.get("user_id"), "user_id")
        normalized["scope"] = str(normalized.get("scope") or "").strip().lower()
        normalized["type"] = str(normalized.get("type") or "").strip().lower()
        normalized["status"] = str(normalized.get("status") or "active").strip().lower()
        normalized["section"] = _normalize_required(normalized.get("section"), "section").lower()
        normalized["content"] = _normalize_required(normalized.get("content"), "content")
        normalized["source_excerpt"] = " ".join(str(normalized.get("source_excerpt") or "").split()).strip()
        priority = int(normalized.get("priority", 50) or 50)
        normalized["priority"] = min(100, max(0, priority))
        scope = normalized["scope"]
        if scope == "global":
            normalized["agent_id"] = None
            normalized["workspace_id"] = None
        elif scope == "agent":
            agent_id = canonicalize_runtime_agent_id(str(normalized.get("agent_id") or "").strip(), default=None)
            if not agent_id:
                raise ValueError("agent_id is required for agent memory")
            normalized["agent_id"] = agent_id
            normalized["workspace_id"] = None
        elif scope == "workspace":
            workspace_id = " ".join(str(normalized.get("workspace_id") or "").split()).strip()
            if not workspace_id:
                raise ValueError("workspace_id is required for workspace memory")
            normalized["workspace_id"] = workspace_id
            agent_id_raw = str(normalized.get("agent_id") or "").strip()
            normalized["agent_id"] = canonicalize_runtime_agent_id(agent_id_raw, default=None) if agent_id_raw else None
        return normalized


def _normalize_required(value: object, field_name: str) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
