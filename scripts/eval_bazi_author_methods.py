from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from marten_runtime.knowledge.config import load_knowledge_config, resolve_knowledge_runtime_paths
from marten_runtime.knowledge.service import KnowledgeService


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Bazi author chapter and method-card retrieval.")
    parser.add_argument(
        "--cases",
        default="evals/cases/bazi_case_library/author_methods_v1.json",
    )
    parser.add_argument("--config", default="config/knowledge.toml")
    args = parser.parse_args()
    fixtures = json.loads(_path(args.cases).read_text(encoding="utf-8"))
    config = resolve_knowledge_runtime_paths(
        load_knowledge_config(str(_path(args.config))).knowledge,
        repo_root=REPO_ROOT,
    )
    service = KnowledgeService(config)

    hits = 0
    citation_hits = 0
    full_mode_hits = 0
    details: list[dict[str, object]] = []
    for fixture in fixtures:
        result = service.search(
            namespace="bazi-theory",
            query=str(fixture["query"]),
            top_k=3,
            filters={"content_type": str(fixture["content_type"])},
        )
        matches = list(result.get("results") or [])
        expected = str(fixture["expected_heading"])
        match = next(
            (item for item in matches if expected in str(item.get("heading") or "")),
            None,
        )
        hits += int(match is not None)
        metadata = dict(match.get("metadata") or {}) if match else {}
        citation_complete = bool(
            match
            and metadata.get("source_title")
            and metadata.get("author")
            and re.search(r"原文(?:行|坐标)：\d+[-–]\d+", str(match.get("text") or ""))
        )
        citation_hits += int(citation_complete)
        full_mode = (
            result.get("retrieval_mode") == "hybrid_rerank"
            and result.get("vector_status") == "available"
            and result.get("rerank_status") == "available"
        )
        full_mode_hits += int(full_mode)
        details.append(
            {
                "name": fixture["name"],
                "hit": match is not None,
                "citation_complete": citation_complete,
                "full_retrieval_mode": full_mode,
                "headings": [str(item.get("heading") or "") for item in matches],
            }
        )

    total = max(1, len(fixtures))
    report = {
        "metrics": {
            "author_method_recall_at_3": hits / total,
            "citation_completeness": citation_hits / total,
            "hybrid_rerank_availability": full_mode_hits / total,
        },
        "queries": details,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all(value == 1.0 for value in report["metrics"].values()) else 1


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
