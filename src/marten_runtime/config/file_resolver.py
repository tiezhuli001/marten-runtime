from __future__ import annotations

from pathlib import Path


def resolve_config_path(path: str) -> Path | None:
    candidate = Path(path)
    if candidate.exists():
        return candidate
    if candidate.suffix == ".toml":
        example = candidate.with_name(f"{candidate.stem}.example{candidate.suffix}")
        if example.exists():
            return example
    return None
