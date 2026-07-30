from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from marten_runtime.bazi_cases.book_extraction import BookProfile
from marten_runtime.bazi_cases.timing_method_extraction import extract_timing_methods, render_timing_method_markdown
from marten_runtime.knowledge.config import load_knowledge_config, resolve_knowledge_runtime_paths
from marten_runtime.knowledge.service import KnowledgeService


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Import modern Bazi timing methods into theory RAG.")
    parser.add_argument("path")
    parser.add_argument("--title", required=True)
    parser.add_argument("--author", default="")
    parser.add_argument("--namespace", default="bazi-theory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = Path(args.path).resolve()
    sections = extract_timing_methods(path, BookProfile(title=args.title, author=args.author))
    text = render_timing_method_markdown(sections)
    report = {
        "title": args.title,
        "section_count": len(sections),
        "character_count": len(text),
        "methods": sorted({item.method for item in sections}),
    }
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    source_id = "ksrc_timing_" + hashlib.sha256(args.title.encode("utf-8")).hexdigest()[:20]
    config = resolve_knowledge_runtime_paths(
        load_knowledge_config(str(REPO_ROOT / "config/knowledge.toml")).knowledge,
        repo_root=REPO_ROOT,
    )
    result = KnowledgeService(config).replace_text_source_atomically(
        namespace=args.namespace,
        source={
            "source_id": source_id,
            "title": f"{args.title} · 应期与取象方法",
            "kind": "markdown",
            "uri": path.as_uri(),
            "version": hashlib.sha256(path.read_bytes()).hexdigest()[:16],
            "text": text,
            "metadata": {
                "corpus_type": "theory",
                "review_status": "reviewed",
                "evidence_kind": "modern_commentary",
                "content_type": "timing_method",
                "calculation_scope": "theory_interpretation",
                "source_title": args.title,
                "author": args.author,
                "source_path": str(path),
                "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            },
        },
    )
    print(json.dumps({"extraction": report, "ingest": result}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
