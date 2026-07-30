from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from marten_runtime.knowledge.config import load_knowledge_config, resolve_knowledge_runtime_paths
from marten_runtime.knowledge.corpus import load_corpus_manifest, publish_corpus_release
from marten_runtime.knowledge.corpus_eval import (
    corpus_retrieval_report_markdown,
    evaluate_corpus_retrieval,
    load_corpus_gold_set,
)
from marten_runtime.knowledge.service import KnowledgeService


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the release-bound Knowledge corpus retrieval baseline.")
    parser.add_argument("--manifest", default="corpora/bazi-theory/v1/manifest.toml")
    parser.add_argument("--gold", default="evals/cases/knowledge_corpus/bazi_theory_classics_v1.json")
    parser.add_argument("--config", default="config/knowledge.toml")
    parser.add_argument("--db-path", default="data/knowledge/bazi-theory-baseline.sqlite3")
    parser.add_argument("--report-root", default="reports/knowledge/bazi-theory-classics-selected-v1")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    corpus = load_corpus_manifest(_path(args.manifest))
    gold, gold_sha256 = load_corpus_gold_set(_path(args.gold))
    service = KnowledgeService(_config(args.config, args.db_path))
    publication = publish_corpus_release(corpus, service)
    drift = list(dict(publication.get("after") or {}).get("drift") or [])
    if drift:
        drift_ids = ", ".join(str(item.get("source_id") or "") for item in drift)
        raise RuntimeError(
            "corpus retrieval baseline requires an isolated namespace without manifest drift: "
            + drift_ids
        )
    code_tree_sha256, code_tree_file_count = _candidate_tree_identity()
    report = evaluate_corpus_retrieval(
        corpus=corpus,
        gold_set=gold,
        gold_sha256=gold_sha256,
        service=service,
        code_commit=_commit(),
        code_tree_sha256=code_tree_sha256,
        code_tree_file_count=code_tree_file_count,
    )
    report_root = _path(args.report_root)
    report_root.mkdir(parents=True, exist_ok=True)
    (report_root / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (report_root / "summary.md").write_text(corpus_retrieval_report_markdown(report), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2, sort_keys=True))
    print(f"report_root={report_root}")
    return 0


def _config(config_path: str, db_path: str):  # noqa: ANN202
    config = resolve_knowledge_runtime_paths(
        load_knowledge_config(str(_path(config_path))).knowledge,
        repo_root=REPO_ROOT,
    )
    return config.model_copy(
        update={
            "repo_root": str(REPO_ROOT),
            "db_path": str(_path(db_path)),
            "embedding": config.embedding.model_copy(update={"local_path": str(_path(config.embedding.local_path))}),
            "reranker": config.reranker.model_copy(update={"local_path": str(_path(config.reranker.local_path))}),
        }
    )


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _candidate_tree_identity() -> tuple[str, int]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "unknown", 0
    paths = sorted(
        path
        for path in output.decode("utf-8").split("\0")
        if path and not path.startswith("reports/")
    )
    digest = hashlib.sha256()
    for relative_path in paths:
        path = REPO_ROOT / relative_path
        if not path.is_file():
            continue
        encoded_path = relative_path.encode("utf-8")
        content = path.read_bytes()
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest(), len(paths)


if __name__ == "__main__":
    raise SystemExit(main())
