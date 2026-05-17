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
        parsed = _parse_markdown_memory(user_id, path.read_text(encoding="utf-8"))
        planned.extend(parsed.items)
        for key in parsed.represented_buckets:
            represented.setdefault(key, [])
        for item in parsed.items:
            represented.setdefault(_bucket_key(item), []).append(item)
    if not import_edited_markdown:
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
    else:
        existing_keys = _active_item_keys(store, planned)
        filtered: list[MemoryItem] = []
        skipped_count = 0
        for item in planned:
            key = _dedupe_key(item)
            if key in existing_keys:
                skipped_count += 1
                continue
            existing_keys.add(key)
            filtered.append(item)
        planned = filtered
        summary["changed_item_count"] = len(planned)
        summary["skipped_count"] = skipped_count
    for item in planned:
        store.append(item)
    export_user_ids = {item.user_id for item in planned}
    if import_edited_markdown:
        export_user_ids.update(key[0] for key in represented)
    for user_id in sorted(export_user_ids):
        write_memory_export(root, user_id, store.list_active(user_id))
    return summary


class ParsedMarkdownMemory:
    def __init__(
        self,
        *,
        items: list[MemoryItem],
        represented_buckets: set[tuple[str, str, str | None, str | None, str, str]],
    ) -> None:
        self.items = items
        self.represented_buckets = represented_buckets


def _parse_markdown_memory(user_id: str, text: str) -> ParsedMarkdownMemory:
    items = _items_from_markdown(user_id, text)
    represented_buckets: set[tuple[str, str, str | None, str | None, str, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("## "):
            continue
        scope, agent_id, workspace_id, memory_type, section = _parse_heading(line[3:].strip())
        represented_buckets.add((user_id, scope, agent_id, workspace_id, memory_type, section))
    for item in items:
        represented_buckets.add(_bucket_key(item))
    return ParsedMarkdownMemory(items=items, represented_buckets=represented_buckets)


def _items_from_markdown(user_id: str, text: str) -> list[MemoryItem]:
    items: list[MemoryItem] = []
    current_section: str | None = None
    current_type: str = "fact"
    current_scope = "global"
    current_agent_id: str | None = None
    current_workspace_id: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            heading = line[3:].strip()
            current_scope, current_agent_id, current_workspace_id, current_type, current_section = _parse_heading(heading)
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
            type=current_type,
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


def _parse_heading(heading: str) -> tuple[str, str | None, str | None, str, str]:
    parts = [part.strip() for part in heading.split("/")]
    if len(parts) == 1:
        section = _normalize_section(parts[0])
        return "global", None, None, _type_from_section(section), section
    if len(parts) >= 3 and _normalize_type(parts[1]) is not None:
        scope_part = parts[0]
        memory_type = _normalize_type(parts[1]) or "fact"
        section = "/".join(parts[2:])
    else:
        scope_part = parts[0]
        section = "/".join(parts[1:])
        memory_type = _type_from_section(section)
    if scope_part.startswith("agent:"):
        return "agent", unquote(scope_part.split(":", 1)[1].strip()), None, memory_type, _normalize_section(section)
    if scope_part.startswith("workspace:"):
        return "workspace", None, unquote(scope_part.split(":", 1)[1].strip()), memory_type, _normalize_section(section)
    return "global", None, None, memory_type, _normalize_section(section)


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


def _normalize_type(value: str) -> str | None:
    normalized = " ".join(str(value or "").split()).strip().lower()
    if normalized in {"preference", "fact", "constraint", "workflow_hint"}:
        return normalized
    return None


def _bucket_key(item: MemoryItem) -> tuple[str, str, str | None, str | None, str, str]:
    return (item.user_id, item.scope, item.agent_id, item.workspace_id, item.type, item.section)


def _dedupe_key(item: MemoryItem) -> tuple[str, str, str | None, str | None, str, str, str]:
    return (
        item.user_id,
        item.scope,
        item.agent_id,
        item.workspace_id,
        item.type,
        item.section,
        item.content,
    )


def _active_item_keys(
    store: SQLiteMemoryStore,
    planned: list[MemoryItem],
) -> set[tuple[str, str, str | None, str | None, str, str, str]]:
    keys: set[tuple[str, str, str | None, str | None, str, str, str]] = set()
    seen_users = {item.user_id for item in planned}
    for user_id in seen_users:
        for item in store.list_active(user_id):
            keys.add(_dedupe_key(item))
    return keys


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
