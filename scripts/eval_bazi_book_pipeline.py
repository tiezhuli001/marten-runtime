from __future__ import annotations

import json
from pathlib import Path

from marten_runtime.bazi_cases.service import BaziCaseService, owner_key_from_context
from marten_runtime.bazi_cases.sqlite_store import SQLiteBaziCaseStore
from marten_runtime.evals.bazi_book_pipeline import evaluate_book_pipeline
from marten_runtime.knowledge.config import load_knowledge_config, resolve_knowledge_runtime_paths
from marten_runtime.knowledge.service import KnowledgeService


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    case_db = REPO_ROOT / "data/bazi_cases/bazi_cases.sqlite3"
    config = resolve_knowledge_runtime_paths(
        load_knowledge_config(str(REPO_ROOT / "config/knowledge.toml")).knowledge,
        repo_root=REPO_ROOT,
    )
    knowledge = KnowledgeService(config)
    cases = BaziCaseService(SQLiteBaziCaseStore(case_db), knowledge)
    owner_key = owner_key_from_context(
        {"channel_id": "eval", "user_id": "shared-case-pipeline"}
    )
    report = evaluate_book_pipeline(cases, knowledge, owner_key=owner_key)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    metrics = report["metrics"]
    return 0 if (
        metrics["timing_year_recall_at_3_after"] > metrics["timing_year_recall_at_3_before"]
        and metrics["case_retrieval_recall_at_3"] == 1.0
        and metrics["method_rag_recall_at_3"] == 1.0
        and metrics["event_subject_accuracy"] == 1.0
        and metrics["citation_completeness"] == 1.0
        and metrics["prediction_as_event_rate"] == 0.0
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
