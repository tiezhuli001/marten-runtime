from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import unquote

from marten_runtime.memory.export import write_memory_export
from marten_runtime.memory.models import MemoryItem
from marten_runtime.memory.sqlite_store import SQLiteMemoryStore


def migrate_memory_root(
    *,
    memory_root: str | Path,
    db_path: str | Path | None = None,
    dry_run: bool = False,
    import_edited_markdown: bool = False,
) -> dict[str, int]:
    root = Path(memory_root)
    resolved_db_path = Path(db_path or root / "memory.sqlite3")
    planned: list[MemoryItem] = []
    represented: dict[tuple[str, str, str | None, str | None, str, str], list[MemoryItem]] = {}
    for path in sorted((root / "users").glob("*/MEMORY.md")):
        user_id = unquote(path.parent.name)
        items = _items_from_markdown(user_id, path.read_text(encoding="utf-8"))
        planned.extend(items)
        for item in items:
            represented.setdefault(_bucket_key(item), []).append(item)
    planned.extend(_items_from_legacy_jsonl(root))
    summary = {
        "user_count": len({item.user_id for item in planned}),
        "item_count": len(planned),
        "changed_item_count": len(planned),
        "skipped_count": 0,
    }
    if dry_run:
        return summary
    store = SQLiteMemoryStore(resolved_db_path)
    if import_edited_markdown:
        for key in represented:
            user_id, scope, agent_id, workspace_id, memory_type, section = key
            for existing in store.list_active(user_id, scope=scope, agent_id=agent_id, workspace_id=workspace_id, type=memory_type):
                if existing.section == section:
                    store.supersede(existing.memory_id)
    for item in planned:
        store.append(item)
    for user_id in sorted({item.user_id for item in planned}):
        write_memory_export(root, user_id, store.list_active(user_id))
    return summary


def _items_from_markdown(user_id: str, text: str) -> list[MemoryItem]:
    items: list[MemoryItem] = []
    current_section: str | None = None
    current_scope = "global"
    current_agent_id: str | None = None
    current_workspace_id: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            heading = line[3:].strip()
            current_scope, current_agent_id, current_workspace_id, current_section = _parse_heading(heading)
            continue
        if not line.startswith("- ") or not current_section:
            continue
        content = " ".join(line[2:].split()).strip()
        if not content:
            continue
        items.append(MemoryItem.new(
            user_id=user_id,
            scope=current_scope,
            agent_id=current_agent_id,
            workspace_id=current_workspace_id,
            type=_type_from_section(current_section),
            section=current_section,
            content=content,
        ))
    return items


def _items_from_legacy_jsonl(root: Path) -> list[MemoryItem]:
    path = root / "legacy_memory.jsonl"
    if not path.exists():
        return []
    items: list[MemoryItem] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        row = json.loads(raw_line)
        scope = str(row.get("scope") or "global").strip().lower()
        agent_id = str(row.get("agent_id") or "").strip() or None
        if str(row.get("app_id") or "").strip() == "main_agent":
            scope = "agent"
            agent_id = "main"
        items.append(MemoryItem.new(
            user_id=str(row["user_id"]),
            scope=scope,
            agent_id=agent_id,
            workspace_id=str(row.get("workspace_id") or "").strip() or None,
            type=str(row.get("type") or _type_from_section(str(row.get("section") or "facts"))),
            section=str(row.get("section") or "facts"),
            content=str(row["content"]),
            source_excerpt=str(row.get("source_excerpt") or ""),
            source_run_id=str(row.get("source_run_id") or "").strip() or None,
            priority=int(row.get("priority", 50) or 50),
        ))
    return items


def _parse_heading(heading: str) -> tuple[str, str | None, str | None, str]:
    parts = [part.strip() for part in heading.split("/", 1)]
    if len(parts) == 1:
        return "global", None, None, _normalize_section(parts[0])
    scope_part, section = parts
    if scope_part.startswith("agent:"):
        return "agent", scope_part.split(":", 1)[1].strip(), None, _normalize_section(section)
    if scope_part.startswith("workspace:"):
        return "workspace", None, scope_part.split(":", 1)[1].strip(), _normalize_section(section)
    return "global", None, None, _normalize_section(section)


def _normalize_section(section: str) -> str:
    value = " ".join(str(section).split()).strip().lower().replace(" ", "_")
    if value == "workflow_hints":
        return "workflow_hints"
    return value


def _type_from_section(section: str) -> str:
    value = _normalize_section(section)
    if value in {"preferences", "preference"}:
        return "preference"
    if value in {"constraints", "constraint"}:
        return "constraint"
    if value in {"workflow_hints", "workflow_hint"}:
        return "workflow_hint"
    return "fact"


def _bucket_key(item: MemoryItem) -> tuple[str, str, str | None, str | None, str, str]:
    return (item.user_id, item.scope, item.agent_id, item.workspace_id, item.type, item.section)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-root", default="data/memory")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--import-edited-markdown", action="store_true")
    args = parser.parse_args()
    summary = migrate_memory_root(
        memory_root=args.memory_root,
        db_path=args.db_path,
        dry_run=args.dry_run,
        import_edited_markdown=args.import_edited_markdown,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
