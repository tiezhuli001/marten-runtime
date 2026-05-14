from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from marten_runtime.memory.models import MemoryItem


def memory_export_path(root: str | Path, user_id: str) -> Path:
    encoded = quote(str(user_id).strip(), safe="-_.~")
    return Path(root) / "users" / encoded / "MEMORY.md"


def render_memory_markdown(items: list[MemoryItem]) -> str:
    active_items = [item for item in items if item.status == "active"]
    if not active_items:
        return ""
    groups: dict[str, list[MemoryItem]] = defaultdict(list)
    for item in sorted(active_items, key=lambda x: (_scope_label(x), x.type, x.section, -x.priority, x.updated_at, x.memory_id)):
        groups[f"{_scope_label(item)} / {_section_label(item)}"].append(item)
    lines = ["# MEMORY"]
    for heading in sorted(groups):
        lines.extend(["", f"## {heading}"])
        lines.extend(f"- {item.content}" for item in groups[heading])
    return "\n".join(lines).strip() + "\n"


def write_memory_export(root: str | Path, user_id: str, items: list[MemoryItem]) -> Path:
    path = memory_export_path(root, user_id)
    text = render_memory_markdown(items)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def sections_from_items(items: list[MemoryItem]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = defaultdict(list)
    for item in items:
        if item.status != "active":
            continue
        key = item.section if item.scope == "global" else f"{_scope_label(item)} / {item.section}"
        sections[key].append(item.content)
    return dict(sections)


def _scope_label(item: MemoryItem) -> str:
    if item.scope == "agent":
        return f"agent:{item.agent_id}"
    if item.scope == "workspace":
        return f"workspace:{item.workspace_id}"
    return "global"


def _section_label(item: MemoryItem) -> str:
    if item.section.endswith("s"):
        return item.section
    if item.type == "preference":
        return "preferences"
    if item.type == "constraint":
        return "constraints"
    if item.type == "workflow_hint":
        return "workflow_hints"
    if item.type == "fact":
        return "facts" if item.section == "fact" else item.section
    return item.section
