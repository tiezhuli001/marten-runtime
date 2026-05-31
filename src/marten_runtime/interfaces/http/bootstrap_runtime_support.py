from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from marten_runtime.agents.assets import AgentRuntimeAssets, load_agent_runtime_assets
from marten_runtime.agents.defaults import DEFAULT_AGENT_ID
from marten_runtime.agents.specs import AgentSpec
from marten_runtime.automation.models import AutomationJob
from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.automation.store import AutomationStore
from marten_runtime.config.automations_loader import load_automations
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.session.sqlite_store import SQLiteSessionStore


def load_agent_runtimes(
    *,
    repo_root: Path,
    agent_specs: list[AgentSpec],
) -> dict[str, AgentRuntimeAssets]:
    runtimes: dict[str, AgentRuntimeAssets] = {}
    for spec in sorted(agent_specs, key=lambda item: item.agent_id):
        if not spec.enabled:
            continue
        runtimes[spec.agent_id] = load_agent_runtime_assets(repo_root=repo_root, spec=spec)
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
