from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from marten_runtime.bazi_cases.author_experience import (
    author_material_report,
    extract_author_material,
    render_author_chapters,
    render_author_experience_cards,
)
from marten_runtime.bazi_cases.book_extraction import BookProfile
from marten_runtime.knowledge.config import load_knowledge_config, resolve_knowledge_runtime_paths
from marten_runtime.knowledge.service import KnowledgeService


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Import complete Bazi teaching chapters and author method cards.")
    parser.add_argument("path")
    parser.add_argument("--title", required=True)
    parser.add_argument("--author", default="")
    parser.add_argument("--namespace", default="bazi-theory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = Path(args.path).resolve()
    chapters, cards = extract_author_material(path, BookProfile(title=args.title, author=args.author))
    report = author_material_report(chapters, cards)
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    base = hashlib.sha256(args.title.encode("utf-8")).hexdigest()[:20]
    common = {
        "corpus_type": "theory",
        "review_status": "reviewed",
        "evidence_kind": "modern_commentary",
        "calculation_scope": "theory_interpretation",
        "source_title": args.title,
        "author": args.author,
        "source_path": str(path),
        "content_sha256": digest,
    }
    config = resolve_knowledge_runtime_paths(
        load_knowledge_config(str(REPO_ROOT / "config/knowledge.toml")).knowledge,
        repo_root=REPO_ROOT,
    )
    service = KnowledgeService(config)
    results = []
    for suffix, label, text, content_type in (
        ("chapters", "完整教学章节", render_author_chapters(chapters), "author_chapter"),
        ("methods", "作者经验卡", render_author_experience_cards(cards), "author_method"),
    ):
        results.append(
            service.replace_text_source_atomically(
                namespace=args.namespace,
                source={
                    "source_id": f"ksrc_author_{suffix}_{base}",
                    "title": f"{args.title} · {label}",
                    "kind": "markdown",
                    "uri": path.as_uri(),
                    "version": digest[:16],
                    "text": text,
                    "metadata": {**common, "content_type": content_type},
                },
            )
        )
    print(json.dumps({"extraction": report, "ingest": results}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all(result.get("ok") for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
