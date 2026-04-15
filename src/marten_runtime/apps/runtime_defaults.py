from __future__ import annotations

from pathlib import Path

DEFAULT_APP_ID = "main_agent"
DEFAULT_AGENT_ID = "main"


def default_app_root(repo_root: Path) -> Path:
    return repo_root / "apps" / DEFAULT_APP_ID


def default_app_manifest_path(repo_root: Path) -> Path:
    return default_app_root(repo_root) / "app.toml"


def default_lessons_path(repo_root: Path) -> Path:
    return default_app_root(repo_root) / "SYSTEM_LESSONS.md"
