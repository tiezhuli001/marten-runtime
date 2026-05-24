import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from marten_runtime.knowledge.config import KnowledgeRerankerConfig
from marten_runtime.knowledge.rerankers import FakeReranker, LocalModelReranker, RerankStatus, weighted_rerank


class KnowledgeRerankerTests(unittest.TestCase):
    def test_fake_reranker_orders_by_query_overlap(self) -> None:
        reranker = FakeReranker()

        result = reranker.rerank("师父 山门", ["无关内容", "山门里师父出现"], top_n=2)

        self.assertEqual(result.status, RerankStatus.AVAILABLE)
        self.assertEqual([item.index for item in result.items], [1, 0])

    def test_local_model_reranker_reports_missing_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = KnowledgeRerankerConfig(
                enabled=True,
                provider="flag_embedding",
                model="BAAI/bge-reranker-base",
                local_path=str(Path(tmp) / "missing"),
                top_n=10,
            )

            result = LocalModelReranker(config).rerank("query", ["passage"], top_n=1)

            self.assertEqual(result.status, RerankStatus.MISSING_MODEL)
            self.assertEqual(result.items, [])

    def test_disabled_reranker_returns_disabled(self) -> None:
        config = KnowledgeRerankerConfig(
            enabled=False,
            provider="flag_embedding",
            model="BAAI/bge-reranker-base",
            local_path="data/models/rerankers/BAAI/bge-reranker-base",
            top_n=10,
        )

        result = LocalModelReranker(config).rerank("query", ["passage"], top_n=1)

        self.assertEqual(result.status, RerankStatus.DISABLED)

    def test_local_model_reranker_reports_missing_runtime_when_path_exists_without_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model"
            model_path.mkdir()
            config = KnowledgeRerankerConfig(
                enabled=True,
                provider="flag_embedding",
                model="BAAI/bge-reranker-base",
                local_path=str(model_path),
                top_n=10,
            )

            result = LocalModelReranker(config).rerank("query", ["passage"], top_n=1)

            self.assertEqual(result.status, RerankStatus.MISSING_MODEL)
            self.assertIn("Reranker model failed", result.message)


    def test_local_model_reranker_uses_cross_encoder_for_sequence_classification_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model"
            model_path.mkdir()
            (model_path / "config.json").write_text(
                '{"architectures":["XLMRobertaForSequenceClassification"]}',
                encoding="utf-8",
            )
            config = KnowledgeRerankerConfig(
                enabled=True,
                provider="flag_embedding",
                model="BAAI/bge-reranker-base",
                local_path=str(model_path),
                top_n=10,
            )
            fake_cross_encoder = Mock()
            fake_cross_encoder.predict.return_value = [0.1, 0.9]

            with patch("sentence_transformers.CrossEncoder", return_value=fake_cross_encoder) as factory:
                result = LocalModelReranker(config).rerank("query", ["first", "second"], top_n=2)

            factory.assert_called_once_with(str(model_path))
            fake_cross_encoder.predict.assert_called_once_with([["query", "first"], ["query", "second"]])
            self.assertEqual(result.status, RerankStatus.AVAILABLE)
            self.assertEqual([item.index for item in result.items], [1, 0])

    def test_weighted_rerank_orders_by_existing_scores(self) -> None:
        items = [
            {"id": "a", "score_parts": {"fts": 0.1, "vector": 0.2, "metadata": 0.0}},
            {"id": "b", "score_parts": {"fts": 0.9, "vector": 0.8, "metadata": 0.1}},
        ]

        ranked = weighted_rerank(items)

        self.assertEqual([item["id"] for item in ranked], ["b", "a"])


class KnowledgeRerankerModelLifecycleTests(unittest.TestCase):
    def test_fake_reranker_reports_and_unloads_loaded_state(self) -> None:
        reranker = FakeReranker(model_id="fake-reranker")
        self.assertFalse(reranker.is_loaded())

        reranker.rerank("query", ["query passage"], top_n=1)

        self.assertTrue(reranker.is_loaded())
        status = reranker.model_status(idle_ttl_seconds=300)
        self.assertEqual(status["status"], "loaded")
        self.assertEqual(status["model_id"], "fake-reranker")
        self.assertTrue(reranker.unload())
        self.assertEqual(reranker.model_status(idle_ttl_seconds=300)["status"], "not_loaded")

    def test_local_model_reranker_unload_releases_cached_model(self) -> None:
        config = KnowledgeRerankerConfig(
            enabled=True,
            provider="flag_embedding",
            model="BAAI/bge-reranker-base",
            local_path="data/models/rerankers/BAAI/bge-reranker-base",
            top_n=10,
        )
        reranker = LocalModelReranker(config)
        reranker._model = object()
        reranker.state.mark_loaded()

        unloaded = reranker.unload()

        self.assertTrue(unloaded)
        self.assertIsNone(reranker._model)
        self.assertFalse(reranker.is_loaded())
        self.assertEqual(reranker.model_status(idle_ttl_seconds=300)["status"], "not_loaded")

    def test_local_model_reranker_unload_is_idempotent_when_not_loaded(self) -> None:
        config = KnowledgeRerankerConfig(
            enabled=True,
            provider="flag_embedding",
            model="BAAI/bge-reranker-base",
            local_path="data/models/rerankers/BAAI/bge-reranker-base",
            top_n=10,
        )
        reranker = LocalModelReranker(config)

        unloaded = reranker.unload()

        self.assertFalse(unloaded)
        self.assertIsNone(reranker._model)
        self.assertEqual(reranker.model_status(idle_ttl_seconds=300)["status"], "not_loaded")


if __name__ == "__main__":
    unittest.main()
