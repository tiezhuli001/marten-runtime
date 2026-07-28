from __future__ import annotations

import unittest
from types import SimpleNamespace

from marten_runtime.knowledge.corpus_eval import (
    KnowledgeCorpusGoldCase,
    KnowledgeCorpusGoldSet,
    evaluate_corpus_retrieval,
    evaluate_namespace_retrieval,
)


class _SearchService:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = iter(responses)
        self.embedding_config_hash = "embedding-hash"
        self.store = _SnapshotStore()
        self.config = SimpleNamespace(
            file_encoding="auto",
            chunking=SimpleNamespace(target_chars=100, overlap_chars=10, max_chars=150, batch_size=4),
            embedding=SimpleNamespace(
                enabled=True,
                provider="fake",
                model="embedding-model",
                dimension=8,
                use_fp16=False,
            ),
            reranker=SimpleNamespace(
                enabled=True,
                provider="fake",
                model="reranker-model",
                use_fp16=False,
                top_n=10,
            ),
            vector_store=SimpleNamespace(enabled=True, backend="json_cosine"),
            search=SimpleNamespace(
                default_top_k=5,
                candidate_pool=20,
                fts_weight=0.3,
                vector_weight=0.5,
                metadata_weight=0.1,
                reranker_weight=0.7,
            ),
        )

    def search(self, **_: object) -> dict[str, object]:
        return next(self._responses)


