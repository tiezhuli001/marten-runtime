from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from marten_runtime.knowledge.config import load_knowledge_config
from marten_runtime.knowledge.corpus_eval import (
    corpus_retrieval_report_markdown,
    evaluate_namespace_retrieval,
    load_corpus_gold_set,
)
from marten_runtime.knowledge.service import KnowledgeService


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate an existing Knowledge namespace.")
    parser.add_argument(
        "--gold",
        default="evals/cases/knowledge_corpus/bazi_theory_sandbox_v1.json",
    )
    parser.add_argument("--config", default="config/knowledge.toml")
    parser.add_argument("--db-path", default="data/knowledge/knowledge.sqlite3")
    parser.add_argument("--report-root", default="reports/knowledge/bazi-theory-sandbox-local-20260728")
    parser.add_argument("--near-duplicate-threshold", type=float, default=0.90)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    gold, gold_sha256 = load_corpus_gold_set(_path(args.gold))
    service = KnowledgeService(_config(args.config, args.db_path))
    _validate_expected_sources(service, namespace=gold.namespace, expected_ids={
        source_id for case in gold.cases for source_id in case.expected_source_ids
    })
    code_tree_sha256, code_tree_file_count = _candidate_tree_identity()
    report = evaluate_namespace_retrieval(
        gold_set=gold,
        gold_sha256=gold_sha256,
        service=service,
        code_commit=_commit(),
        code_tree_sha256=code_tree_sha256,
        code_tree_file_count=code_tree_file_count,
    )
    report["corpus_profile"] = profile_namespace(
        service,
        namespace=gold.namespace,
        near_duplicate_threshold=args.near_duplicate_threshold,
    )
    _redact_result_text(report)
    report_root = _path(args.report_root)
    report_root.mkdir(parents=True, exist_ok=True)
    (report_root / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    markdown = corpus_retrieval_report_markdown(report) + _profile_markdown(report["corpus_profile"])
    (report_root / "summary.md").write_text(markdown, encoding="utf-8")
    print(json.dumps({"metrics": report["metrics"], "corpus_profile": report["corpus_profile"]}, ensure_ascii=False, indent=2))
    print(f"report_root={report_root}")
    return 0


def profile_namespace(service, *, namespace: str, near_duplicate_threshold: float) -> dict[str, object]:  # noqa: ANN001
    chunks = service.store.list_chunks(namespace)
    source_count = service.store.count_sources(namespace)
    source_rows, _ = service.store.list_source_summaries(
        namespace,
        page=1,
        page_size=max(1, source_count),
    )
    source_titles = {
        str(row.get("source_id") or ""): str(row.get("title") or "")
        for row in source_rows
    }
    source_metadata = {
        str(row.get("source_id") or ""): dict(row.get("metadata") or {})
        for row in source_rows
    }
    by_source: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    lengths: list[int] = []
    normalized: list[str] = []
    for chunk in chunks:
        length = len(chunk.text)
        lengths.append(length)
        by_source[chunk.source_id][0] += 1
        by_source[chunk.source_id][1] += length
        normalized.append(re.sub(r"\W+", "", chunk.text).lower())

    exact_counts = Counter(normalized)
    exact_duplicate_pairs = sum(count * (count - 1) // 2 for count in exact_counts.values() if count > 1)
    near_pairs: list[dict[str, object]] = []
    if len(chunks) > 1:
        vectors = HashingVectorizer(
            analyzer="char",
            ngram_range=(3, 5),
            n_features=2**17,
            norm="l2",
            alternate_sign=False,
        ).transform(normalized)
        similarities = cosine_similarity(vectors, dense_output=True)
        np.fill_diagonal(similarities, 0)
        for left in range(len(chunks)):
            for right in range(left + 1, len(chunks)):
                if chunks[left].source_id == chunks[right].source_id:
                    continue
                score = float(similarities[left, right])
                if score < near_duplicate_threshold:
                    continue
                near_pairs.append(
                    {
                        "similarity": round(score, 6),
                        "left_source_id": chunks[left].source_id,
                        "left_ordinal": chunks[left].ordinal,
                        "right_source_id": chunks[right].source_id,
                        "right_ordinal": chunks[right].ordinal,
                    }
                )
    near_pairs.sort(key=lambda item: float(item["similarity"]), reverse=True)
    source_stats = [
        {
            "source_id": source_id,
            "title": source_titles.get(source_id, ""),
            "chunk_count": values[0],
            "indexed_chunk_chars": values[1],
            "extraction_method": str(source_metadata.get(source_id, {}).get("extraction_method") or ""),
        }
        for source_id, values in by_source.items()
    ]
    source_stats.sort(key=lambda item: int(item["chunk_count"]), reverse=True)
    total_chunks = len(chunks)
    ocr_source_ids = {
        source_id
        for source_id, metadata in source_metadata.items()
        if str(metadata.get("extraction_method") or "") == "ocr_unreviewed"
    }
    return {
        "source_count": source_count,
        "chunk_count": total_chunks,
        "indexed_chunk_chars": sum(lengths),
        "chunk_chars_p50": round(statistics.median(lengths)) if lengths else 0,
        "chunk_chars_p95": round(float(np.percentile(lengths, 95))) if lengths else 0,
        "largest_source_chunk_share": (
            round(int(source_stats[0]["chunk_count"]) / total_chunks, 6)
            if source_stats and total_chunks
            else 0.0
        ),
        "ocr_unreviewed_source_count": len(ocr_source_ids),
        "ocr_unreviewed_chunk_count": sum(
            int(item["chunk_count"]) for item in source_stats if item["source_id"] in ocr_source_ids
        ),
        "exact_duplicate_chunk_pairs": exact_duplicate_pairs,
        "near_duplicate_threshold": near_duplicate_threshold,
        "cross_source_near_duplicate_pairs": len(near_pairs),
        "near_duplicate_samples": near_pairs[:20],
        "sources": source_stats,
    }


def _profile_markdown(profile: dict[str, object]) -> str:
    rows = [
        "# Namespace Corpus Profile",
        "",
        f"- Sources: `{profile.get('source_count')}`",
        f"- Chunks: `{profile.get('chunk_count')}`",
        f"- Indexed chunk characters: `{profile.get('indexed_chunk_chars')}`",
        f"- Largest source chunk share: `{profile.get('largest_source_chunk_share')}`",
        f"- OCR unreviewed: `{profile.get('ocr_unreviewed_source_count')}` sources / `{profile.get('ocr_unreviewed_chunk_count')}` chunks",
        f"- Exact duplicate chunk pairs: `{profile.get('exact_duplicate_chunk_pairs')}`",
        (
            f"- Cross-source near-duplicate pairs: `{profile.get('cross_source_near_duplicate_pairs')}` "
            f"at threshold `{profile.get('near_duplicate_threshold')}`"
        ),
        "",
        "| Source | Chunks | Indexed chars | Extraction |",
        "| --- | ---: | ---: | --- |",
    ]
    for source in list(profile.get("sources") or []):
        rows.append(
            f"| {source.get('source_id')} | {source.get('chunk_count')} | "
            f"{source.get('indexed_chunk_chars')} | {source.get('extraction_method')} |"
        )
    return "\n".join(rows) + "\n"


def _redact_result_text(report: dict[str, object]) -> None:
    for case in list(report.get("cases") or []):
        for result in list(case.get("results") or []):
            text = str(result.pop("text", ""))
            result["text_chars"] = len(text)
            result["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_expected_sources(service, *, namespace: str, expected_ids: set[str]) -> None:  # noqa: ANN001
    source_count = service.store.count_sources(namespace)
    rows, _ = service.store.list_source_summaries(
        namespace,
        page=1,
        page_size=max(1, source_count),
    )
    actual_ids = {str(row.get("source_id") or "") for row in rows}
    missing = sorted(expected_ids - actual_ids)
    if missing:
        raise RuntimeError("gold set references missing sources: " + ", ".join(missing))


def _config(config_path: str, db_path: str):  # noqa: ANN202
    config = load_knowledge_config(str(_path(config_path))).knowledge
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
