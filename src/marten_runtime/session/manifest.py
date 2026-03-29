from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

from pydantic import BaseModel, Field


class ContextManifest(BaseModel):
    manifest_id: str
    run_id: str
    config_snapshot_id: str = "cfg_bootstrap"
    bootstrap_manifest_id: str = "boot_default"
    prompt_mode: str = "full"
    bootstrap_sources: list[str] = Field(default_factory=list)
    working_context_digest: str = ""
    recalled_memory_ids: list[str] = Field(default_factory=list)
    skill_snapshot_id: str = "skill_default"
    tool_snapshot_id: str = "tool_default"
    token_estimate_by_layer: dict[str, int] = Field(default_factory=dict)
    truncated_sources: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def build_context_manifest(
    run_id: str,
    bootstrap_sources: list[str],
    token_estimate_by_layer: dict[str, int],
    *,
    config_snapshot_id: str = "cfg_bootstrap",
    bootstrap_manifest_id: str = "boot_default",
    prompt_mode: str = "full",
    working_context: dict | None = None,
    recalled_memory_ids: list[str] | None = None,
    skill_snapshot_id: str = "skill_default",
    tool_snapshot_id: str = "tool_default",
    truncated_sources: list[str] | None = None,
) -> ContextManifest:
    working_context = working_context or {}
    recalled_memory_ids = recalled_memory_ids or []
    truncated_sources = truncated_sources or []
    working_context_digest = sha256(
        json.dumps(working_context, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:8]
    digest = sha256(
        json.dumps(
            {
                "run_id": run_id,
                "config_snapshot_id": config_snapshot_id,
                "bootstrap_manifest_id": bootstrap_manifest_id,
                "prompt_mode": prompt_mode,
                "bootstrap_sources": bootstrap_sources,
                "working_context_digest": working_context_digest,
                "recalled_memory_ids": recalled_memory_ids,
                "skill_snapshot_id": skill_snapshot_id,
                "tool_snapshot_id": tool_snapshot_id,
                "token_estimate_by_layer": token_estimate_by_layer,
                "truncated_sources": truncated_sources,
            },
            ensure_ascii=True,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:8]
    return ContextManifest(
        manifest_id=f"ctx_manifest_{digest}",
        run_id=run_id,
        config_snapshot_id=config_snapshot_id,
        bootstrap_manifest_id=bootstrap_manifest_id,
        prompt_mode=prompt_mode,
        bootstrap_sources=bootstrap_sources,
        working_context_digest=working_context_digest,
        recalled_memory_ids=recalled_memory_ids,
        skill_snapshot_id=skill_snapshot_id,
        tool_snapshot_id=tool_snapshot_id,
        token_estimate_by_layer=token_estimate_by_layer,
        truncated_sources=truncated_sources,
    )