class KnowledgeCorpusGraderTests(unittest.TestCase):
    def test_metrics_cover_rank_citations_headings_empty_and_forbidden_sources(self) -> None:
        corpus = SimpleNamespace(
            manifest=SimpleNamespace(release_id="release-v1", namespace="bazi-theory"),
            manifest_sha256="manifest-sha",
        )
        gold = KnowledgeCorpusGoldSet(
            schema_version="knowledge.corpus.gold.v1",
            release_id="release-v1",
            namespace="bazi-theory",
            cases=[
                KnowledgeCorpusGoldCase(
                    case_id="rank-two",
                    query="query one",
                    expected_source_ids=["expected-one"],
                    expected_headings=["古籍原文"],
                ),
                KnowledgeCorpusGoldCase(
                    case_id="incomplete-forbidden",
                    query="query two",
                    expected_source_ids=["expected-two"],
                    expected_headings=["Marten 释义"],
                    forbidden_source_ids=["forbidden"],
                ),
                KnowledgeCorpusGoldCase(
                    case_id="empty",
                    query="query three",
                    expected_source_ids=["expected-three"],
                ),
            ],
        )
        service = _SearchService(
            [
                self._search_result(
                    [
                        self._result("other", heading="其他", complete=True),
                        self._result("expected-one", heading="古籍原文", complete=True),
                    ]
                ),
                self._search_result(
                    [
                        self._result("expected-two", heading="古籍原文", complete=False),
                        self._result("forbidden", heading="Marten 释义", complete=True),
                    ]
                ),
                self._search_result([]),
            ]
        )

        report = evaluate_corpus_retrieval(
            corpus=corpus,
            gold_set=gold,
            gold_sha256="gold-sha",
            service=service,
            code_commit="commit-sha",
            code_tree_sha256="tree-sha",
            code_tree_file_count=42,
        )

        self.assertEqual(
            report["metrics"],
            {
                "case_count": 3,
                "recall_at_1": 1 / 3,
                "recall_at_3": 2 / 3,
                "recall_at_5": 2 / 3,
                "mrr": 0.5,
                "expected_source_first_rate": 1 / 3,
                "citation_metadata_complete_rate": 1 / 3,
                "heading_match_rate": 1 / 3,
                "first_evidence_kind_match_rate": 2 / 3,
                "required_text_match_rate": 1.0,
                "mean_duplicate_source_ratio": 0.0,
                "empty_result_count": 1,
                "false_positive_case_count": 1,
            },
        )
        self.assertEqual(report["manifest_sha256"], "manifest-sha")
        self.assertEqual(report["gold_sha256"], "gold-sha")
        self.assertEqual(report["embedding_config_hash"], "embedding-hash")
        self.assertEqual(report["code_commit"], "commit-sha")
        self.assertEqual(report["code_tree_sha256"], "tree-sha")
        self.assertEqual(report["code_tree_file_count"], 42)
        self.assertEqual(report["knowledge_config"]["evaluation_top_k"], 5)
        self.assertEqual(report["knowledge_config"]["search"]["candidate_pool"], 20)
        self.assertRegex(str(report["knowledge_config_sha256"]), r"^[0-9a-f]{64}$")
        self.assertRegex(str(report["knowledge_snapshot"]["sha256"]), r"^[0-9a-f]{64}$")
        self.assertEqual(report["knowledge_snapshot"]["source_count"], 1)
        self.assertEqual(report["knowledge_snapshot"]["chunk_count"], 1)
        self.assertEqual(report["knowledge_snapshot"]["current_embedding_count"], 1)

    def test_release_or_namespace_mismatch_is_rejected(self) -> None:
        corpus = SimpleNamespace(
            manifest=SimpleNamespace(release_id="release-v1", namespace="bazi-theory"),
            manifest_sha256="manifest-sha",
        )
        gold = KnowledgeCorpusGoldSet(
            schema_version="knowledge.corpus.gold.v1",
            release_id="release-v2",
            namespace="bazi-theory",
            cases=[
                KnowledgeCorpusGoldCase(
                    case_id="mismatch",
                    query="query",
                    expected_source_ids=["expected"],
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "does not match corpus manifest"):
            evaluate_corpus_retrieval(
                corpus=corpus,
                gold_set=gold,
                gold_sha256="gold-sha",
                service=_SearchService([]),
                code_commit="commit-sha",
                code_tree_sha256="tree-sha",
                code_tree_file_count=42,
            )

    def test_namespace_evaluation_uses_dataset_metadata_contract(self) -> None:
        gold = KnowledgeCorpusGoldSet(
            schema_version="knowledge.corpus.gold.v1",
            release_id="sandbox-v1",
            namespace="bazi-theory",
            required_metadata_fields=["source_url"],
            cases=[
                KnowledgeCorpusGoldCase(
                    case_id="sandbox-source",
                    query="query",
                    expected_source_ids=["expected-one"],
                )
            ],
        )

        report = evaluate_namespace_retrieval(
            gold_set=gold,
            gold_sha256="gold-sha",
            service=_SearchService(
                [self._search_result([self._result("expected-one", heading="", complete=True)])]
            ),
            code_commit="commit-sha",
            code_tree_sha256="tree-sha",
            code_tree_file_count=42,
        )

        self.assertEqual(report["manifest_sha256"], "runtime-namespace")
        self.assertEqual(report["required_metadata_fields"], ["source_url"])
        self.assertEqual(report["metrics"]["citation_metadata_complete_rate"], 1.0)

    @staticmethod
    def _search_result(results: list[dict[str, object]]) -> dict[str, object]:
        return {
            "ok": True,
            "retrieval_mode": "hybrid_rerank",
            "vector_status": "available",
            "rerank_status": "available",
            "degraded_reason": "",
            "results": results,
        }

    @staticmethod
    def _result(source_id: str, *, heading: str, complete: bool) -> dict[str, object]:
        metadata = {
            "work": "经典",
            "chapter": "章节",
            "edition_or_source": "版本",
            "source_url": "https://example.test/source",
            "verification_status": "verified",
            "license": "public-domain",
            "provenance": "fixed source",
            "corpus_release_id": "release-v1",
        }
        if not complete:
            metadata.pop("source_url")
        return {
            "source_id": source_id,
            "heading": heading,
            "metadata": metadata,
        }


class _SnapshotStore:
    def count_sources(self, namespace: str) -> int:
        return int(namespace == "bazi-theory")

    def list_source_summaries(self, namespace: str, *, page: int, page_size: int):  # noqa: ANN201
        del page, page_size
        if namespace != "bazi-theory":
            return [], 0
        return [
            {
                "source_id": "expected-one",
                "title": "经典",
                "kind": "markdown",
                "uri": "https://example.test/source",
                "version": "v1",
                "metadata": {"review_status": "reviewed"},
            }
        ], 1

    def list_chunks(self, namespace: str):  # noqa: ANN201
        if namespace != "bazi-theory":
            return []
        return [
            SimpleNamespace(
                chunk_id="chunk-one",
                source_id="expected-one",
                ordinal=0,
                heading="古籍原文",
                text="天地之间。",
                token_estimate=6,
                metadata={"review_status": "reviewed"},
            )
        ]

    def list_embeddings(self, namespace: str, embedding_config_hash: str):  # noqa: ANN201
        if namespace != "bazi-theory" or embedding_config_hash != "embedding-hash":
            return []
        return [SimpleNamespace(chunk_id="chunk-one")]


if __name__ == "__main__":
    unittest.main()
