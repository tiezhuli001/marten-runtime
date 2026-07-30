from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from marten_runtime.bazi_cases.service import (
    BaziCaseService,
    owner_key_from_context,
)
from marten_runtime.bazi_cases.sqlite_store import SQLiteBaziCaseStore
from marten_runtime.evals.bazi_case_library import evaluate_private_case_retrieval
from marten_runtime.knowledge.config import load_knowledge_config, resolve_knowledge_runtime_paths
from marten_runtime.knowledge.service import KnowledgeService


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate private Bazi case retrieval.")
    parser.add_argument(
        "--cases",
        default="evals/cases/bazi_case_library/private_cases_v1.json",
    )
    parser.add_argument("--config", default="config/knowledge.toml")
    args = parser.parse_args()
    fixtures = json.loads(_path(args.cases).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = resolve_knowledge_runtime_paths(
            load_knowledge_config(str(_path(args.config))).knowledge,
            repo_root=REPO_ROOT,
        )
        config = config.model_copy(
            update={
                "db_path": str(root / "knowledge.sqlite3"),
                "repo_root": str(REPO_ROOT),
                "prewarm_on_start": False,
                "embedding": config.embedding.model_copy(
                    update={"local_path": str(_path(config.embedding.local_path))}
                ),
                "reranker": config.reranker.model_copy(
                    update={"local_path": str(_path(config.reranker.local_path))}
                ),
            }
        )
        service = BaziCaseService(
            SQLiteBaziCaseStore(root / "bazi_cases.sqlite3"),
            KnowledgeService(config),
        )
        owner = owner_key_from_context(
            {"channel_id": "eval", "user_id": "private-case-fixture"}
        )
        report = evaluate_private_case_retrieval(service, owner_key=owner, cases=fixtures)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    metrics = report["metrics"]
    return 0 if (
        metrics["exact_recall_at_1"] == 1.0
        and metrics["near_recall_at_3"] >= 0.85
        and metrics["with_cases_verified_event_recall_at_3"] >= 0.80
        and metrics["verified_event_recall_lift"] >= 0.20
        and metrics["result_contract_completeness"] == 1.0
        and metrics["owner_leakage"] == 0
        and metrics["prediction_as_event"] == 0
        and metrics["builtin_fact_conflicts"] == 0
    ) else 1


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
