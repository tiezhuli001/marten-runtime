import tempfile
import threading
import time
import unittest
from pathlib import Path

from marten_runtime.knowledge.config import KnowledgeEmbeddingConfig, embedding_config_hash, load_knowledge_config
from marten_runtime.knowledge.embeddings import EmbeddingResult, EmbeddingStatus, FakeEmbeddingAdapter
from marten_runtime.knowledge.models import KnowledgeSource
from marten_runtime.knowledge.service import KnowledgeService


class MissingEmbeddingAdapter:
    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(status=EmbeddingStatus.MISSING_MODEL, message="missing local model")

    def is_loaded(self) -> bool:
        return False

    def unload(self) -> bool:
        return False

    def model_status(self, *, idle_ttl_seconds: float | None) -> dict[str, object]:
        return {"status": "not_loaded"}


class PartiallyFailingEmbeddingAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        self.calls += 1
        if self.calls > 1:
            return EmbeddingResult(status=EmbeddingStatus.MISSING_MODEL, message="embedding failed after first batch")
        return EmbeddingResult(status=EmbeddingStatus.AVAILABLE, vectors=[[1.0] + [0.0] * 7 for _ in texts])

    def is_loaded(self) -> bool:
        return False

    def unload(self) -> bool:
        return False

    def model_status(self, *, idle_ttl_seconds: float | None) -> dict[str, object]:
        return {"status": "not_loaded"}


class BlockingEmbeddingAdapter:
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        self.calls += 1
        self.entered.set()
        if not self.release.wait(timeout=3):
            raise AssertionError("embedding release timed out")
        return EmbeddingResult(
            status=EmbeddingStatus.AVAILABLE,
            vectors=[[1.0] + [0.0] * (self.dimension - 1) for _ in texts],
        )

    def is_loaded(self) -> bool:
        return False

    def unload(self) -> bool:
        return False

    def model_status(self, *, idle_ttl_seconds: float | None) -> dict[str, object]:
        return {"status": "not_loaded"}


