from __future__ import annotations

import re
from pathlib import Path

from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore

_SKILL_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _validate_skill_slug(slug: str) -> str:
    normalized = slug.strip().lower()
    if not _SKILL_SLUG_RE.fullmatch(normalized):
        raise ValueError("skill candidate slug must be lowercase kebab-case")
    return normalized


def _render_skill_markdown(
    *,
    slug: str,
    title: str,
    summary: str,
    body_markdown: str,
    agent_id: str,
) -> str:
    body = body_markdown.strip()
    meta = (
        "---\n"
        f"skill_id: {slug}\n"
        f"name: {title.strip() or slug}\n"
        f"description: {summary.strip() or 'promoted from self-improve candidate'}\n"
        "enabled: true\n"
        f"agents: [{agent_id.strip()}]\n"
        "channels: [http, feishu]\n"
        "tags: [self_improve]\n"
        "---\n\n"
    )
    return meta + body + "\n"


def promote_skill_candidate(
    *,
    store: SQLiteSelfImproveStore,
    candidate_id: str,
    repo_root: str | Path,
) -> dict[str, object]:
    candidate = store.get_skill_candidate(candidate_id)
    if candidate.status != "accepted":
        raise ValueError("skill candidate must be accepted before promotion")
    safe_slug = _validate_skill_slug(candidate.slug)
    skills_root = Path(repo_root) / "skills" / safe_slug
    skill_path = skills_root / "SKILL.md"
    try:
        skills_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError(f"skill already exists: {safe_slug}")
    try:
        with skill_path.open("x", encoding="utf-8") as handle:
            handle.write(
                _render_skill_markdown(
                    slug=safe_slug,
                    title=candidate.title,
                    summary=candidate.summary,
                    body_markdown=candidate.body_markdown,
                    agent_id=candidate.agent_id,
                )
            )
    except FileExistsError as exc:
        raise ValueError(f"skill already exists: {safe_slug}") from exc
    updated = store.mark_skill_candidate_promoted(
        candidate_id,
        promoted_skill_id=safe_slug,
    )
    return {
        "ok": True,
        "candidate": updated.model_dump(mode="json"),
        "skill_path": str(skill_path),
    }
