from __future__ import annotations

import hashlib
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_RUN_ID_LOCK = threading.Lock()
_LAST_RUN_ID_TIMESTAMP: str | None = None
_RUN_ID_SEQUENCE = 0


def build_eval_run_id(suite_id: str, git_sha: str) -> str:
    global _LAST_RUN_ID_TIMESTAMP, _RUN_ID_SEQUENCE
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    shortsha = (git_sha or "nogit")[:8]
    with _RUN_ID_LOCK:
        if timestamp == _LAST_RUN_ID_TIMESTAMP:
            _RUN_ID_SEQUENCE += 1
        else:
            _LAST_RUN_ID_TIMESTAMP = timestamp
            _RUN_ID_SEQUENCE = 0
        sequence = _RUN_ID_SEQUENCE
    return f"eval_{suite_id}_{timestamp}_{shortsha}_{sequence:04d}"


def config_fingerprint(repo_root: Path) -> str:
    hasher = hashlib.sha256()
    inputs: list[Path] = []
    for relative in ("config", "apps", "skills"):
        root = repo_root / relative
        if not root.exists():
            continue
        inputs.extend(path for path in root.rglob("*") if path.is_file())
    mcps_path = repo_root / "mcps.json"
    if not mcps_path.exists():
        mcps_path = repo_root / "mcps.example.json"
    if mcps_path.exists():
        inputs.append(mcps_path)
    for path in sorted(inputs, key=lambda item: item.as_posix()):
        hasher.update(path.relative_to(repo_root).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def git_state(repo_root: Path) -> tuple[str, str, bool]:
    branch = _git_command(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    sha = _git_command(repo_root, "rev-parse", "--short", "HEAD") or "nogit"
    dirty = bool(
        _git_command(repo_root, "status", "--porcelain", "--untracked-files=normal")
    )
    return branch, sha, dirty


def _git_command(repo_root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
