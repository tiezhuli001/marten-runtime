from __future__ import annotations

import sqlite3
from pathlib import Path


def prepare_sqlite_path(path: str | Path) -> Path:
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def connect_sqlite(path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(prepare_sqlite_path(path))
