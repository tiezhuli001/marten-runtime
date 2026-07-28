from __future__ import annotations

import shutil
import time
from pathlib import Path, PurePosixPath
from uuid import uuid4

from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore


class KnowledgeIngestJobStore:
    _TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

    def __init__(self, store: SQLiteKnowledgeStore, *, staging_root: str | Path) -> None:
        self.store = store
        self.staging_root = Path(staging_root)
        self.staging_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.staging_root.chmod(0o700)
        self.cleanup_failures: list[dict[str, str]] = []

    def create_job(self, *, namespace: str, source_title: str, staged_file_path: str = "") -> str:
        if staged_file_path:
            self._owned_directory(staged_file_path)
        job_id = f"kjob_{uuid4().hex[:12]}"
        self.store.upsert_ingest_job(
            namespace=namespace,
            job_id=job_id,
            source_title=source_title,
            status="queued",
            message="queued",
            staged_file_path=staged_file_path,
        )
        return job_id

    def update(
        self,
        *,
        namespace: str,
        job_id: str,
        source_title: str,
        status: str,
        chunks_total: int = 0,
        chunks_embedded: int = 0,
        message: str = "",
        error: str = "",
        error_code: str = "",
        retryable: bool = False,
    ) -> bool:
        percent = 0.0 if chunks_total <= 0 else round((chunks_embedded / chunks_total) * 100.0, 1)
        if status == "completed":
            percent = 100.0
        updated = self.store.update_ingest_job(
            namespace=namespace,
            job_id=job_id,
            source_title=source_title,
            status=status,
            chunks_total=chunks_total,
            chunks_embedded=chunks_embedded,
            percent=percent,
            message=message,
            error=error,
            error_code=error_code,
            retryable=retryable,
        )
        current = self.get(namespace=namespace, job_id=job_id)
        if current and str(current.get("status") or "") in self._TERMINAL_STATUSES:
            self._cleanup_job_staging(current)
        return updated

    def get(self, *, namespace: str, job_id: str) -> dict[str, object] | None:
        return self.store.get_ingest_job(namespace, job_id)

    def validate_staged_file(self, *, staged_file_path: str, file_path: str | Path) -> None:
        relative = PurePosixPath(staged_file_path)
        self._owned_directory(staged_file_path)
        expected = (self.staging_root.resolve() / relative).resolve()
        actual = Path(file_path).resolve()
        if actual != expected:
            raise ValueError("file_path does not match staged_file_path")

    def is_cancelled(self, *, namespace: str, job_id: str) -> bool:
        job = self.get(namespace=namespace, job_id=job_id)
        return str((job or {}).get("status") or "") == "cancelled"

    def cancel(self, *, namespace: str, job_id: str) -> dict[str, object]:
        job = self.get(namespace=namespace, job_id=job_id)
        if job is None:
            return {"ok": False, "error_code": "KNOWLEDGE_JOB_NOT_FOUND", "job_id": job_id}
        self.update(
            namespace=namespace,
            job_id=job_id,
            source_title=str(job.get("source_title") or ""),
            status="cancelled",
            chunks_total=int(job.get("chunks_total") or 0),
            chunks_embedded=int(job.get("chunks_embedded") or 0),
            message="cancelled",
        )
        updated = self.get(namespace=namespace, job_id=job_id) or {}
        return {"ok": True, **updated}

    def cleanup_terminal(self, *, namespace: str, job_id: str) -> bool:
        job = self.get(namespace=namespace, job_id=job_id)
        if job is None or str(job.get("status") or "") not in self._TERMINAL_STATUSES:
            return False
        return self._cleanup_job_staging(job)

    def reconcile_startup(self, *, orphan_max_age_seconds: float = 24 * 60 * 60) -> dict[str, object]:
        interrupted_count = self.store.recover_interrupted_ingest_jobs()
        jobs = self.store.list_ingest_jobs()
        owned_directories: set[str] = set()
        terminal_cleanup_count = 0
        for job in jobs:
            staged_file_path = str(job.get("staged_file_path") or "")
            if not staged_file_path:
                continue
            try:
                owned_directories.add(self._owned_directory(staged_file_path).name)
            except ValueError as exc:
                self._record_cleanup_failure(staged_file_path, exc)
                continue
            if str(job.get("status") or "") in self._TERMINAL_STATUSES:
                if self._cleanup_job_staging(job):
                    terminal_cleanup_count += 1
        orphan_count = self._cleanup_expired_orphans(
            owned_directories=owned_directories,
            max_age_seconds=orphan_max_age_seconds,
        )
        return {
            "interrupted_job_count": interrupted_count,
            "terminal_directories_removed": terminal_cleanup_count,
            "orphan_directories_removed": orphan_count,
            "cleanup_failures": list(self.cleanup_failures),
        }

    def _cleanup_job_staging(self, job: dict[str, object]) -> bool:
        staged_file_path = str(job.get("staged_file_path") or "")
        if not staged_file_path:
            return False
        try:
            directory = self._owned_directory(staged_file_path)
            if not directory.exists():
                return False
            shutil.rmtree(directory)
            return True
        except (OSError, ValueError) as exc:
            self._record_cleanup_failure(staged_file_path, exc)
            return False

    def _cleanup_expired_orphans(self, *, owned_directories: set[str], max_age_seconds: float) -> int:
        removed = 0
        cutoff = time.time() - max_age_seconds
        try:
            children = list(self.staging_root.iterdir())
        except OSError as exc:
            self._record_cleanup_failure("", exc)
            return 0
        for child in children:
            if child.name in owned_directories or not child.is_dir() or child.is_symlink():
                continue
            try:
                if child.stat().st_mtime > cutoff:
                    continue
                shutil.rmtree(child)
                removed += 1
            except OSError as exc:
                self._record_cleanup_failure(child.name, exc)
        return removed

    def _owned_directory(self, staged_file_path: str) -> Path:
        path = PurePosixPath(staged_file_path)
        if path.is_absolute() or len(path.parts) != 2 or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("staged_file_path must identify a file inside one upload directory")
        root = self.staging_root.resolve()
        directory = (root / path.parts[0]).resolve()
        if directory.parent != root:
            raise ValueError("staged_file_path escapes the staging root")
        return directory

    def _record_cleanup_failure(self, staged_file_path: str, exc: Exception) -> None:
        detail = getattr(exc, "strerror", None) or str(exc)
        self.cleanup_failures.append(
            {
                "staged_file_path": staged_file_path,
                "error": f"{type(exc).__name__}: {detail}",
            }
        )
        del self.cleanup_failures[:-50]
