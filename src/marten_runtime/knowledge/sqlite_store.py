from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from marten_runtime.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDeleteResult,
    KnowledgeEmbeddingRecord,
    KnowledgeIngestJob,
    KnowledgeSource,
    utc_now_iso,
)
from marten_runtime.knowledge.vector_models import VectorQueryResult, VectorResultItem, VectorStatus


class SQLiteKnowledgeStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            import sqlite_vec  # type: ignore[import-not-found]

            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
        except Exception:
            pass
        return conn

    def sqlite_vec_available(self) -> bool:
        with self._connect() as conn:
            try:
                conn.execute("SELECT vec_version()").fetchone()
                return True
            except sqlite3.Error:
                return False

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                  namespace TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  title TEXT NOT NULL,
                  uri TEXT NOT NULL,
                  version TEXT NOT NULL DEFAULT '',
                  metadata_json TEXT NOT NULL DEFAULT '{}',
                  status TEXT NOT NULL DEFAULT 'active',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(namespace, source_id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                  namespace TEXT NOT NULL,
                  chunk_id TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  heading TEXT NOT NULL DEFAULT '',
                  ordinal INTEGER NOT NULL,
                  text TEXT NOT NULL,
                  token_estimate INTEGER NOT NULL DEFAULT 0,
                  metadata_json TEXT NOT NULL DEFAULT '{}',
                  status TEXT NOT NULL DEFAULT 'active',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(namespace, chunk_id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_namespaces (
                  namespace TEXT PRIMARY KEY,
                  embedding_config_hash TEXT NOT NULL,
                  embedding_profile_id TEXT NOT NULL DEFAULT 'default',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_embeddings (
                  namespace TEXT NOT NULL,
                  chunk_id TEXT NOT NULL,
                  model_id TEXT NOT NULL,
                  dimension INTEGER NOT NULL,
                  embedding_config_hash TEXT NOT NULL,
                  vector_json TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'active',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(namespace, chunk_id, embedding_config_hash)
                );
                CREATE TABLE IF NOT EXISTS knowledge_embedding_vec_map (
                  vec_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                  namespace TEXT NOT NULL,
                  chunk_id TEXT NOT NULL,
                  embedding_config_hash TEXT NOT NULL,
                  dimension INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(namespace, chunk_id, embedding_config_hash, dimension)
                );
                CREATE TABLE IF NOT EXISTS knowledge_search_runs (
                  run_id TEXT PRIMARY KEY,
                  namespace TEXT NOT NULL,
                  query TEXT NOT NULL,
                  filters_json TEXT NOT NULL DEFAULT '{}',
                  result_count INTEGER NOT NULL DEFAULT 0,
                  retrieval_mode TEXT NOT NULL DEFAULT '',
                  degraded_reason TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_ingest_jobs (
                  namespace TEXT NOT NULL,
                  job_id TEXT NOT NULL,
                  source_title TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL,
                  chunks_total INTEGER NOT NULL DEFAULT 0,
                  chunks_embedded INTEGER NOT NULL DEFAULT 0,
                  percent REAL NOT NULL DEFAULT 0.0,
                  message TEXT NOT NULL DEFAULT '',
                  error TEXT NOT NULL DEFAULT '',
                  error_code TEXT NOT NULL DEFAULT '',
                  retryable INTEGER NOT NULL DEFAULT 0,
                  staged_file_path TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(namespace, job_id)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
                  namespace UNINDEXED,
                  chunk_id UNINDEXED,
                  title,
                  heading,
                  text,
                  tokenize='trigram'
                );
                """
            )
            _ensure_column(conn, "knowledge_embedding_vec_map", "dimension", "INTEGER NOT NULL DEFAULT 0")
            _ensure_column(conn, "knowledge_namespaces", "embedding_profile_id", "TEXT NOT NULL DEFAULT 'default'")
            _ensure_column(conn, "knowledge_ingest_jobs", "error_code", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "knowledge_ingest_jobs", "retryable", "INTEGER NOT NULL DEFAULT 0")
            _ensure_column(conn, "knowledge_ingest_jobs", "staged_file_path", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_ingest_jobs_status_updated "
                "ON knowledge_ingest_jobs(status, updated_at)"
            )
            self._ensure_sqlite_vec_schema(conn)

    def upsert_source(self, source: KnowledgeSource) -> KnowledgeSource:
        with self._connect() as conn:
            self._upsert_source(conn, source)
        return source

    def find_source_id_by_uri_version(self, namespace: str, uri: str, version: str) -> str | None:
        normalized_uri = str(uri or "")
        if not normalized_uri:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT source_id
                FROM knowledge_sources
                WHERE namespace=? AND uri=? AND version=? AND status='active'
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (namespace, normalized_uri, str(version or "")),
            ).fetchone()
        return str(row["source_id"]) if row is not None else None


    def clear_embeddings(self, namespace: str) -> None:
        with self._connect() as conn:
            rows = conn.execute("SELECT chunk_id FROM knowledge_embeddings WHERE namespace=?", (namespace,)).fetchall()
            self._delete_sqlite_vec_embeddings(conn, namespace, chunk_ids=[str(row["chunk_id"]) for row in rows])
            conn.execute("DELETE FROM knowledge_embeddings WHERE namespace=?", (namespace,))

    def find_source_id_by_title(self, namespace: str, title: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_id FROM knowledge_sources WHERE namespace=? AND title=? AND status='active' ORDER BY created_at DESC LIMIT 1",
                (namespace, title),
            ).fetchone()
        return str(row["source_id"]) if row is not None else None

    def get_source(self, namespace: str, source_id: str) -> KnowledgeSource | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_sources WHERE namespace=? AND source_id=? AND status='active'",
                (namespace, source_id),
            ).fetchone()
        return _source_from_row(row) if row is not None else None

    def get_source_title(self, namespace: str, source_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT title FROM knowledge_sources WHERE namespace=? AND source_id=? AND status='active'",
                (namespace, source_id),
            ).fetchone()
        return str(row["title"]) if row is not None else ""

    def replace_chunks(self, namespace: str, source_id: str, chunks: list[KnowledgeChunk]) -> None:
        with self._connect() as conn:
            self._replace_chunks(conn, namespace, source_id, chunks)

    def replace_source_bundle(
        self,
        *,
        source: KnowledgeSource,
        chunks: list[KnowledgeChunk],
        vectors: list[list[float]],
        model_id: str,
        dimension: int,
        embedding_config_hash: str,
        embedding_profile_id: str = "default",
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        with self._connect() as conn:
            self._replace_source_bundle(
                conn,
                source=source,
                chunks=chunks,
                vectors=vectors,
                model_id=model_id,
                dimension=dimension,
                embedding_config_hash=embedding_config_hash,
                embedding_profile_id=embedding_profile_id,
            )

    def complete_ingest_job_with_source_bundle(
        self,
        *,
        namespace: str,
        job_id: str,
        source_title: str,
        source: KnowledgeSource,
        chunks: list[KnowledgeChunk],
        vectors: list[list[float]],
        model_id: str,
        dimension: int,
        embedding_config_hash: str,
        embedding_profile_id: str = "default",
    ) -> bool:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM knowledge_ingest_jobs WHERE namespace=? AND job_id=?",
                (namespace, job_id),
            ).fetchone()
            if row is None or str(row["status"]) in {"completed", "failed", "cancelled"}:
                return False
            self._replace_source_bundle(
                conn,
                source=source,
                chunks=chunks,
                vectors=vectors,
                model_id=model_id,
                dimension=dimension,
                embedding_config_hash=embedding_config_hash,
                embedding_profile_id=embedding_profile_id,
            )
            now = utc_now_iso()
            cursor = conn.execute(
                """
                UPDATE knowledge_ingest_jobs SET
                  source_title=?, status='completed', chunks_total=?, chunks_embedded=?,
                  percent=100.0, message='completed', error='', error_code='', retryable=0,
                  updated_at=?
                WHERE namespace=? AND job_id=?
                  AND status NOT IN ('completed', 'failed', 'cancelled')
                """,
                (
                    source_title,
                    len(chunks),
                    len(vectors),
                    now,
                    namespace,
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("ingest job changed while publishing source bundle")
            return True

    def get_chunk(self, namespace: str, chunk_id: str) -> KnowledgeChunk | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_chunks WHERE namespace=? AND chunk_id=? AND status='active'",
                (namespace, chunk_id),
            ).fetchone()
        return _chunk_from_row(row) if row is not None else None

    def search_fts(self, namespace: str, query: str, *, limit: int) -> list[KnowledgeChunk]:
        match_query = _normalize_query(query)
        if not match_query:
            return []
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT c.*
                    FROM knowledge_chunks_fts f
                    JOIN knowledge_chunks c ON c.namespace=f.namespace AND c.chunk_id=f.chunk_id
                    WHERE f.namespace=? AND f.knowledge_chunks_fts MATCH ? AND c.status='active'
                    ORDER BY c.ordinal ASC, c.chunk_id ASC
                    LIMIT ?
                    """,
                    (namespace, match_query, limit),
                ).fetchall()
            except sqlite3.Error:
                return self.find_chunks_containing(namespace, query, limit=limit)
        return [_chunk_from_row(row) for row in rows]

    def find_chunks_containing(self, namespace: str, query: str, *, limit: int) -> list[KnowledgeChunk]:
        text = str(query or "").strip()
        if not text:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM knowledge_chunks
                WHERE namespace=? AND status='active' AND text LIKE ?
                ORDER BY ordinal ASC, chunk_id ASC
                LIMIT ?
                """,
                (namespace, f"%{text}%", limit),
            ).fetchall()
        return [_chunk_from_row(row) for row in rows]

    def delete_source(self, namespace: str, source_id: str) -> KnowledgeDeleteResult:
        now = utc_now_iso()
        with self._connect() as conn:
            chunk_rows = conn.execute(
                "SELECT chunk_id FROM knowledge_chunks WHERE namespace=? AND source_id=? AND status='active'",
                (namespace, source_id),
            ).fetchall()
            for row in chunk_rows:
                self._delete_fts(conn, namespace, str(row["chunk_id"]))
            conn.execute(
                "UPDATE knowledge_sources SET status='deleted', updated_at=? WHERE namespace=? AND source_id=?",
                (now, namespace, source_id),
            )
            conn.execute(
                "UPDATE knowledge_chunks SET status='deleted', updated_at=? WHERE namespace=? AND source_id=?",
                (now, namespace, source_id),
            )
            chunk_ids = [str(row["chunk_id"]) for row in chunk_rows]
            self._delete_sqlite_vec_embeddings(conn, namespace, chunk_ids=chunk_ids)
            conn.execute(
                "UPDATE knowledge_embeddings SET status='deleted', updated_at=? WHERE namespace=? AND chunk_id IN (SELECT chunk_id FROM knowledge_chunks WHERE namespace=? AND source_id=?)",
                (now, namespace, namespace, source_id),
            )
        return KnowledgeDeleteResult(deleted_source_id=source_id, deleted_chunk_count=len(chunk_rows))

    def set_namespace_config_hash(
        self,
        namespace: str,
        embedding_config_hash: str,
        embedding_profile_id: str = "default",
    ) -> None:
        with self._connect() as conn:
            self._set_namespace_config_hash(
                conn,
                namespace,
                embedding_config_hash,
                embedding_profile_id,
            )

    def get_namespace_config_hash(self, namespace: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT embedding_config_hash FROM knowledge_namespaces WHERE namespace=?",
                (namespace,),
            ).fetchone()
        return str(row["embedding_config_hash"]) if row is not None else None

    def get_namespace_embedding_profile_id(self, namespace: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT embedding_profile_id FROM knowledge_namespaces WHERE namespace=?",
                (namespace,),
            ).fetchone()
        return str(row["embedding_profile_id"]) if row is not None else None

    def replace_namespace_embeddings(
        self,
        *,
        namespace: str,
        chunks: list[KnowledgeChunk],
        vectors: list[list[float]],
        model_id: str,
        dimension: int,
        embedding_config_hash: str,
        embedding_profile_id: str,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT chunk_id FROM knowledge_embeddings WHERE namespace=?",
                (namespace,),
            ).fetchall()
            self._delete_sqlite_vec_embeddings(
                conn,
                namespace,
                chunk_ids=[str(row["chunk_id"]) for row in existing],
            )
            conn.execute("DELETE FROM knowledge_embeddings WHERE namespace=?", (namespace,))
            for chunk, vector in zip(chunks, vectors, strict=True):
                self._upsert_embedding(
                    conn,
                    namespace=namespace,
                    chunk_id=chunk.chunk_id,
                    model_id=model_id,
                    dimension=dimension,
                    embedding_config_hash=embedding_config_hash,
                    vector=vector,
                )
            self._set_namespace_config_hash(
                conn,
                namespace,
                embedding_config_hash,
                embedding_profile_id,
            )

    def upsert_embedding(
        self,
        *,
        namespace: str,
        chunk_id: str,
        model_id: str,
        dimension: int,
        embedding_config_hash: str,
        vector: list[float],
    ) -> None:
        with self._connect() as conn:
            self._upsert_embedding(
                conn,
                namespace=namespace,
                chunk_id=chunk_id,
                model_id=model_id,
                dimension=dimension,
                embedding_config_hash=embedding_config_hash,
                vector=vector,
            )

    def list_embeddings(self, namespace: str, embedding_config_hash: str) -> list[KnowledgeEmbeddingRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_embeddings WHERE namespace=? AND embedding_config_hash=? AND status='active'",
                (namespace, embedding_config_hash),
            ).fetchall()
        return [_embedding_from_row(row) for row in rows]

    def query_sqlite_vec(
        self,
        namespace: str,
        embedding_config_hash: str,
        query_vector: list[float],
        *,
        top_k: int,
    ) -> VectorQueryResult:
        table_name = _sqlite_vec_table_name(len(query_vector))
        with self._connect() as conn:
            if not table_name or not self._sqlite_vec_ready(conn):
                return VectorQueryResult(status=VectorStatus.DISABLED, message="sqlite-vec table is not available")
            active_count = self._active_embedding_count(conn, namespace, embedding_config_hash, len(query_vector))
            if active_count <= 0:
                namespace_hash = self.get_namespace_config_hash(namespace)
                if namespace_hash == embedding_config_hash:
                    return VectorQueryResult(status=VectorStatus.AVAILABLE, items=[])
                return VectorQueryResult(
                    status=VectorStatus.CONFIG_MISMATCH,
                    message="Current embedding config has no sqlite-vec rows for this namespace. Run knowledge.reindex --namespace xxx.",
                )
            mapped_count = self._active_sqlite_vec_map_count(conn, namespace, embedding_config_hash, len(query_vector))
            if mapped_count < active_count:
                return VectorQueryResult(
                    status=VectorStatus.BACKEND_ERROR,
                    message="sqlite-vec index has fewer active rows than embeddings. Run knowledge.reindex --namespace xxx.",
                )
            table_count = self._sqlite_vec_table_row_count(conn, table_name=table_name, rowids=self._active_sqlite_vec_rowids(conn, namespace, embedding_config_hash, len(query_vector)))
            if table_count < mapped_count:
                return VectorQueryResult(
                    status=VectorStatus.BACKEND_ERROR,
                    message="sqlite-vec index table rows are missing while embeddings exist. Run knowledge.reindex --namespace xxx.",
                )
            try:
                import sqlite_vec  # type: ignore[import-not-found]

                rows = conn.execute(
                    f"""
                    SELECT m.chunk_id, v.distance
                    FROM {table_name} v
                    JOIN knowledge_embedding_vec_map m ON m.vec_rowid = v.rowid
                    JOIN knowledge_chunks c ON c.namespace=m.namespace AND c.chunk_id=m.chunk_id
                    JOIN knowledge_embeddings e ON e.namespace=m.namespace
                      AND e.chunk_id=m.chunk_id
                      AND e.embedding_config_hash=m.embedding_config_hash
                      AND e.dimension=m.dimension
                    WHERE v.embedding MATCH ?
                      AND k = ?
                      AND m.namespace = ?
                      AND m.embedding_config_hash = ?
                      AND m.dimension = ?
                      AND c.status = 'active'
                      AND e.status = 'active'
                    ORDER BY v.distance ASC
                    LIMIT ?
                    """,
                    (
                        sqlite_vec.serialize_float32(query_vector),
                        top_k,
                        namespace,
                        embedding_config_hash,
                        len(query_vector),
                        top_k,
                    ),
                ).fetchall()
            except sqlite3.Error as exc:
                return VectorQueryResult(status=VectorStatus.BACKEND_ERROR, message=f"sqlite-vec query failed: {exc}")
        return VectorQueryResult(
            status=VectorStatus.AVAILABLE,
            items=[VectorResultItem(chunk_id=str(row["chunk_id"]), score=float(row["distance"])) for row in rows],
        )

    def record_search_run(
        self,
        *,
        namespace: str,
        query: str,
        filters: dict[str, object],
        result_count: int,
        retrieval_mode: str,
        degraded_reason: str,
    ) -> str:
        run_id = f"ksrun_{uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_search_runs(
                  run_id, namespace, query, filters_json, result_count,
                  retrieval_mode, degraded_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    namespace,
                    query,
                    json.dumps(filters, ensure_ascii=False, sort_keys=True),
                    result_count,
                    retrieval_mode,
                    degraded_reason,
                    utc_now_iso(),
                ),
            )
        return run_id

    def list_search_runs(self, namespace: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_search_runs WHERE namespace=? ORDER BY created_at ASC, run_id ASC",
                (namespace,),
            ).fetchall()
        return [
            {
                "run_id": str(row["run_id"]),
                "namespace": str(row["namespace"]),
                "query": str(row["query"]),
                "filters": json.loads(str(row["filters_json"] or "{}")),
                "result_count": int(row["result_count"]),
                "retrieval_mode": str(row["retrieval_mode"]),
                "degraded_reason": str(row["degraded_reason"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def list_chunks(self, namespace: str, *, source_id: str | None = None) -> list[KnowledgeChunk]:
        with self._connect() as conn:
            if source_id:
                rows = conn.execute(
                    "SELECT * FROM knowledge_chunks WHERE namespace=? AND source_id=? AND status='active' ORDER BY ordinal ASC, chunk_id ASC",
                    (namespace, source_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM knowledge_chunks WHERE namespace=? AND status='active' ORDER BY source_id ASC, ordinal ASC, chunk_id ASC",
                    (namespace,),
                ).fetchall()
        return [_chunk_from_row(row) for row in rows]

    def count_sources(self, namespace: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM knowledge_sources WHERE namespace=? AND status='active'",
                (namespace,),
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def count_chunks(self, namespace: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM knowledge_chunks WHERE namespace=? AND status='active'",
                (namespace,),
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def list_namespace_summaries(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                WITH namespaces(namespace) AS (
                  SELECT namespace FROM knowledge_namespaces
                  UNION SELECT namespace FROM knowledge_sources
                  UNION SELECT namespace FROM knowledge_chunks
                  UNION SELECT namespace FROM knowledge_ingest_jobs
                )
                SELECT
                  n.namespace,
                  COALESCE((SELECT COUNT(*) FROM knowledge_sources s
                    WHERE s.namespace=n.namespace AND s.status='active'), 0) AS source_count,
                  COALESCE((SELECT COUNT(*) FROM knowledge_chunks c
                    WHERE c.namespace=n.namespace AND c.status='active'), 0) AS chunk_count,
                  COALESCE((SELECT embedding_config_hash FROM knowledge_namespaces k
                    WHERE k.namespace=n.namespace), '') AS index_embedding_config_hash,
                  COALESCE((SELECT embedding_profile_id FROM knowledge_namespaces k
                    WHERE k.namespace=n.namespace), 'default') AS embedding_profile_id
                FROM namespaces n
                ORDER BY n.namespace ASC
                """
            ).fetchall()
        return [
            {
                "namespace": str(row["namespace"]),
                "source_count": int(row["source_count"]),
                "chunk_count": int(row["chunk_count"]),
                "index_embedding_config_hash": str(row["index_embedding_config_hash"]),
                "embedding_profile_id": str(row["embedding_profile_id"]),
            }
            for row in rows
        ]

    def list_source_summaries(
        self,
        namespace: str,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, object]], int]:
        offset = (page - 1) * page_size
        with self._connect() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) AS count FROM knowledge_sources WHERE namespace=? AND status='active'",
                (namespace,),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT s.*, COUNT(c.chunk_id) AS chunk_count
                FROM knowledge_sources s
                LEFT JOIN knowledge_chunks c
                  ON c.namespace=s.namespace AND c.source_id=s.source_id AND c.status='active'
                WHERE s.namespace=? AND s.status='active'
                GROUP BY s.namespace, s.source_id
                ORDER BY s.updated_at DESC, s.source_id ASC
                LIMIT ? OFFSET ?
                """,
                (namespace, page_size, offset),
            ).fetchall()
        return (
            [
                {
                    **_source_from_row(row).model_dump(mode="json"),
                    "chunk_count": int(row["chunk_count"]),
                }
                for row in rows
            ],
            int(total_row["count"]) if total_row is not None else 0,
        )

    def list_chunk_summaries(
        self,
        namespace: str,
        source_id: str,
        *,
        page: int,
        page_size: int,
        preview_chars: int = 240,
    ) -> tuple[list[dict[str, object]], int]:
        offset = (page - 1) * page_size
        with self._connect() as conn:
            total_row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM knowledge_chunks
                WHERE namespace=? AND source_id=? AND status='active'
                """,
                (namespace, source_id),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT * FROM knowledge_chunks
                WHERE namespace=? AND source_id=? AND status='active'
                ORDER BY ordinal ASC, chunk_id ASC
                LIMIT ? OFFSET ?
                """,
                (namespace, source_id, page_size, offset),
            ).fetchall()
        return (
            [
                {
                    "namespace": str(row["namespace"]),
                    "chunk_id": str(row["chunk_id"]),
                    "source_id": str(row["source_id"]),
                    "heading": str(row["heading"]),
                    "ordinal": int(row["ordinal"]),
                    "token_estimate": int(row["token_estimate"]),
                    "metadata": json.loads(str(row["metadata_json"] or "{}")),
                    "status": str(row["status"]),
                    "text_preview": str(row["text"])[:preview_chars],
                    "updated_at": str(row["updated_at"]),
                }
                for row in rows
            ],
            int(total_row["count"]) if total_row is not None else 0,
        )

    def list_ingest_job_summaries(
        self,
        namespace: str,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, object]], int]:
        offset = (page - 1) * page_size
        with self._connect() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) AS count FROM knowledge_ingest_jobs WHERE namespace=?",
                (namespace,),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT * FROM knowledge_ingest_jobs
                WHERE namespace=?
                ORDER BY updated_at DESC, job_id ASC
                LIMIT ? OFFSET ?
                """,
                (namespace, page_size, offset),
            ).fetchall()
        return (
            [_ingest_job_from_row(row).model_dump(mode="json") for row in rows],
            int(total_row["count"]) if total_row is not None else 0,
        )

    def ingest_job_diagnostics(self) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  SUM(CASE WHEN status IN ('queued', 'reading', 'chunking', 'embedding') THEN 1 ELSE 0 END) AS active_count,
                  SUM(CASE WHEN error_code='KNOWLEDGE_JOB_INTERRUPTED' THEN 1 ELSE 0 END) AS interrupted_count
                FROM knowledge_ingest_jobs
                """
            ).fetchone()
        return {
            "active_count": int((row or {})["active_count"] or 0),
            "interrupted_count": int((row or {})["interrupted_count"] or 0),
        }

    def upsert_ingest_job(
        self,
        *,
        namespace: str,
        job_id: str,
        source_title: str,
        status: str,
        chunks_total: int = 0,
        chunks_embedded: int = 0,
        percent: float = 0.0,
        message: str = "",
        error: str = "",
        error_code: str = "",
        retryable: bool = False,
        staged_file_path: str = "",
    ) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_ingest_jobs (
                  namespace, job_id, source_title, status, chunks_total, chunks_embedded,
                  percent, message, error, error_code, retryable, staged_file_path,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, job_id) DO UPDATE SET
                  source_title=excluded.source_title,
                  status=excluded.status,
                  chunks_total=excluded.chunks_total,
                  chunks_embedded=excluded.chunks_embedded,
                  percent=excluded.percent,
                  message=excluded.message,
                  error=excluded.error,
                  error_code=excluded.error_code,
                  retryable=excluded.retryable,
                  staged_file_path=excluded.staged_file_path,
                  updated_at=excluded.updated_at
                """,
                (
                    namespace,
                    job_id,
                    source_title,
                    status,
                    chunks_total,
                    chunks_embedded,
                    percent,
                    message,
                    error,
                    error_code,
                    int(retryable),
                    staged_file_path,
                    now,
                    now,
                ),
            )

    def update_ingest_job(
        self,
        *,
        namespace: str,
        job_id: str,
        source_title: str,
        status: str,
        chunks_total: int,
        chunks_embedded: int,
        percent: float,
        message: str,
        error: str,
        error_code: str,
        retryable: bool,
    ) -> bool:
        now = utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE knowledge_ingest_jobs SET
                  source_title=?, status=?, chunks_total=?, chunks_embedded=?,
                  percent=?, message=?, error=?, error_code=?, retryable=?, updated_at=?
                WHERE namespace=? AND job_id=?
                  AND status NOT IN ('completed', 'failed', 'cancelled')
                """,
                (
                    source_title,
                    status,
                    chunks_total,
                    chunks_embedded,
                    percent,
                    message,
                    error,
                    error_code,
                    int(retryable),
                    now,
                    namespace,
                    job_id,
                ),
            )
            return cursor.rowcount == 1

    def recover_interrupted_ingest_jobs(self) -> int:
        now = utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE knowledge_ingest_jobs SET
                  status='failed',
                  message='interrupted by runtime restart',
                  error='runtime stopped before ingest completed',
                  error_code='KNOWLEDGE_JOB_INTERRUPTED',
                  retryable=1,
                  updated_at=?
                WHERE status IN ('queued', 'reading', 'chunking', 'embedding')
                """,
                (now,),
            )
            return max(cursor.rowcount, 0)

    def list_ingest_jobs(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_ingest_jobs ORDER BY updated_at DESC, job_id ASC"
            ).fetchall()
        return [_ingest_job_from_row(row).model_dump(mode="json") for row in rows]

    def get_ingest_job(self, namespace: str, job_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_ingest_jobs WHERE namespace=? AND job_id=?",
                (namespace, job_id),
            ).fetchone()
        if row is None:
            return None
        return _ingest_job_from_row(row).model_dump(mode="json")

    def _replace_source_bundle(
        self,
        conn: sqlite3.Connection,
        *,
        source: KnowledgeSource,
        chunks: list[KnowledgeChunk],
        vectors: list[list[float]],
        model_id: str,
        dimension: int,
        embedding_config_hash: str,
        embedding_profile_id: str = "default",
    ) -> None:
        self._upsert_source(conn, source)
        self._replace_chunks(conn, source.namespace, source.source_id, chunks)
        for chunk, vector in zip(chunks, vectors, strict=True):
            self._upsert_embedding(
                conn,
                namespace=source.namespace,
                chunk_id=chunk.chunk_id,
                model_id=model_id,
                dimension=dimension,
                embedding_config_hash=embedding_config_hash,
                vector=vector,
            )
        self._set_namespace_config_hash(
            conn,
            source.namespace,
            embedding_config_hash,
            embedding_profile_id,
        )

    @staticmethod
    def _upsert_source(conn: sqlite3.Connection, source: KnowledgeSource) -> None:
        conn.execute(
            """
            INSERT INTO knowledge_sources (
              namespace, source_id, kind, title, uri, version, metadata_json, status,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(namespace, source_id) DO UPDATE SET
              kind=excluded.kind,
              title=excluded.title,
              uri=excluded.uri,
              version=excluded.version,
              metadata_json=excluded.metadata_json,
              status=excluded.status,
              updated_at=excluded.updated_at
            """,
            (
                source.namespace,
                source.source_id,
                source.kind,
                source.title,
                source.uri,
                source.version,
                json.dumps(source.metadata, ensure_ascii=False, sort_keys=True),
                source.status,
                source.created_at,
                source.updated_at,
            ),
        )

    def _replace_chunks(
        self,
        conn: sqlite3.Connection,
        namespace: str,
        source_id: str,
        chunks: list[KnowledgeChunk],
    ) -> None:
        existing = conn.execute(
            "SELECT chunk_id FROM knowledge_chunks WHERE namespace=? AND source_id=?",
            (namespace, source_id),
        ).fetchall()
        for row in existing:
            self._delete_fts(conn, namespace, str(row["chunk_id"]))
        conn.execute(
            "DELETE FROM knowledge_chunks WHERE namespace=? AND source_id=?",
            (namespace, source_id),
        )
        self._delete_orphan_embeddings(conn, namespace)
        source_row = conn.execute(
            "SELECT title FROM knowledge_sources WHERE namespace=? AND source_id=? AND status='active'",
            (namespace, source_id),
        ).fetchone()
        title = str(source_row["title"]) if source_row is not None else ""
        for chunk in chunks:
            conn.execute(
                """
                INSERT INTO knowledge_chunks (
                  namespace, chunk_id, source_id, heading, ordinal, text, token_estimate,
                  metadata_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk.namespace,
                    chunk.chunk_id,
                    chunk.source_id,
                    chunk.heading,
                    chunk.ordinal,
                    chunk.text,
                    chunk.token_estimate,
                    json.dumps(chunk.metadata, ensure_ascii=False, sort_keys=True),
                    chunk.status,
                    chunk.created_at,
                    chunk.updated_at,
                ),
            )
            self._insert_fts(
                conn,
                namespace,
                chunk.chunk_id,
                title,
                chunk.heading,
                chunk.text,
            )

    @staticmethod
    def _set_namespace_config_hash(
        conn: sqlite3.Connection,
        namespace: str,
        embedding_config_hash: str,
        embedding_profile_id: str = "default",
    ) -> None:
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO knowledge_namespaces(
              namespace, embedding_config_hash, embedding_profile_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(namespace) DO UPDATE SET
              embedding_config_hash=excluded.embedding_config_hash,
              embedding_profile_id=excluded.embedding_profile_id,
              updated_at=excluded.updated_at
            """,
            (namespace, embedding_config_hash, embedding_profile_id, now, now),
        )

    def _upsert_embedding(
        self,
        conn: sqlite3.Connection,
        *,
        namespace: str,
        chunk_id: str,
        model_id: str,
        dimension: int,
        embedding_config_hash: str,
        vector: list[float],
    ) -> None:
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO knowledge_embeddings (
              namespace, chunk_id, model_id, dimension, embedding_config_hash, vector_json,
              status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(namespace, chunk_id, embedding_config_hash) DO UPDATE SET
              model_id=excluded.model_id,
              dimension=excluded.dimension,
              vector_json=excluded.vector_json,
              status='active',
              updated_at=excluded.updated_at
            """,
            (
                namespace,
                chunk_id,
                model_id,
                dimension,
                embedding_config_hash,
                json.dumps(vector),
                now,
                now,
            ),
        )
        self._upsert_sqlite_vec_embedding(
            conn,
            namespace=namespace,
            chunk_id=chunk_id,
            embedding_config_hash=embedding_config_hash,
            vector=vector,
            now=now,
        )

    def _insert_fts(self, conn: sqlite3.Connection, namespace: str, chunk_id: str, title: str, heading: str, text: str) -> None:
        conn.execute(
            "INSERT INTO knowledge_chunks_fts(namespace, chunk_id, title, heading, text) VALUES (?, ?, ?, ?, ?)",
            (namespace, chunk_id, title, heading, text),
        )

    def _delete_fts(self, conn: sqlite3.Connection, namespace: str, chunk_id: str) -> None:
        conn.execute(
            "DELETE FROM knowledge_chunks_fts WHERE namespace=? AND chunk_id=?",
            (namespace, chunk_id),
        )

    def _delete_orphan_embeddings(self, conn: sqlite3.Connection, namespace: str) -> None:
        rows = conn.execute(
            "SELECT chunk_id FROM knowledge_embeddings WHERE namespace=? AND chunk_id NOT IN (SELECT chunk_id FROM knowledge_chunks WHERE namespace=?)",
            (namespace, namespace),
        ).fetchall()
        chunk_ids = [str(row["chunk_id"]) for row in rows]
        self._delete_sqlite_vec_embeddings(conn, namespace, chunk_ids=chunk_ids)
        conn.execute(
            "DELETE FROM knowledge_embeddings WHERE namespace=? AND chunk_id NOT IN (SELECT chunk_id FROM knowledge_chunks WHERE namespace=?)",
            (namespace, namespace),
        )

    def _delete_sqlite_vec_embeddings(self, conn: sqlite3.Connection, namespace: str, *, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = conn.execute(
            f"SELECT vec_rowid, dimension FROM knowledge_embedding_vec_map WHERE namespace=? AND chunk_id IN ({placeholders})",
            (namespace, *chunk_ids),
        ).fetchall()
        for row in rows:
            table_name = _sqlite_vec_table_name(int(row["dimension"]))
            if table_name and self._sqlite_vec_ready(conn):
                try:
                    conn.execute(f"DELETE FROM {table_name} WHERE rowid=?", (int(row["vec_rowid"]),))
                except sqlite3.Error:
                    pass
        conn.execute(
            f"DELETE FROM knowledge_embedding_vec_map WHERE namespace=? AND chunk_id IN ({placeholders})",
            (namespace, *chunk_ids),
        )

    def _ensure_sqlite_vec_schema(self, conn: sqlite3.Connection) -> None:
        if not self._sqlite_vec_ready(conn):
            return
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_embedding_vec USING vec0(embedding float[1024])")
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_embedding_vec_512 USING vec0(embedding float[512])")
        except sqlite3.Error:
            return

    def _upsert_sqlite_vec_embedding(
        self,
        conn: sqlite3.Connection,
        *,
        namespace: str,
        chunk_id: str,
        embedding_config_hash: str,
        vector: list[float],
        now: str,
    ) -> None:
        table_name = _sqlite_vec_table_name(len(vector))
        if not table_name or not self._sqlite_vec_ready(conn):
            return
        try:
            import sqlite_vec  # type: ignore[import-not-found]

            row = conn.execute(
                """
                SELECT vec_rowid
                FROM knowledge_embedding_vec_map
                WHERE namespace=? AND chunk_id=? AND embedding_config_hash=? AND dimension=?
                """,
                (namespace, chunk_id, embedding_config_hash, len(vector)),
            ).fetchone()
            if row is None:
                cursor = conn.execute(
                    """
                    INSERT INTO knowledge_embedding_vec_map(
                      namespace, chunk_id, embedding_config_hash, dimension, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (namespace, chunk_id, embedding_config_hash, len(vector), now, now),
                )
                vec_rowid = int(cursor.lastrowid)
            else:
                vec_rowid = int(row["vec_rowid"])
                conn.execute(
                    "UPDATE knowledge_embedding_vec_map SET updated_at=? WHERE vec_rowid=?",
                    (now, vec_rowid),
                )
                conn.execute(f"DELETE FROM {table_name} WHERE rowid=?", (vec_rowid,))
            conn.execute(
                f"INSERT INTO {table_name}(rowid, embedding) VALUES (?, ?)",
                (vec_rowid, sqlite_vec.serialize_float32(vector)),
            )
        except sqlite3.Error:
            return

    def _sqlite_vec_ready(self, conn: sqlite3.Connection) -> bool:
        try:
            conn.execute("SELECT vec_version()").fetchone()
            return True
        except sqlite3.Error:
            return False

    def _active_embedding_count(self, conn: sqlite3.Connection, namespace: str, embedding_config_hash: str, dimension: int) -> int:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM knowledge_embeddings e
            JOIN knowledge_chunks c ON c.namespace=e.namespace AND c.chunk_id=e.chunk_id
            WHERE e.namespace=? AND e.embedding_config_hash=? AND e.dimension=?
              AND e.status='active' AND c.status='active'
            """,
            (namespace, embedding_config_hash, dimension),
        ).fetchone()
        return int(row["count"]) if row is not None else 0

    def _active_sqlite_vec_map_count(self, conn: sqlite3.Connection, namespace: str, embedding_config_hash: str, dimension: int) -> int:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM knowledge_embedding_vec_map m
            JOIN knowledge_embeddings e ON e.namespace=m.namespace
              AND e.chunk_id=m.chunk_id
              AND e.embedding_config_hash=m.embedding_config_hash
              AND e.dimension=m.dimension
            JOIN knowledge_chunks c ON c.namespace=m.namespace AND c.chunk_id=m.chunk_id
            WHERE m.namespace=? AND m.embedding_config_hash=? AND m.dimension=?
              AND e.status='active' AND c.status='active'
            """,
            (namespace, embedding_config_hash, dimension),
        ).fetchone()
        return int(row["count"]) if row is not None else 0

    def _active_sqlite_vec_rowids(self, conn: sqlite3.Connection, namespace: str, embedding_config_hash: str, dimension: int) -> list[int]:
        rows = conn.execute(
            """
            SELECT m.vec_rowid
            FROM knowledge_embedding_vec_map m
            JOIN knowledge_embeddings e ON e.namespace=m.namespace
              AND e.chunk_id=m.chunk_id
              AND e.embedding_config_hash=m.embedding_config_hash
              AND e.dimension=m.dimension
            JOIN knowledge_chunks c ON c.namespace=m.namespace AND c.chunk_id=m.chunk_id
            WHERE m.namespace=? AND m.embedding_config_hash=? AND m.dimension=?
              AND e.status='active' AND c.status='active'
            """,
            (namespace, embedding_config_hash, dimension),
        ).fetchall()
        return [int(row["vec_rowid"]) for row in rows]

    def _sqlite_vec_table_row_count(self, conn: sqlite3.Connection, *, table_name: str, rowids: list[int]) -> int:
        if not rowids:
            return 0
        placeholders = ",".join("?" for _ in rowids)
        row = conn.execute(
            f"SELECT COUNT(*) AS count FROM {table_name} WHERE rowid IN ({placeholders})",
            tuple(rowids),
        ).fetchone()
        return int(row["count"]) if row is not None else 0


