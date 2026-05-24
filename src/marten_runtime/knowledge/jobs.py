from __future__ import annotations

from uuid import uuid4

from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore


class KnowledgeIngestJobStore:
    def __init__(self, store: SQLiteKnowledgeStore) -> None:
        self.store = store

    def create_job(self, *, namespace: str, source_title: str) -> str:
        job_id = f"kjob_{uuid4().hex[:12]}"
        self.store.upsert_ingest_job(
            namespace=namespace,
            job_id=job_id,
            source_title=source_title,
            status="queued",
            message="queued",
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
    ) -> None:
        percent = 0.0 if chunks_total <= 0 else round((chunks_embedded / chunks_total) * 100.0, 1)
        if status == "completed":
            percent = 100.0
        self.store.upsert_ingest_job(
            namespace=namespace,
            job_id=job_id,
            source_title=source_title,
            status=status,
            chunks_total=chunks_total,
            chunks_embedded=chunks_embedded,
            percent=percent,
            message=message,
            error=error,
        )

    def get(self, *, namespace: str, job_id: str) -> dict[str, object] | None:
        return self.store.get_ingest_job(namespace, job_id)

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
