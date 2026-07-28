from __future__ import annotations

import argparse
import json
from pathlib import Path

from marten_runtime.knowledge.config import load_knowledge_config
from marten_runtime.knowledge.corpus import (
    corpus_report_json,
    load_corpus_manifest,
    plan_corpus_release,
    publish_corpus_release,
)
from marten_runtime.knowledge.service import KnowledgeService


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate, plan, or publish a Knowledge corpus release.")
    parser.add_argument("action", choices=("validate", "plan", "publish"))
    parser.add_argument("--manifest", default="corpora/bazi-theory/v1/manifest.toml")
    parser.add_argument("--config", default="config/knowledge.toml")
    parser.add_argument("--db-path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_path = _path(args.manifest)
    corpus = load_corpus_manifest(manifest_path)
    if args.action == "validate":
        print(corpus_report_json(corpus))
        return 0
    service = KnowledgeService(_config(args.config, args.db_path))
    result = (
        plan_corpus_release(corpus, service.store)
        if args.action == "plan"
        else publish_corpus_release(corpus, service)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _config(config_path: str, db_path: str | None):  # noqa: ANN202
    config = load_knowledge_config(str(_path(config_path))).knowledge
    resolved_db = _path(db_path or config.db_path)
    return config.model_copy(
        update={
            "repo_root": str(REPO_ROOT),
            "db_path": str(resolved_db),
            "embedding": config.embedding.model_copy(update={"local_path": str(_path(config.embedding.local_path))}),
            "reranker": config.reranker.model_copy(update={"local_path": str(_path(config.reranker.local_path))}),
        }
    )


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
