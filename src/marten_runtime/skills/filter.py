import os
import shutil

from marten_runtime.skills.models import SkillSpec


def filter_skills(
    agent_id: str,
    channel_id: str,
    items: list[SkillSpec],
    env: dict[str, str] | None = None,
    config: dict[str, str] | None = None,
) -> list[SkillSpec]:
    env = env or dict(os.environ)
    config = config or {}
    result: list[SkillSpec] = []
    for item in items:
        if not item.meta.enabled:
            continue
        if item.meta.agents and agent_id not in item.meta.agents:
            continue
        if item.meta.channels and channel_id not in item.meta.channels:
            continue
        if item.meta.requires.os and os.name not in item.meta.requires.os:
            continue
        if item.meta.requires.bins and any(shutil.which(name) is None for name in item.meta.requires.bins):
            continue
        if item.meta.requires.env and any(name not in env or not env[name] for name in item.meta.requires.env):
            continue
        if item.meta.requires.config and any(name not in config for name in item.meta.requires.config):
            continue
        result.append(item)
    return result
