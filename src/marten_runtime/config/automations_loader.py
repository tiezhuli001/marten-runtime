from __future__ import annotations

import tomllib

from marten_runtime.automation.models import AutomationJob
from marten_runtime.config.file_resolver import resolve_config_path


def load_automations(path: str) -> list[AutomationJob]:
    resolved = resolve_config_path(path)
    if resolved is None:
        return []

    data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    return [AutomationJob(**item) for item in data.get("automations", [])]
