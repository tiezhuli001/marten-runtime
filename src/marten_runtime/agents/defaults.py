from __future__ import annotations

from pathlib import Path

DEFAULT_AGENT_ID = "main"
DEFAULT_AGENT_ASSET_ROOT = "agents/main"


def default_agent_assets_root(repo_root: Path) -> Path:
    return repo_root / DEFAULT_AGENT_ASSET_ROOT


def default_lessons_path(repo_root: Path) -> Path:
    return default_agent_assets_root(repo_root) / "SYSTEM_LESSONS.md"
