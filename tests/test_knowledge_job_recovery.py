import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from marten_runtime.knowledge.config import load_knowledge_config
from marten_runtime.knowledge.jobs import KnowledgeIngestJobStore
from marten_runtime.knowledge.service import KnowledgeService
from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore


class KnowledgeJobRecoveryTests(unittest.TestCase):
    def _config(self, root: Path):
        return load_knowledge_config.from_text(
            f'''
[knowledge]
db_path = "{root / 'knowledge.sqlite3'}"
repo_root = "{root}"
default_namespace = "personal"

[knowledge.chunking]
target_chars = 40
overlap_chars = 5
max_chars = 60
batch_size = 2

[knowledge.embedding]
provider = "fake"
model = "fake-embedding"
local_path = "{root / 'models' / 'embedding'}"
dimension = 8
allow_remote_download = false
use_fp16 = false

[knowledge.reranker]
provider = "fake"
model = "fake-reranker"
local_path = "{root / 'models' / 'reranker'}"
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

    def test_old_job_schema_migrates_additively_and_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "knowledge.sqlite3"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE knowledge_ingest_jobs (
                      namespace TEXT NOT NULL,
                      job_id TEXT NOT NULL,
                      source_title TEXT NOT NULL DEFAULT '',
                      status TEXT NOT NULL,
                      chunks_total INTEGER NOT NULL DEFAULT 0,
                      chunks_embedded INTEGER NOT NULL DEFAULT 0,
                      percent REAL NOT NULL DEFAULT 0.0,
                      message TEXT NOT NULL DEFAULT '',
                      error TEXT NOT NULL DEFAULT '',
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      PRIMARY KEY(namespace, job_id)
                    );
                    INSERT INTO knowledge_ingest_jobs VALUES (
                      'bazi', 'legacy', 'Legacy', 'failed', 2, 1, 50.0,
                      'failed', 'legacy error', '2026-01-01T00:00:00+00:00',
                      '2026-01-01T00:01:00+00:00'
                    );
                    """
                )

            store = SQLiteKnowledgeStore(db_path)
            SQLiteKnowledgeStore(db_path)
            job = store.get_ingest_job("bazi", "legacy")

            self.assertEqual(job["error"], "legacy error")
            self.assertEqual(job["error_code"], "")
            self.assertFalse(job["retryable"])
            self.assertEqual(job["staged_file_path"], "")
            with sqlite3.connect(db_path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(knowledge_ingest_jobs)")}
                indexes = {row[1] for row in conn.execute("PRAGMA index_list(knowledge_ingest_jobs)")}
            self.assertTrue({"error_code", "retryable", "staged_file_path"}.issubset(columns))
            self.assertIn("idx_knowledge_ingest_jobs_status_updated", indexes)

    def test_startup_recovers_active_jobs_and_cleans_all_owned_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SQLiteKnowledgeStore(root / "knowledge.sqlite3")
            staging_root = root / "data" / "knowledge" / "uploads"
            active = ("queued", "reading", "chunking", "embedding")
            terminal = ("completed", "failed", "cancelled")
            for status in (*active, *terminal):
                relative = f"upload-{status}/source.txt"
                staged = staging_root / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_text(status, encoding="utf-8")
                store.upsert_ingest_job(
                    namespace="bazi",
                    job_id=f"job-{status}",
                    source_title=status,
                    status=status,
                    staged_file_path=relative,
                    error_code="ORIGINAL" if status == "failed" else "",
                    retryable=status == "failed",
                )

            service = KnowledgeService(self._config(root))

            for status in active:
                job = service.jobs.get(namespace="bazi", job_id=f"job-{status}")
                self.assertEqual(job["status"], "failed")
                self.assertEqual(job["error_code"], "KNOWLEDGE_JOB_INTERRUPTED")
                self.assertTrue(job["retryable"])
                self.assertIn("restart", job["message"])
            for status in terminal:
                job = service.jobs.get(namespace="bazi", job_id=f"job-{status}")
                self.assertEqual(job["status"], status)
            self.assertEqual(list(staging_root.glob("upload-*")), [])
            self.assertEqual(service.job_recovery_status["interrupted_job_count"], 4)
            self.assertEqual(service.job_recovery_status["cleanup_failures"], [])

            second = KnowledgeService(self._config(root))
            self.assertEqual(second.job_recovery_status["interrupted_job_count"], 0)

    def test_startup_cleans_only_expired_unowned_staging_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging_root = root / "data" / "knowledge" / "uploads"
            old_orphan = staging_root / "old-orphan"
            fresh_orphan = staging_root / "fresh-orphan"
            owned = staging_root / "owned"
            for directory in (old_orphan, fresh_orphan, owned):
                directory.mkdir(parents=True)
                (directory / "source.txt").write_text("text", encoding="utf-8")
            old = time.time() - (25 * 60 * 60)
            os.utime(old_orphan, (old, old))
            os.utime(owned, (old, old))
            store = SQLiteKnowledgeStore(root / "knowledge.sqlite3")
            store.upsert_ingest_job(
                namespace="bazi",
                job_id="owned-active",
                source_title="Owned",
                status="queued",
                staged_file_path="owned/source.txt",
            )

            service = KnowledgeService(self._config(root))

            self.assertFalse(old_orphan.exists())
            self.assertTrue(fresh_orphan.exists())
            self.assertFalse(owned.exists())
            self.assertEqual(service.job_recovery_status["orphan_directories_removed"], 1)

    def test_cleanup_failure_is_diagnostic_and_preserves_terminal_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SQLiteKnowledgeStore(root / "knowledge.sqlite3")
            staged = root / "data" / "knowledge" / "uploads" / "owned" / "source.txt"
            staged.parent.mkdir(parents=True)
            staged.write_text("text", encoding="utf-8")
            store.upsert_ingest_job(
                namespace="bazi",
                job_id="failed-job",
                source_title="Failed",
                status="failed",
                error="original detail",
                error_code="ORIGINAL_ERROR",
                retryable=True,
                staged_file_path="owned/source.txt",
            )

            with patch("marten_runtime.knowledge.jobs.shutil.rmtree", side_effect=OSError("permission denied")):
                service = KnowledgeService(self._config(root))

            job = service.jobs.get(namespace="bazi", job_id="failed-job")
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error_code"], "ORIGINAL_ERROR")
            self.assertEqual(job["error"], "original detail")
            self.assertEqual(len(service.job_recovery_status["cleanup_failures"]), 1)
            self.assertNotIn(str(root), str(service.job_recovery_status["cleanup_failures"]))

    def test_terminal_transition_is_atomic_and_retry_creates_new_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = KnowledgeIngestJobStore(
                SQLiteKnowledgeStore(root / "knowledge.sqlite3"),
                staging_root=root / "uploads",
            )
            old_job_id = jobs.create_job(namespace="bazi", source_title="Original")
            barrier = threading.Barrier(3)

            def finish(status: str) -> None:
                barrier.wait()
                jobs.update(
                    namespace="bazi",
                    job_id=old_job_id,
                    source_title="Original",
                    status=status,
                    message=status,
                )

            threads = [threading.Thread(target=finish, args=(status,)) for status in ("completed", "cancelled")]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()

            old_job = jobs.get(namespace="bazi", job_id=old_job_id)
            self.assertIn(old_job["status"], {"completed", "cancelled"})
            jobs.update(
                namespace="bazi",
                job_id=old_job_id,
                source_title="Original",
                status="failed",
                message="late failure",
                error_code="LATE_FAILURE",
            )
            self.assertEqual(jobs.get(namespace="bazi", job_id=old_job_id)["status"], old_job["status"])

            retry_job_id = jobs.create_job(namespace="bazi", source_title="Retry")
            self.assertNotEqual(retry_job_id, old_job_id)
            self.assertEqual(jobs.get(namespace="bazi", job_id=old_job_id)["status"], old_job["status"])

    def test_staged_file_validation_rejects_escape_and_path_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = KnowledgeIngestJobStore(
                SQLiteKnowledgeStore(root / "knowledge.sqlite3"),
                staging_root=root / "uploads",
            )
            staged = root / "uploads" / "upload-1" / "source.txt"
            staged.parent.mkdir(parents=True)
            staged.write_text("text", encoding="utf-8")

            jobs.validate_staged_file(staged_file_path="upload-1/source.txt", file_path=staged)
            with self.assertRaises(ValueError):
                jobs.create_job(
                    namespace="bazi",
                    source_title="Escape",
                    staged_file_path="../outside/source.txt",
                )
            with self.assertRaises(ValueError):
                jobs.validate_staged_file(
                    staged_file_path="upload-1/source.txt",
                    file_path=root / "outside.txt",
                )


if __name__ == "__main__":
    unittest.main()
