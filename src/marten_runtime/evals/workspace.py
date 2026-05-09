from __future__ import annotations

import shutil
from pathlib import Path


def copy_repo_scaffold(
    source_repo_root: Path,
    workspace_root: Path,
    *,
    include_mcp: bool,
) -> None:
    for name in ("config", "apps", "skills"):
        source = source_repo_root / name
        if source.exists():
            shutil.copytree(source, workspace_root / name)
    if include_mcp:
        for name in ("mcps.json", "mcps.example.json"):
            source = source_repo_root / name
            if source.exists():
                shutil.copy2(source, workspace_root / name)
    (workspace_root / "data").mkdir(parents=True, exist_ok=True)
