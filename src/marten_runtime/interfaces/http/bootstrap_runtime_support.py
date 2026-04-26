from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from marten_runtime.apps.bootstrap_prompt import load_bootstrap_prompt
from marten_runtime.apps.manifest import AppManifest, load_app_manifest
from marten_runtime.apps.runtime_defaults import DEFAULT_AGENT_ID, DEFAULT_APP_ID
from marten_runtime.automation.models import AutomationJob
from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.automation.store import AutomationStore
from marten_runtime.config.automations_loader import load_automations
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.session.sqlite_store import SQLiteSessionStore


@dataclass
class AppRuntimeAssets:
    manifest: AppManifest
    system_prompt: str


def load_app_runtimes(
    *,
    repo_root: Path,
    app_ids: set[str],
) -> dict[str, AppRuntimeAssets]:
    runtimes: dict[str, AppRuntimeAssets] = {}
    for app_id in sorted(app_ids):
        manifest = load_app_manifest(str(repo_root / "apps" / app_id / "app.toml"))
        runtimes[app_id] = AppRuntimeAssets(
            manifest=manifest,
            system_prompt=load_bootstrap_prompt(repo_root=repo_root, manifest=manifest),
        )
    return runtimes


def build_stateful_stores(
    repo_root: Path,
) -> tuple[SQLiteAutomationStore, SQLiteSelfImproveStore, SQLiteSessionStore]:
    automation_store = SQLiteAutomationStore(repo_root / "data" / "automations.sqlite3")
    self_improve_store = SQLiteSelfImproveStore(
        repo_root / "data" / "self_improve.sqlite3"
    )
    session_store = SQLiteSessionStore(repo_root / "data" / "sessions.sqlite3")
    for job in load_automations(str(repo_root / "config" / "automations.toml")):
        automation_store.save(job)
    ensure_self_improve_automation(automation_store)
    return automation_store, self_improve_store, session_store


def has_feishu_credentials(env: Mapping[str, str]) -> bool:
    return bool(env.get("FEISHU_APP_ID") and env.get("FEISHU_APP_SECRET"))


def ensure_self_improve_automation(store: AutomationStore) -> None:
    automation_id = "self_improve_internal"
    try:
        store.get(automation_id)
        return
    except KeyError:
        pass
    store.save(
        AutomationJob(
            automation_id=automation_id,
            name="Internal Self Improve",
            app_id=DEFAULT_APP_ID,
            agent_id=DEFAULT_AGENT_ID,
            prompt_template="Summarize repeated failures and later recoveries into lesson candidates.",
            schedule_kind="daily",
            schedule_expr="03:00",
            timezone="UTC",
            session_target="isolated",
            delivery_channel="http",
            delivery_target="internal",
            skill_id="self_improve",
            enabled=True,
            internal=True,
        )
    )
