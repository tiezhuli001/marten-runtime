from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from marten_runtime.memory.models import MemoryItem


class SQLiteMemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                  memory_id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  scope TEXT NOT NULL,
                  agent_id TEXT,
                  workspace_id TEXT,
                  type TEXT NOT NULL,
                  section TEXT NOT NULL,
                  content TEXT NOT NULL,
                  source_excerpt TEXT NOT NULL DEFAULT '',
                  source_run_id TEXT,
                  status TEXT NOT NULL DEFAULT 'active',
                  priority INTEGER NOT NULL DEFAULT 50,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts USING fts5(
                  memory_id UNINDEXED,
                  content,
                  section,
                  tokenize='trigram'
                );
                CREATE INDEX IF NOT EXISTS idx_memory_items_active_lookup
                ON memory_items(user_id, status, scope, agent_id, workspace_id, type);
                CREATE INDEX IF NOT EXISTS idx_memory_items_priority_recent
                ON memory_items(user_id, status, priority, updated_at);
                """
            )

    def append(self, item: MemoryItem) -> MemoryItem:
        with self._connect() as conn:
            self._insert_item(conn, item)
            self._insert_fts(conn, item)
        return item

    def get(self, memory_id: str) -> MemoryItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return self._row_to_item(row) if row is not None else None

    def list_active(
        self,
        user_id: str,
        *,
        scope: str | None = None,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        type: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryItem]:
        clauses = ["user_id = ?", "status = 'active'"]
        params: list[object] = [user_id]
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if workspace_id is not None:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if type is not None:
            clauses.append("type = ?")
            params.append(type)
        sql = f"SELECT * FROM memory_items WHERE {' AND '.join(clauses)} ORDER BY priority DESC, updated_at DESC, memory_id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_item(row) for row in rows]


    def replace(self, memory_id: str, new_item: MemoryItem) -> MemoryItem:
        existing = self.get(memory_id)
        if existing is None:
            raise KeyError(f"memory item not found: {memory_id}")
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_items SET status = 'superseded', updated_at = ? WHERE memory_id = ?",
                (new_item.updated_at, memory_id),
            )
            self._delete_fts(conn, memory_id)
            self._insert_item(conn, new_item)
            self._insert_fts(conn, new_item)
        return new_item

    def delete(self, memory_id: str) -> MemoryItem:
        existing = self.get(memory_id)
        if existing is None:
            raise KeyError(f"memory item not found: {memory_id}")
        deleted = existing.model_copy(update={"status": "deleted", "updated_at": existing.updated_at})
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_items SET status = 'deleted', updated_at = ? WHERE memory_id = ?",
                (deleted.updated_at, memory_id),
            )
            self._delete_fts(conn, memory_id)
        return deleted

    def supersede(self, memory_id: str, *, updated_at: str | None = None) -> MemoryItem:
        existing = self.get(memory_id)
        if existing is None:
            raise KeyError(f"memory item not found: {memory_id}")
        superseded = existing.model_copy(
            update={"status": "superseded", "updated_at": updated_at or existing.updated_at}
        )
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_items SET status = 'superseded', updated_at = ? WHERE memory_id = ?",
                (superseded.updated_at, memory_id),
            )
            self._delete_fts(conn, memory_id)
        return superseded

    def search(
        self,
        user_id: str,
        query: str,
        *,
        scope: str | None = None,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        type: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        match_query = _normalize_fts_query(query)
        use_fts = bool(match_query)
        clauses = ["m.user_id = ?", "m.status = 'active'"]
        params: list[object] = [user_id]
        if use_fts:
            clauses.append("f.memory_items_fts MATCH ?")
            params.append(match_query)
        else:
            clauses.append("(m.content LIKE ? OR m.section LIKE ?)")
            like_query = f"%{str(query or '').strip()}%"
            params.extend([like_query, like_query])
        if scope is not None:
            clauses.append("m.scope = ?")
            params.append(scope)
        if agent_id is not None:
            clauses.append("m.agent_id = ?")
            params.append(agent_id)
        if workspace_id is not None:
            clauses.append("m.workspace_id = ?")
            params.append(workspace_id)
        if type is not None:
            clauses.append("m.type = ?")
            params.append(type)
        params.append(limit)
        sql = f"""
            SELECT m.*
            FROM memory_items_fts f
            JOIN memory_items m ON m.memory_id = f.memory_id
            WHERE {' AND '.join(clauses)}
            ORDER BY m.priority DESC, m.updated_at DESC, m.memory_id ASC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_item(row) for row in rows]


    def count_active(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM memory_items WHERE status = 'active'").fetchone()
        return int(row["count"] if row is not None else 0)

    def _insert_item(self, conn: sqlite3.Connection, item: MemoryItem) -> None:
        conn.execute(
            """
            INSERT INTO memory_items (
              memory_id, user_id, scope, agent_id, workspace_id, type, section,
              content, source_excerpt, source_run_id, status, priority, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.memory_id,
                item.user_id,
                item.scope,
                item.agent_id,
                item.workspace_id,
                item.type,
                item.section,
                item.content,
                item.source_excerpt,
                item.source_run_id,
                item.status,
                item.priority,
                item.created_at,
                item.updated_at,
            ),
        )

    def _insert_fts(self, conn: sqlite3.Connection, item: MemoryItem) -> None:
        if item.status != "active":
            return
        conn.execute(
            "INSERT INTO memory_items_fts(memory_id, content, section) VALUES (?, ?, ?)",
            (item.memory_id, item.content, item.section),
        )

    def _delete_fts(self, conn: sqlite3.Connection, memory_id: str) -> None:
        conn.execute("DELETE FROM memory_items_fts WHERE memory_id = ?", (memory_id,))

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            memory_id=str(row["memory_id"]),
            user_id=str(row["user_id"]),
            scope=str(row["scope"]),
            agent_id=row["agent_id"],
            workspace_id=row["workspace_id"],
            type=str(row["type"]),
            section=str(row["section"]),
            content=str(row["content"]),
            source_excerpt=str(row["source_excerpt"] or ""),
            source_run_id=row["source_run_id"],
            status=str(row["status"]),
            priority=int(row["priority"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def _normalize_fts_query(query: str) -> str:
    value = str(query or "").strip().casefold()
    if len(value) < 3:
        return ""
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[0-9a-zA-Z_]+|[\u4e00-\u9fff]+", value):
        for term in _fts_terms_for_token(token):
            if term in seen:
                continue
            seen.add(term)
            terms.append(term)
            if len(terms) >= 16:
                break
        if len(terms) >= 16:
            break
    return " OR ".join(f'"{term}"' for term in terms)


def _fts_terms_for_token(token: str) -> list[str]:
    if not token:
        return []
    if re.fullmatch(r"[\u4e00-\u9fff]+", token):
        if len(token) < 3:
            return []
        if len(token) == 3:
            return [token]
        return [token[index : index + 3] for index in range(0, len(token) - 2)]
    return [token] if len(token) >= 3 else []
