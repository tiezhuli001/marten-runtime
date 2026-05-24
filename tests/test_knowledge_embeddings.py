import tempfile
import unittest
from pathlib import Path

from marten_runtime.knowledge.config import KnowledgeEmbeddingConfig, embedding_config_hash
from marten_runtime.knowledge.embeddings import EmbeddingStatus, FakeEmbeddingAdapter, LocalModelEmbeddingAdapter


class KnowledgeEmbeddingTests(unittest.TestCase):
    def test_fake_embedder_is_deterministic_and_preserves_order(self) -> None:
        adapter = FakeEmbeddingAdapter(dimension=4)

        first = adapter.embed_texts(["alpha", "beta", "alpha"])
        second = adapter.embed_texts(["alpha", "beta", "alpha"])

        self.assertEqual(first.status, EmbeddingStatus.AVAILABLE)
        self.assertEqual(first.vectors, second.vectors)
        self.assertEqual(first.vectors[0], first.vectors[2])
        self.assertNotEqual(first.vectors[0], first.vectors[1])
        self.assertTrue(all(len(vector) == 4 for vector in first.vectors))

    def test_local_model_adapter_reports_missing_model_without_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = KnowledgeEmbeddingConfig(
                enabled=True,
                provider="flag_embedding",
                model="BAAI/bge-small-zh-v1.5",
                local_path=str(Path(tmp) / "missing"),
                dimension=512,
                allow_remote_download=False,
            )
            adapter = LocalModelEmbeddingAdapter(config)

            result = adapter.embed_texts(["hello"])

            self.assertEqual(result.status, EmbeddingStatus.MISSING_MODEL)
            self.assertEqual(result.vectors, [])
            self.assertIn("local_path", result.message)

    def test_disabled_adapter_returns_disabled(self) -> None:
        config = KnowledgeEmbeddingConfig(
            enabled=False,
            provider="flag_embedding",
            model="BAAI/bge-small-zh-v1.5",
            local_path="data/models/embeddings/BAAI/bge-small-zh-v1.5",
            dimension=512,
        )

        result = LocalModelEmbeddingAdapter(config).embed_texts(["hello"])

        self.assertEqual(result.status, EmbeddingStatus.DISABLED)
        self.assertEqual(result.vectors, [])

    def test_local_model_adapter_reports_missing_runtime_when_path_exists_without_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model"
            model_path.mkdir()
            config = KnowledgeEmbeddingConfig(
                enabled=True,
                provider="flag_embedding",
                model="BAAI/bge-small-zh-v1.5",
                local_path=str(model_path),
                dimension=512,
                allow_remote_download=False,
            )

            result = LocalModelEmbeddingAdapter(config).embed_texts(["hello"])

            self.assertEqual(result.status, EmbeddingStatus.MISSING_MODEL)
            self.assertIn("Embedding model failed", result.message)

    def test_embedding_hash_uses_vector_space_fields(self) -> None:
        config = KnowledgeEmbeddingConfig(
            enabled=True,
            provider="flag_embedding",
            model="BAAI/bge-small-zh-v1.5",
            local_path="data/models/embeddings/BAAI/bge-small-zh-v1.5",
            dimension=512,
        )
        changed = config.model_copy(update={"dimension": 768})

        self.assertNotEqual(embedding_config_hash(config), embedding_config_hash(changed))


class KnowledgeEmbeddingModelLifecycleTests(unittest.TestCase):
    def test_fake_adapter_reports_and_unloads_loaded_state(self) -> None:
        adapter = FakeEmbeddingAdapter(dimension=4, model_id="fake-embedding")
        self.assertFalse(adapter.is_loaded())

        adapter.embed_texts(["alpha"])

        self.assertTrue(adapter.is_loaded())
        status = adapter.model_status(idle_ttl_seconds=300)
        self.assertEqual(status["status"], "loaded")
        self.assertEqual(status["model_id"], "fake-embedding")
        self.assertTrue(adapter.unload())
        self.assertFalse(adapter.is_loaded())
        self.assertEqual(adapter.model_status(idle_ttl_seconds=300)["status"], "not_loaded")

    def test_local_model_adapter_unload_releases_cached_model(self) -> None:
        config = KnowledgeEmbeddingConfig(
            enabled=True,
            provider="flag_embedding",
            model="BAAI/bge-small-zh-v1.5",
            local_path="data/models/embeddings/BAAI/bge-small-zh-v1.5",
            dimension=512,
        )
        adapter = LocalModelEmbeddingAdapter(config)
        adapter._model = object()
        adapter.state.mark_loaded()

        unloaded = adapter.unload()

        self.assertTrue(unloaded)
        self.assertIsNone(adapter._model)
        self.assertFalse(adapter.is_loaded())
        self.assertEqual(adapter.model_status(idle_ttl_seconds=300)["status"], "not_loaded")

    def test_local_model_adapter_unload_is_idempotent_when_not_loaded(self) -> None:
        config = KnowledgeEmbeddingConfig(
            enabled=True,
            provider="flag_embedding",
            model="BAAI/bge-small-zh-v1.5",
            local_path="data/models/embeddings/BAAI/bge-small-zh-v1.5",
            dimension=512,
        )
        adapter = LocalModelEmbeddingAdapter(config)

        unloaded = adapter.unload()

        self.assertFalse(unloaded)
        self.assertIsNone(adapter._model)
        self.assertEqual(adapter.model_status(idle_ttl_seconds=300)["status"], "not_loaded")


if __name__ == "__main__":
    unittest.main()
