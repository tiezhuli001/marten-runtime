from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from marten_runtime.bazi_cases.book_extraction import BookProfile, extract_book_cases, extraction_report
from marten_runtime.bazi_cases.service import BaziCaseService
from marten_runtime.bazi_cases.sqlite_store import SQLiteBaziCaseStore
from marten_runtime.knowledge.config import load_knowledge_config, resolve_knowledge_runtime_paths
from marten_runtime.knowledge.service import KnowledgeService


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Import A/B Bazi book cases into the shared curated library.")
    parser.add_argument("path")
    parser.add_argument("--title", required=True)
    parser.add_argument("--author", default="")
    parser.add_argument("--owner-key", default="")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    candidates = extract_book_cases(args.path, BookProfile(title=args.title, author=args.author))
    report = extraction_report(candidates)
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    accepted_items = [item.as_import_item() for item in candidates if item.grade in {"A", "B"}]
    source_digests = {
        str(item.get("source_ref", {}).get("content_sha256") or "").strip()
        for item in accepted_items
    }
    source_digests.discard("")
    if not accepted_items:
        raise RuntimeError("no grade A/B cases were extracted; no data was changed")
    if len(source_digests) != 1:
        raise RuntimeError("accepted cases must have one non-empty source content digest")
    source_digest = next(iter(source_digests))

    case_db = REPO_ROOT / "data/bazi_cases/bazi_cases.sqlite3"
    owner_key = args.owner_key or (_single_owner(case_db) if args.private else "")
    config = resolve_knowledge_runtime_paths(
        load_knowledge_config(str(REPO_ROOT / "config/knowledge.toml")).knowledge,
        repo_root=REPO_ROOT,
    )
    service = BaziCaseService(SQLiteBaziCaseStore(case_db), KnowledgeService(config))
    result = service.import_candidates(
        owner_key=owner_key,
        candidates=accepted_items,
        run_id=f"book-import:{Path(args.path).name}",
        replace_existing=True,
        shared=not args.private,
    )
    accepted_fingerprints = {str(item["input_fingerprint"]) for item in accepted_items}
    archived: list[str] = []
    from marten_runtime.bazi_cases.models import SHARED_CASE_OWNER_KEY

    target_owner = owner_key if args.private else SHARED_CASE_OWNER_KEY
    for record in service.store.list(target_owner):
        if (
            record.source_type == "operator_imported"
            and record.source_ref.content_sha256 == source_digest
            and record.input_fingerprint not in accepted_fingerprints
        ):
            service.archive(owner_key=target_owner, case_id=record.case_id)
            archived.append(record.case_id)
    result["archived_rejected_count"] = len(archived)
    if not args.private:
        result.update(
            service.archive_private_imports_replaced_by_shared(
                content_sha256=source_digest,
                accepted_fingerprints=accepted_fingerprints,
            )
        )
    print(json.dumps({"extraction": report, "import": result}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _single_owner(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        owners = [
            str(row[0])
            for row in conn.execute(
                "SELECT DISTINCT owner_key FROM bazi_cases WHERE status='active_private'"
            )
        ]
    if len(owners) != 1:
        raise RuntimeError("--owner-key is required unless the case database has exactly one active owner")
    return owners[0]


if __name__ == "__main__":
    raise SystemExit(main())
