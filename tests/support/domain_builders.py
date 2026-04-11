from __future__ import annotations

from pathlib import Path

from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


def build_self_improve_adapter(root: Path) -> tuple[DomainDataAdapter, SQLiteSelfImproveStore]:
    store = SQLiteSelfImproveStore(root / "self_improve.sqlite3")
    return DomainDataAdapter(self_improve_store=store), store


def build_automation_adapter(root: Path) -> tuple[DomainDataAdapter, SQLiteAutomationStore]:
    automation_store = SQLiteAutomationStore(root / "automations.sqlite3")
    adapter = DomainDataAdapter(
        self_improve_store=SQLiteSelfImproveStore(root / "self_improve.sqlite3"),
        automation_store=automation_store,
    )
    return adapter, automation_store