def _source_from_row(row: sqlite3.Row) -> KnowledgeSource:
    return KnowledgeSource(
        namespace=str(row["namespace"]),
        source_id=str(row["source_id"]),
        kind=str(row["kind"]),
        title=str(row["title"]),
        uri=str(row["uri"]),
        version=str(row["version"] or ""),
        metadata=json.loads(str(row["metadata_json"] or "{}")),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _chunk_from_row(row: sqlite3.Row) -> KnowledgeChunk:
    return KnowledgeChunk(
        namespace=str(row["namespace"]),
        chunk_id=str(row["chunk_id"]),
        source_id=str(row["source_id"]),
        heading=str(row["heading"] or ""),
        ordinal=int(row["ordinal"]),
        text=str(row["text"]),
        token_estimate=int(row["token_estimate"]),
        metadata=json.loads(str(row["metadata_json"] or "{}")),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _embedding_from_row(row: sqlite3.Row) -> KnowledgeEmbeddingRecord:
    return KnowledgeEmbeddingRecord(
        namespace=str(row["namespace"]),
        chunk_id=str(row["chunk_id"]),
        model_id=str(row["model_id"]),
        dimension=int(row["dimension"]),
        embedding_config_hash=str(row["embedding_config_hash"]),
        vector=[float(item) for item in json.loads(str(row["vector_json"] or "[]"))],
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _ingest_job_from_row(row: sqlite3.Row) -> KnowledgeIngestJob:
    return KnowledgeIngestJob(
        namespace=str(row["namespace"]),
        job_id=str(row["job_id"]),
        source_title=str(row["source_title"]),
        status=str(row["status"]),
        chunks_total=int(row["chunks_total"]),
        chunks_embedded=int(row["chunks_embedded"]),
        percent=float(row["percent"]),
        message=str(row["message"]),
        error=str(row["error"]),
        error_code=str(row["error_code"]),
        retryable=bool(row["retryable"]),
        staged_file_path=str(row["staged_file_path"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _normalize_query(query: str) -> str:
    return " ".join(token for token in str(query or "").strip().split() if token) or str(query or "").strip()


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
    columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def _sqlite_vec_table_name(dimension: int) -> str:
    if dimension == 1024:
        return "knowledge_embedding_vec"
    if dimension == 512:
        return "knowledge_embedding_vec_512"
    return ""