class KnowledgeServiceTests(unittest.TestCase):
    def _service(self):
        tmp = tempfile.TemporaryDirectory()
        config = load_knowledge_config.from_text(
            f'''
[knowledge]
db_path = "{Path(tmp.name) / 'knowledge.sqlite3'}"
repo_root = "{Path(tmp.name)}"
default_namespace = "personal"
model_idle_ttl_seconds = 300

[knowledge.chunking]
target_chars = 40
overlap_chars = 5
max_chars = 60
batch_size = 2

[knowledge.embedding]
provider = "fake"
model = "fake-embedding"
local_path = "{Path(tmp.name) / 'models' / 'embedding'}"
dimension = 8
allow_remote_download = false
use_fp16 = false

[knowledge.reranker]
provider = "fake"
model = "fake-reranker"
local_path = "{Path(tmp.name) / 'models' / 'reranker'}"
allow_remote_download = false
use_fp16 = false
top_n = 10

[knowledge.vector_store]
enabled = true
backend = "json_cosine"

[knowledge.search]
default_top_k = 5
candidate_pool = 20
fts_weight = 1.0
vector_weight = 1.0
metadata_weight = 0.2
reranker_weight = 2.0
'''
        ).knowledge
        service = KnowledgeService(config)
        service._tmp = tmp
        return service

    def test_ingest_text_search_get_delete_and_stats(self) -> None:
        service = self._service()

        ingest = service.ingest_text(
            namespace="fanqie",
            source={"title": "Book", "kind": "text", "uri": "local://book", "text": "# 第一章\n\n师父在山门出现", "metadata": {"novel_id": "n1"}},
        )
        self.assertTrue(ingest["ok"])
        self.assertEqual(ingest["namespace"], "fanqie")
        self.assertGreater(ingest["chunk_count"], 0)
        self.assertEqual(ingest["embedding_status"], "embedded")

        search = service.search(namespace="fanqie", query="师父", top_k=3, filters={"novel_id": "n1"})
        self.assertTrue(search["ok"])
        self.assertEqual(search["results"][0]["source_id"], ingest["source_id"])

        chunk = service.get_chunk(namespace="fanqie", chunk_id=search["results"][0]["chunk_id"])
        self.assertTrue(chunk["ok"])
        self.assertIn("师父", chunk["chunk"]["text"])

        stats = service.stats(namespace="fanqie")
        self.assertEqual(stats["source_count"], 1)
        self.assertGreater(stats["chunk_count"], 0)

        deleted = service.delete_source(namespace="fanqie", source_id=ingest["source_id"])
        self.assertTrue(deleted["ok"])
        self.assertEqual(service.search(namespace="fanqie", query="师父", top_k=3)["results"], [])

    def test_reingest_same_uri_version_replaces_existing_source(self) -> None:
        service = self._service()

        first = service.ingest_text(namespace="fanqie", source={"title": "Book", "kind": "text", "uri": "local://book", "version": "v1", "text": "旧文本"})
        second = service.ingest_text(namespace="fanqie", source={"title": "Book Updated", "kind": "text", "uri": "local://book", "version": "v1", "text": "新文本"})

        self.assertEqual(second["source_id"], first["source_id"])
        self.assertEqual(service.stats(namespace="fanqie")["source_count"], 1)
        search = service.search(namespace="fanqie", query="文本", top_k=5)
        self.assertEqual(len(search["results"]), 1)
        self.assertIn("新文本", search["results"][0]["text"])
        self.assertEqual(search["results"][0]["source_title"], "Book Updated")

    def test_ingest_file_returns_job_and_status_progress(self) -> None:
        service = self._service()
        tmp_file = Path(service._tmp.name) / "novel.txt"
        tmp_file.write_text("师父在山门出现\n" * 20, encoding="utf-8")

        result = service.ingest_file(namespace="fanqie", file_path=str(tmp_file), source={"title": "Novel", "kind": "txt", "uri": tmp_file.as_uri()})

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "queued")
        status = {}
        for _ in range(50):
            status = service.ingest_status(namespace="fanqie", job_id=result["job_id"])
            if status.get("status") in {"completed", "failed"}:
                break
            time.sleep(0.02)
        self.assertTrue(status["ok"])
        self.assertEqual(status["status"], "completed")
        self.assertGreaterEqual(status["percent"], 0.0)

    def test_ingest_file_resolves_relative_path_from_repo_root(self) -> None:
        service = self._service()
        relative_file = Path(service._tmp.name) / "fixtures" / "novel.txt"
        relative_file.parent.mkdir(parents=True)
        relative_file.write_text("师父在山门出现\n" * 20, encoding="utf-8")

        result = service.ingest_file(namespace="fanqie", file_path="fixtures/novel.txt", source={"title": "Novel", "kind": "txt"})

        final = {}
        for _ in range(50):
            final = service.ingest_status(namespace="fanqie", job_id=result["job_id"])
            if final.get("status") in {"completed", "failed"}:
                break
            time.sleep(0.02)
        self.assertEqual(final["status"], "completed")
        search = service.search(namespace="fanqie", query="师父", top_k=3)
        self.assertTrue(search["ok"])
        self.assertIn("师父", search["results"][0]["text"])

    def test_search_rejects_empty_query_without_loading_models(self) -> None:
        service = self._service()

        result = service.search(namespace="fanqie", query="   ", top_k=3)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "KNOWLEDGE_QUERY_REQUIRED")
        self.assertEqual(service.model_status()["embedding"]["status"], "not_loaded")

    def test_search_reports_query_embedding_unavailable_without_config_mismatch(self) -> None:
        service = self._service()
        service.embedding_adapter = MissingEmbeddingAdapter()

        result = service.search(namespace="fanqie", query="师父", top_k=3)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "KNOWLEDGE_QUERY_EMBEDDING_UNAVAILABLE")
        self.assertEqual(result["embedding_status"], "missing_model")
        self.assertIn("missing local model", result["message"])

    def test_parallel_searches_serialize_local_model_execution(self) -> None:
        service = self._service()
        adapter = BlockingEmbeddingAdapter(service.config.embedding.dimension)
        service.embedding_adapter = adapter
        results: list[dict[str, object]] = []
        first = threading.Thread(
            target=lambda: results.append(service.search(namespace="fanqie", query="甲木"))
        )
        second = threading.Thread(
            target=lambda: results.append(service.search(namespace="fanqie", query="乙木"))
        )

        first.start()
        self.assertTrue(adapter.entered.wait(timeout=2))
        second.start()
        time.sleep(0.05)

        self.assertEqual(adapter.calls, 1)
        adapter.release.set()
        first.join(timeout=3)
        second.join(timeout=3)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result["ok"] for result in results))

    def test_ingest_file_reports_embedding_progress_and_reads_gb18030(self) -> None:
        service = self._service()
        tmp_file = Path(service._tmp.name) / "novel_gbk.txt"
        tmp_file.write_bytes(("师父在山门出现\n" * 20).encode("gb18030"))

        result = service.ingest_file(namespace="fanqie", file_path=str(tmp_file), source={"title": "Novel", "kind": "txt", "uri": tmp_file.as_uri()})

        statuses = []
        final = {}
        for _ in range(50):
            final = service.ingest_status(namespace="fanqie", job_id=result["job_id"])
            statuses.append(str(final.get("status") or ""))
            if final.get("status") in {"completed", "failed"}:
                break
            time.sleep(0.02)
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["percent"], 100.0)
        self.assertGreater(final["chunks_total"], 0)
        self.assertEqual(final["chunks_embedded"], final["chunks_total"])
        self.assertIn("completed", statuses)

    def test_ingest_file_embedding_failure_preserves_progress_context(self) -> None:
        service = self._service()
        service.embedding_adapter = PartiallyFailingEmbeddingAdapter()
        tmp_file = Path(service._tmp.name) / "novel.txt"
        tmp_file.write_text(("甲木乙木丙火丁火戊土己土庚金辛金壬水癸水。\n" * 20), encoding="utf-8")

        result = service.ingest_file(namespace="fanqie", file_path=str(tmp_file), source={"title": "Novel", "kind": "txt", "uri": tmp_file.as_uri()})

        final = {}
        for _ in range(50):
            final = service.ingest_status(namespace="fanqie", job_id=result["job_id"])
            if final.get("status") in {"completed", "failed"}:
                break
            time.sleep(0.02)
        self.assertEqual(final["status"], "failed")
        self.assertGreater(final["chunks_total"], 0)
        self.assertGreater(final["chunks_embedded"], 0)
        self.assertLess(final["chunks_embedded"], final["chunks_total"])
        self.assertEqual(final["message"], "embedding_failed")
        self.assertIn("embedding_status=missing_model", final["error"])
        self.assertEqual(service.stats(namespace="fanqie")["source_count"], 0)
        self.assertEqual(service.stats(namespace="fanqie")["chunk_count"], 0)
        self.assertEqual(
            service.store.list_embeddings("fanqie", service.embedding_config_hash),
            [],
        )

    def test_cancel_during_embedding_does_not_publish_source_bundle(self) -> None:
        service = self._service()
        adapter = BlockingEmbeddingAdapter(service.config.embedding.dimension)
        service.embedding_adapter = adapter
        tmp_file = Path(service._tmp.name) / "cancelled.txt"
        tmp_file.write_text("甲木生于春季。\n" * 20, encoding="utf-8")

        result = service.ingest_file(
            namespace="fanqie",
            file_path=str(tmp_file),
            source={"title": "Cancelled", "kind": "txt", "uri": tmp_file.as_uri()},
        )
        self.assertTrue(adapter.entered.wait(timeout=2))
        cancelled = service.cancel_ingest(namespace="fanqie", job_id=result["job_id"])
        adapter.release.set()

        final = {}
        for _ in range(100):
            final = service.ingest_status(namespace="fanqie", job_id=result["job_id"])
            if final.get("status") == "cancelled":
                break
            time.sleep(0.02)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(final["status"], "cancelled")
        self.assertEqual(service.stats(namespace="fanqie")["source_count"], 0)
        self.assertEqual(service.stats(namespace="fanqie")["chunk_count"], 0)
        self.assertEqual(
            service.store.list_embeddings("fanqie", service.embedding_config_hash),
            [],
        )

    def test_delete_waits_for_ingest_publication_then_removes_complete_bundle(self) -> None:
        service = self._service()
        adapter = BlockingEmbeddingAdapter(service.config.embedding.dimension)
        service.embedding_adapter = adapter
        tmp_file = Path(service._tmp.name) / "delete-race.txt"
        tmp_file.write_text("甲木生于春季。\n" * 20, encoding="utf-8")
        source_id = "ksrc_delete_race"
        result = service.ingest_file(
            namespace="fanqie",
            file_path=str(tmp_file),
            source={
                "source_id": source_id,
                "title": "Delete race",
                "kind": "txt",
                "uri": tmp_file.as_uri(),
            },
        )
        self.assertTrue(adapter.entered.wait(timeout=2))
        deleted: list[dict[str, object]] = []
        delete_thread = threading.Thread(
            target=lambda: deleted.append(
                service.delete_source(namespace="fanqie", source_id=source_id)
            )
        )
        delete_thread.start()
        time.sleep(0.05)
        self.assertTrue(delete_thread.is_alive())
        adapter.release.set()
        delete_thread.join(timeout=3)

        final = {}
        for _ in range(100):
            final = service.ingest_status(namespace="fanqie", job_id=result["job_id"])
            if final.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)
        self.assertFalse(delete_thread.is_alive())
        self.assertEqual(final["status"], "completed")
        self.assertEqual(deleted[0]["deleted_source_id"], source_id)
        self.assertEqual(service.stats(namespace="fanqie")["source_count"], 0)
        self.assertEqual(service.stats(namespace="fanqie")["chunk_count"], 0)
        self.assertEqual(
            service.store.list_embeddings("fanqie", service.embedding_config_hash),
            [],
        )

    def test_reindex_uses_current_embedding_config(self) -> None:
        service = self._service()
        ingest = service.ingest_text(namespace="fanqie", source={"title": "Book", "kind": "text", "uri": "local://book", "text": "师父在山门出现"})

        reindex = service.reindex(namespace="fanqie")

        self.assertTrue(reindex["ok"])
        self.assertEqual(reindex["namespace"], "fanqie")
        self.assertEqual(reindex["chunk_count"], ingest["chunk_count"])
        self.assertEqual(reindex["embedding_config_hash"], service.embedding_config_hash)

    def test_namespace_embedding_profile_change_replaces_vectors_atomically(self) -> None:
        service = self._service()
        service.ingest_text(
            namespace="fanqie",
            source={"title": "Book", "kind": "text", "uri": "local://book", "text": "师父在山门出现"},
        )
        alternate = KnowledgeEmbeddingConfig(
            provider="fake",
            model="fake-embedding-768",
            local_path="models/fake-embedding-768",
            dimension=768,
        )
        service.embedding_profiles["alternate"] = alternate
        service.embedding_profile_hashes["alternate"] = embedding_config_hash(alternate)
        service._embedding_adapters["alternate"] = FakeEmbeddingAdapter(
            dimension=768,
            model_id=alternate.model,
        )

        result = service.reindex(namespace="fanqie", embedding_profile_id="alternate")

        self.assertTrue(result["ok"])
        self.assertEqual(service.store.get_namespace_embedding_profile_id("fanqie"), "alternate")
        self.assertEqual(service.store.list_embeddings("fanqie", service.embedding_config_hash), [])
        records = service.store.list_embeddings("fanqie", service.embedding_profile_hashes["alternate"])
        self.assertTrue(records)
        self.assertEqual({record.dimension for record in records}, {768})

    def test_approve_source_rejects_missing_evidence_kind(self) -> None:
        service = self._service()
        ingest = service.ingest_text(
            namespace="bazi-theory-sandbox",
            source={
                "title": "Unclassified",
                "kind": "text",
                "uri": "local://unclassified",
                "text": "月令为先。",
            },
        )

        result = service.approve_source(
            draft_namespace="bazi-theory-sandbox",
            source_id=str(ingest["source_id"]),
            target_namespace="bazi-theory",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "KNOWLEDGE_APPROVAL_EVIDENCE_KIND_REQUIRED")
        self.assertIsNotNone(
            service.store.get_source("bazi-theory-sandbox", str(ingest["source_id"]))
        )
        self.assertIsNone(service.store.get_source("bazi-theory", str(ingest["source_id"])))

    def test_failed_embedding_profile_change_preserves_current_index(self) -> None:
        service = self._service()
        service.ingest_text(
            namespace="fanqie",
            source={"title": "Book", "kind": "text", "uri": "local://book", "text": "师父在山门出现"},
        )
        original = service.store.list_embeddings("fanqie", service.embedding_config_hash)
        alternate = KnowledgeEmbeddingConfig(
            provider="fake",
            model="missing-embedding",
            local_path="models/missing",
            dimension=768,
        )
        service.embedding_profiles["missing"] = alternate
        service.embedding_profile_hashes["missing"] = embedding_config_hash(alternate)
        service._embedding_adapters["missing"] = MissingEmbeddingAdapter()

        result = service.reindex(namespace="fanqie", embedding_profile_id="missing")

        self.assertFalse(result["ok"])
        self.assertEqual(service.store.get_namespace_embedding_profile_id("fanqie"), "default")
        self.assertEqual(
            [record.chunk_id for record in service.store.list_embeddings("fanqie", service.embedding_config_hash)],
            [record.chunk_id for record in original],
        )
        self.assertEqual(service.store.list_embeddings("fanqie", service.embedding_profile_hashes["missing"]), [])

    def test_reindex_reports_missing_source_id(self) -> None:
        service = self._service()

        reindex = service.reindex(namespace="fanqie", source_id="missing_source")

        self.assertFalse(reindex["ok"])
        self.assertEqual(reindex["error_code"], "KNOWLEDGE_SOURCE_NOT_FOUND")
        self.assertEqual(reindex["source_id"], "missing_source")

    def test_reindex_reports_source_without_chunks(self) -> None:
        service = self._service()
        source = KnowledgeSource.new(namespace="fanqie", title="Book", kind="text", uri="local://book")
        service.store.upsert_source(source)

        result = service.reindex(namespace="fanqie", source_id=source.source_id)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "KNOWLEDGE_SOURCE_HAS_NO_CHUNKS")
        self.assertEqual(result["source_id"], source.source_id)

    def test_reindex_reports_embedding_unavailable(self) -> None:
        service = self._service()
        service.ingest_text(namespace="fanqie", source={"title": "Book", "kind": "text", "uri": "local://book", "text": "师父在山门出现"})
        service.embedding_adapter = MissingEmbeddingAdapter()

        result = service.reindex(namespace="fanqie")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "KNOWLEDGE_REINDEX_EMBEDDING_UNAVAILABLE")
        self.assertEqual(result["embedding_status"], "missing_model")
        self.assertGreater(result["chunk_count"], 0)

    def test_model_status_and_unload_models_report_loaded_state(self) -> None:
        service = self._service()

        initial = service.model_status()
        self.assertEqual(initial["embedding"]["status"], "not_loaded")
        self.assertEqual(initial["reranker"]["status"], "not_loaded")

        service.ingest_text(namespace="fanqie", source={"title": "Book", "kind": "text", "uri": "local://book", "text": "师父在山门出现"})
        loaded = service.model_status()
        self.assertEqual(loaded["embedding"]["status"], "loaded")
        self.assertEqual(loaded["reranker"]["status"], "not_loaded")

        search = service.search(namespace="fanqie", query="师父", top_k=3)
        self.assertTrue(search["ok"])
        self.assertEqual(service.model_status()["reranker"]["status"], "loaded")

        unloaded = service.unload_models()
        self.assertTrue(unloaded["embedding_unloaded"])
        self.assertTrue(unloaded["reranker_unloaded"])
        self.assertEqual(unloaded["embedding"]["status"], "not_loaded")
        self.assertEqual(unloaded["reranker"]["status"], "not_loaded")

    def test_prewarm_loads_embedding_and_reranker_and_marks_service_ready(self) -> None:
        service = self._service()

        result = service.prewarm_models()

        self.assertTrue(result["ok"])
        self.assertTrue(service.ready)
        status = service.model_status()
        self.assertEqual(status["embedding"]["status"], "loaded")
        self.assertEqual(status["reranker"]["status"], "loaded")
        self.assertTrue(status["prewarm"]["ready"])

    def test_idle_ttl_unloads_models_on_tool_boundary(self) -> None:
        service = self._service()
        service.config.model_idle_ttl_seconds = 0.001
        service.ingest_text(namespace="fanqie", source={"title": "Book", "kind": "text", "uri": "local://book", "text": "师父在山门出现"})

        time.sleep(0.01)
        status = service.model_status()

        self.assertEqual(status["embedding"]["status"], "not_loaded")

    def test_cancel_ingest_changes_queued_job_status(self) -> None:
        service = self._service()
        job_id = service.jobs.create_job(namespace="fanqie", source_title="Manual")

        cancelled = service.cancel_ingest(namespace="fanqie", job_id=job_id)

        self.assertTrue(cancelled["ok"])
        self.assertEqual(cancelled["status"], "cancelled")

    def test_file_ingest_terminal_state_cleans_owned_staging(self) -> None:
        service = self._service()
        staged = Path(service._tmp.name) / "data" / "knowledge" / "uploads" / "upload-1" / "source.txt"
        staged.parent.mkdir(parents=True)
        staged.write_text("师父在山门出现", encoding="utf-8")

        result = service.ingest_file(
            namespace="fanqie",
            file_path=str(staged),
            staged_file_path="upload-1/source.txt",
            source={"title": "Novel", "kind": "txt", "uri": "upload://fanqie/upload-1/source.txt"},
        )

        final = {}
        for _ in range(50):
            final = service.ingest_status(namespace="fanqie", job_id=result["job_id"])
            if final.get("status") in {"completed", "failed"}:
                break
            time.sleep(0.02)
        self.assertEqual(final["status"], "completed")
        self.assertFalse(staged.parent.exists())


if __name__ == "__main__":
    unittest.main()
