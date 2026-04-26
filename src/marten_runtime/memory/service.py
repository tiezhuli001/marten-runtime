from __future__ import annotations

from urllib.parse import quote
from pathlib import Path

from marten_runtime.memory.models import MemoryDocument
from marten_runtime.memory.render import render_memory_block


class ThinMemoryService:
    def __init__(
        self,
        root: str | Path,
        *,
        max_write_chars: int = 1000,
        prompt_char_limit: int = 400,
    ) -> None:
        self.root = Path(root)
        self.max_write_chars = max_write_chars
        self.prompt_char_limit = prompt_char_limit

    def has_stable_user_id(self, user_id: str) -> bool:
        return bool(str(user_id or "").strip())

    def memory_path(self, user_id: str) -> Path:
        if not self.has_stable_user_id(user_id):
            raise ValueError("stable user_id is required")
        encoded = quote(str(user_id).strip(), safe="-_.~")
        return self.root / "users" / encoded / "MEMORY.md"

    def load(self, user_id: str) -> MemoryDocument:
        if not self.has_stable_user_id(user_id):
            return MemoryDocument(
                user_id="",
                path=self.root / "users" / "_anonymous" / "MEMORY.md",
                available=False,
            )
        path = self.memory_path(user_id)
        if not path.exists():
            return MemoryDocument(user_id=user_id, path=path, text="", sections={})
        text = path.read_text(encoding="utf-8")
        return MemoryDocument(
            user_id=user_id,
            path=path,
            text=text,
            sections=_parse_sections(text),
        )

    def render_prompt_memory(self, user_id: str) -> str | None:
        document = self.load(user_id)
        if not document.available:
            return None
        return render_memory_block(document.text, char_limit=self.prompt_char_limit)

    def append(self, user_id: str, *, section: str, content: str) -> MemoryDocument:
        self._validate_write(content)
        document = self._require_document(user_id)
        key = _normalize_section(section)
        entry = _normalize_entry(content)
        items = list(document.sections.get(key, []))
        if entry not in items:
            items.append(entry)
        document.sections[key] = items
        return self._save(document)

    def replace(self, user_id: str, *, section: str, content: str) -> MemoryDocument:
        self._validate_write(content)
        document = self._require_document(user_id)
        key = _normalize_section(section)
        entries = [
            _normalize_entry(line)
            for line in str(content).splitlines()
            if _normalize_entry(line)
        ]
        document.sections[key] = entries or [_normalize_entry(content)]
        return self._save(document)

    def delete(
        self,
        user_id: str,
        *,
        section: str,
        content: str | None = None,
    ) -> MemoryDocument:
        document = self._require_document(user_id)
        key = _normalize_section(section)
        if key not in document.sections:
            return document
        if content is None:
            del document.sections[key]
            return self._save(document)
        entry = _normalize_entry(content)
        document.sections[key] = [
            item for item in document.sections[key] if item != entry
        ]
        if not document.sections[key]:
            del document.sections[key]
        return self._save(document)

    def _require_document(self, user_id: str) -> MemoryDocument:
        document = self.load(user_id)
        if not document.available:
            raise ValueError("stable user_id is required")
        return document

    def _save(self, document: MemoryDocument) -> MemoryDocument:
        text = _render_sections(document.sections)
        document.path.parent.mkdir(parents=True, exist_ok=True)
        document.path.write_text(text, encoding="utf-8")
        document.text = text
        return document

    def _validate_write(self, content: str) -> None:
        normalized = _normalize_entry(content)
        if not normalized:
            raise ValueError("content is required")
        if len(normalized) > self.max_write_chars:
            raise ValueError("memory write too large")


def _parse_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current = _normalize_section(line[3:])
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        if line.startswith("- "):
            entry = _normalize_entry(line[2:])
            if entry:
                sections[current].append(entry)
    return sections


def _render_sections(sections: dict[str, list[str]]) -> str:
    if not sections:
        return ""
    lines = ["# MEMORY"]
    for section in sorted(sections):
        items = [item for item in sections[section] if item]
        if not items:
            continue
        lines.append("")
        lines.append(f"## {section}")
        lines.extend(f"- {item}" for item in items)
    return "\n".join(lines).strip() + "\n"


def _normalize_section(section: str) -> str:
    value = " ".join(str(section).split()).strip().lower()
    if not value:
        raise ValueError("section is required")
    return value


def _normalize_entry(content: str) -> str:
    return " ".join(str(content).split()).strip()
