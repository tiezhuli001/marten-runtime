from __future__ import annotations

from pathlib import Path

from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


def build_self_improve_adapter(
    root: Path,
) -> tuple[SQLiteSelfImproveStore, SQLiteSelfImproveStore]:
    store = SQLiteSelfImproveStore(root / "self_improve.sqlite3")
    return store, store


def build_automation_adapter(
    root: Path,
) -> tuple[SQLiteAutomationStore, SQLiteAutomationStore]:
    store = SQLiteAutomationStore(root / "automations.sqlite3")
    return store, store
