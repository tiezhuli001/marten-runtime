from __future__ import annotations

import argparse
import json
from pathlib import Path

from marten_runtime.bazi_cases.service import BaziCaseService
from marten_runtime.bazi_cases.sqlite_store import SQLiteBaziCaseStore
from marten_runtime.knowledge.config import load_knowledge_config, resolve_knowledge_runtime_paths
from marten_runtime.knowledge.service import KnowledgeService


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote trusted operator-imported Bazi cases into the shared curated library."
    )
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-title", required=True)
    parser.add_argument("--source-path", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    case_db = REPO_ROOT / "data/bazi_cases/bazi_cases.sqlite3"
    config = resolve_knowledge_runtime_paths(
        load_knowledge_config(str(REPO_ROOT / "config/knowledge.toml")).knowledge,
        repo_root=REPO_ROOT,
    )
    service = BaziCaseService(SQLiteBaziCaseStore(case_db), KnowledgeService(config))
    matches = [
        record
        for owner in service.store.list_active_private_owners()
        for record in service.store.list(owner)
        if record.source_type == "operator_imported"
        and record.source_run_id == args.source_run_id
    ]
    preview = {
        "source_run_id": args.source_run_id,
        "matched_count": len(matches),
        "case_ids": [record.case_id for record in matches],
    }
    if args.dry_run or not matches:
        print(json.dumps(preview, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    owners = {record.owner_key for record in matches}
    if len(owners) != 1:
        raise RuntimeError("matched cases must belong to exactly one owner")
    result = service.promote_private_imports_to_shared(
        owner_key=next(iter(owners)),
        case_ids=[record.case_id for record in matches],
        source_ref_defaults={
            "title": args.source_title,
            "path": args.source_path,
        },
    )
    print(json.dumps({**preview, "migration": result}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
