import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from marten_runtime.knowledge.config import (
    embedding_config_hash,
    load_knowledge_config,
    resolve_knowledge_runtime_paths,
)


class KnowledgeConfigTests(unittest.TestCase):
    def test_loader_reads_knowledge_example_when_local_config_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            example = base / "knowledge.example.toml"
            example.write_text(
                """
                [knowledge]
                db_path = "data/knowledge/knowledge.sqlite3"
                default_namespace = "personal"
                model_idle_ttl_seconds = 300

                [knowledge.chunking]
                target_chars = 1000
                overlap_chars = 150
                max_chars = 1600
                batch_size = 64

                [knowledge.embedding]
                enabled = true
                provider = "flag_embedding"
                model = "BAAI/bge-small-zh-v1.5"
                local_path = "data/models/embeddings/BAAI/bge-small-zh-v1.5"
                dimension = 512
                allow_remote_download = false

                [knowledge.reranker]
                enabled = true
                provider = "flag_embedding"
                model = "BAAI/bge-reranker-base"
                local_path = "data/models/rerankers/BAAI/bge-reranker-base"
                allow_remote_download = false
                use_fp16 = false
                top_n = 10

                [knowledge.vector_store]
                enabled = true
                backend = "sqlite_vec"

                [knowledge.search]
                default_top_k = 5
                candidate_pool = 30
                fts_weight = 0.35
                vector_weight = 0.55
                metadata_weight = 0.10
                reranker_weight = 0.70
                """,
                encoding="utf-8",
            )

            config = load_knowledge_config(str(base / "knowledge.toml"))

            self.assertEqual(config.knowledge.db_path, "data/knowledge/knowledge.sqlite3")
            self.assertEqual(config.knowledge.default_namespace, "personal")
            self.assertEqual(config.knowledge.model_idle_ttl_seconds, 300)
            self.assertEqual(config.knowledge.chunking.target_chars, 1000)
            self.assertEqual(config.knowledge.chunking.overlap_chars, 150)
            self.assertEqual(config.knowledge.chunking.max_chars, 1600)
            self.assertEqual(config.knowledge.chunking.batch_size, 64)
            self.assertEqual(config.knowledge.embedding.model, "BAAI/bge-small-zh-v1.5")
            self.assertEqual(config.knowledge.embedding.dimension, 512)
            self.assertFalse(config.knowledge.embedding.allow_remote_download)
            self.assertEqual(config.knowledge.reranker.model, "BAAI/bge-reranker-base")
            self.assertEqual(config.knowledge.reranker.top_n, 10)
            self.assertEqual(config.knowledge.vector_store.backend, "sqlite_vec")
            self.assertEqual(config.knowledge.search.default_top_k, 5)

    def test_local_config_overrides_example(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "knowledge.example.toml").write_text(_valid_config(model="BAAI/bge-small-zh-v1.5"), encoding="utf-8")
            local = base / "knowledge.toml"
            local.write_text(_valid_config(model="custom/model", dimension=768), encoding="utf-8")

            config = load_knowledge_config(str(local))

            self.assertEqual(config.knowledge.embedding.model, "custom/model")
            self.assertEqual(config.knowledge.embedding.dimension, 768)

    def test_remote_download_defaults_to_false_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "knowledge.toml"
            path.write_text(_valid_config_without_remote_download(), encoding="utf-8")

            config = load_knowledge_config(str(path))

            self.assertFalse(config.knowledge.embedding.allow_remote_download)
            self.assertFalse(config.knowledge.reranker.allow_remote_download)

    def test_loader_rejects_missing_required_model_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "knowledge.toml"
            path.write_text(
                """
                [knowledge]
                db_path = "data/knowledge/knowledge.sqlite3"
                default_namespace = "personal"
                model_idle_ttl_seconds = 300

                [knowledge.chunking]
                target_chars = 1000
                overlap_chars = 150
                max_chars = 1600
                batch_size = 64

                [knowledge.embedding]
                enabled = true
                provider = "flag_embedding"
                dimension = 512

                [knowledge.reranker]
                enabled = true
                provider = "flag_embedding"
                model = "BAAI/bge-reranker-base"
                local_path = "data/models/rerankers/BAAI/bge-reranker-base"
                top_n = 10

                [knowledge.vector_store]
                enabled = true
                backend = "sqlite_vec"

                [knowledge.search]
                default_top_k = 5
                candidate_pool = 30
                fts_weight = 0.35
                vector_weight = 0.55
                metadata_weight = 0.10
                reranker_weight = 0.70
                """,
                encoding="utf-8",
            )

            with self.assertRaises(ValidationError):
                load_knowledge_config(str(path))

    def test_rejects_invalid_chunking_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "knowledge.toml"
            path.write_text(_valid_config(target_chars=100, overlap_chars=100, max_chars=90), encoding="utf-8")

            with self.assertRaises(ValidationError):
                load_knowledge_config(str(path))

    def test_embedding_config_hash_changes_when_vector_space_fields_change(self) -> None:
        base = load_knowledge_config.from_text(_valid_config()).knowledge.embedding
        changed_model = load_knowledge_config.from_text(_valid_config(model="BAAI/bge-base-zh-v1.5")).knowledge.embedding
        changed_dimension = load_knowledge_config.from_text(_valid_config(dimension=768)).knowledge.embedding
        changed_path = load_knowledge_config.from_text(_valid_config(local_path="data/models/other")).knowledge.embedding
        changed_precision = base.model_copy(update={"use_fp16": True})

        digest = embedding_config_hash(base)

        self.assertNotEqual(digest, embedding_config_hash(changed_model))
        self.assertNotEqual(digest, embedding_config_hash(changed_dimension))
        self.assertNotEqual(digest, embedding_config_hash(changed_path))
        self.assertNotEqual(digest, embedding_config_hash(changed_precision))

    def test_named_embedding_profiles_are_loaded_with_default_profile(self) -> None:
        text = _valid_config() + """
        [knowledge.embedding_profiles.large]
        enabled = true
        provider = "fake"
        model = "fake-large"
        local_path = "data/models/fake-large"
        dimension = 768
        allow_remote_download = false
        use_fp16 = false
        """

        config = load_knowledge_config.from_text(text).knowledge

        profiles = config.resolved_embedding_profiles()
        self.assertEqual(set(profiles), {"default", "large"})
        self.assertEqual(profiles["large"].dimension, 768)

    def test_runtime_path_resolution_covers_all_model_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            text = _valid_config() + """
            [knowledge.embedding_profiles.large]
            enabled = true
            provider = "fake"
            model = "fake-large"
            local_path = "data/models/fake-large"
            dimension = 768
            allow_remote_download = false
            use_fp16 = false
            """
            config = load_knowledge_config.from_text(text).knowledge

            resolved = resolve_knowledge_runtime_paths(config, repo_root=root)

            self.assertEqual(resolved.repo_root, str(root))
            self.assertEqual(resolved.db_path, str(root / config.db_path))
            self.assertEqual(resolved.embedding.local_path, str(root / config.embedding.local_path))
            self.assertEqual(
                resolved.embedding_profiles["large"].local_path,
                str(root / "data/models/fake-large"),
            )
            self.assertEqual(resolved.reranker.local_path, str(root / config.reranker.local_path))


def _valid_config(
    *,
    model: str = "BAAI/bge-small-zh-v1.5",
    local_path: str = "data/models/embeddings/BAAI/bge-small-zh-v1.5",
    dimension: int = 512,
    target_chars: int = 1000,
    overlap_chars: int = 150,
    max_chars: int = 1600,
) -> str:
    return f"""
    [knowledge]
    db_path = "data/knowledge/knowledge.sqlite3"
    default_namespace = "personal"
    model_idle_ttl_seconds = 300

    [knowledge.chunking]
    target_chars = {target_chars}
    overlap_chars = {overlap_chars}
    max_chars = {max_chars}
    batch_size = 64

    [knowledge.embedding]
    enabled = true
    provider = "flag_embedding"
    model = "{model}"
    local_path = "{local_path}"
    dimension = {dimension}
    allow_remote_download = false
    use_fp16 = false

    [knowledge.reranker]
    enabled = true
    provider = "flag_embedding"
    model = "BAAI/bge-reranker-base"
    local_path = "data/models/rerankers/BAAI/bge-reranker-base"
    allow_remote_download = false
    use_fp16 = false
    top_n = 10

    [knowledge.vector_store]
    enabled = true
    backend = "sqlite_vec"

    [knowledge.search]
    default_top_k = 5
    candidate_pool = 30
    fts_weight = 0.35
    vector_weight = 0.55
    metadata_weight = 0.10
    reranker_weight = 0.70
    """


def _valid_config_without_remote_download() -> str:
    return _valid_config().replace("    allow_remote_download = false\n", "")
