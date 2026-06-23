"""Unified SQLite store — merges graph.db + memory.db into a single database.

This is the V3 storage foundation.  It inherits all table schemas from
GraphStore and MemoryBackendStore so existing data can be migrated in-place.

Key improvements over 2.x:
- WAL mode + connection pool (via SQLitePool)
- Graph tables + memory tables in one DB
- Prepared vector column (BLOB) for sqlite-vec / future ANN indexes
- Recursive CTE neighbor queries (no more N+1 BFS)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .pool import SQLitePool


# ── Schema ───────────────────────────────────────────────────────────────────

_GRAPH_DDL = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    project TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    line INTEGER DEFAULT 0,
    metadata_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    type TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    metadata_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_nodes_type_name ON nodes(type, name);
CREATE INDEX IF NOT EXISTS idx_nodes_project   ON nodes(project);
CREATE INDEX IF NOT EXISTS idx_edges_source    ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target    ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type      ON edges(type);
CREATE INDEX IF NOT EXISTS idx_edges_source_type ON edges(source_id, type);
CREATE INDEX IF NOT EXISTS idx_edges_target_type ON edges(target_id, type);
CREATE INDEX IF NOT EXISTS idx_nodes_name       ON nodes(name);
"""

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS node_search
    USING fts5(id UNINDEXED, type, name, project, file_path, content);
"""

_MEMORY_DDL = """
CREATE TABLE IF NOT EXISTS json_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection TEXT NOT NULL,
    record_id TEXT DEFAULT '',
    type TEXT DEFAULT '',
    session_id TEXT DEFAULT '',
    project TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_json_records_collection  ON json_records(collection);
CREATE INDEX IF NOT EXISTS idx_json_records_record_id   ON json_records(record_id);
CREATE INDEX IF NOT EXISTS idx_json_records_created_at  ON json_records(created_at);
CREATE INDEX IF NOT EXISTS idx_json_records_type        ON json_records(type);
CREATE INDEX IF NOT EXISTS idx_json_records_session_id  ON json_records(session_id);
CREATE INDEX IF NOT EXISTS idx_json_records_project     ON json_records(project);

CREATE TABLE IF NOT EXISTS refs (
    ref_path TEXT PRIMARY KEY,
    created_at TEXT DEFAULT '',
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_mirror (
    name TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    updated_at TEXT DEFAULT ''
);
"""


class UnifiedStore:
    """Single SQLite database for graph + memory + future vectors.

    This class is the V3 replacement for both ``GraphStore`` and
    ``MemoryBackendStore``.  It owns a :class:`SQLitePool` and exposes
    helpers for graph operations, memory records, and (later) vector search.
    """

    def __init__(self, db_path: str | Path, pool_size: int = 4):
        self.db_path = Path(db_path)
        self.pool = SQLitePool(self.db_path, pool_size=pool_size)
        self._init_schema()

    # ── Schema init ──────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self.pool.connection() as conn:
            conn.executescript(_GRAPH_DDL)
            conn.executescript(_MEMORY_DDL)
            # FTS5 may not be available in every SQLite build
            try:
                conn.executescript(_FTS_DDL)
            except sqlite3.OperationalError:
                pass

    # ── Graph: node helpers ──────────────────────────────────────────────

    def upsert_nodes(self, rows: list[tuple]) -> None:
        """Bulk upsert nodes.  Each tuple: (id, type, name, project, file_path, line, metadata_json)."""
        with self.pool.transaction() as conn:
            conn.executemany(
                """INSERT INTO nodes(id, type, name, project, file_path, line, metadata_json)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     type=excluded.type, name=excluded.name, project=excluded.project,
                     file_path=excluded.file_path, line=excluded.line, metadata_json=excluded.metadata_json""",
                rows,
            )

    def upsert_edges(self, rows: list[tuple]) -> None:
        """Bulk upsert edges.  Each tuple: (id, source_id, target_id, type, confidence, metadata_json)."""
        with self.pool.transaction() as conn:
            conn.executemany(
                """INSERT INTO edges(id, source_id, target_id, type, confidence, metadata_json)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     source_id=excluded.source_id, target_id=excluded.target_id,
                     type=excluded.type, confidence=excluded.confidence,
                     metadata_json=excluded.metadata_json""",
                rows,
            )

    def node_by_id(self, node_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def find_nodes(self, query: str, types: list[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        rows = self._find_nodes_fts(query, types, limit)
        if not rows:
            rows = self._find_nodes_like(query, types, limit)
        return rows

    def _find_nodes_fts(self, query: str, types: list[str] | None, limit: int) -> list[dict[str, Any]]:
        import re as _re
        safe_terms = [_re.sub(r"[^\w\u3400-\u9fff]", "", t) for t in query.replace("-", " ").replace("/", " ").split() if t.strip()]
        safe_terms = [t for t in safe_terms if t]
        if not safe_terms:
            return []
        fts_query = " OR ".join(f'"{t}"' for t in safe_terms[:8])
        sql = "SELECT n.* FROM node_search s JOIN nodes n ON n.id=s.id WHERE node_search MATCH ?"
        args: list[Any] = [fts_query]
        if types:
            sql += " AND n.type IN (%s)" % ",".join("?" for _ in types)
            args.extend(types)
        sql += " LIMIT ?"
        args.append(limit)
        try:
            with self.pool.connection() as conn:
                rows = conn.execute(sql, args).fetchall()
            return [_row_to_dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    def _find_nodes_like(self, query: str, types: list[str] | None, limit: int) -> list[dict[str, Any]]:
        q = f"%{query.lower()}%"
        sql = ("SELECT * FROM nodes WHERE lower(name) LIKE ? OR lower(id) LIKE ? "
               "OR lower(file_path) LIKE ? OR lower(metadata_json) LIKE ?")
        args: list[Any] = [q, q, q, q]
        if types:
            sql += " AND type IN (%s)" % ",".join("?" for _ in types)
            args.extend(types)
        sql += " LIMIT ?"
        args.append(limit)
        with self.pool.connection() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_row_to_dict(r) for r in rows]

    def all_nodes(self) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT * FROM nodes").fetchall()
        return [_row_to_dict(r) for r in rows]

    def graph_counts(self) -> dict[str, int]:
        with self.pool.connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            e = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return {"nodes": n, "edges": e}

    # ── Graph: neighbors via recursive CTE ───────────────────────────────

    def neighbors(
        self,
        node_id: str,
        direction: str = "both",
        max_depth: int = 2,
        limit: int = 200,
        edge_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Multi-hop neighbor traversal using a single recursive CTE query.

        Replaces the 2.x BFS loop that issued one SQL query per depth level.
        """
        if direction == "downstream":
            join_cond = "e.source_id = c.node_id"
        elif direction == "upstream":
            join_cond = "e.target_id = c.node_id"
        else:  # both
            join_cond = "(e.source_id = c.node_id OR e.target_id = c.node_id)"

        type_filter = ""
        if edge_types:
            placeholders = ",".join("?" for _ in edge_types)
            type_filter = f" AND e.type IN ({placeholders})"

        sql = f"""
        WITH RECURSIVE chain(node_id, depth) AS (
            SELECT ?, 0
            UNION
            SELECT CASE WHEN e.source_id = c.node_id THEN e.target_id ELSE e.source_id END,
                   c.depth + 1
            FROM edges e
            JOIN chain c ON {join_cond}
            WHERE c.depth < ?{type_filter}
              AND CASE WHEN e.source_id = c.node_id THEN e.target_id ELSE e.source_id END != '{node_id}'
        )
        SELECT DISTINCT n.*, c.depth
        FROM chain c
        JOIN nodes n ON n.id = c.node_id
        WHERE c.node_id != ?
        ORDER BY c.depth
        LIMIT ?
        """
        params: list[Any] = [node_id, max_depth]
        if edge_types:
            params.extend(edge_types)
        params.extend([node_id, limit])

        with self.pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    # ── Graph: edges ─────────────────────────────────────────────────────

    def edges_for_node(self, node_id: str, direction: str = "both", limit: int = 200) -> list[dict[str, Any]]:
        if direction == "upstream":
            sql = "SELECT * FROM edges WHERE target_id=? LIMIT ?"
        elif direction == "downstream":
            sql = "SELECT * FROM edges WHERE source_id=? LIMIT ?"
        else:
            sql = "SELECT * FROM edges WHERE source_id=? OR target_id=? LIMIT ?"
            with self.pool.connection() as conn:
                rows = conn.execute(sql, (node_id, node_id, limit)).fetchall()
            return [_row_to_dict(r) for r in rows]
        with self.pool.connection() as conn:
            rows = conn.execute(sql, (node_id, limit)).fetchall()
        return [_row_to_dict(r) for r in rows]

    def clear_graph(self) -> None:
        with self.pool.transaction() as conn:
            conn.execute("DELETE FROM edges")
            conn.execute("DELETE FROM nodes")
            try:
                conn.execute("DELETE FROM node_search")
            except sqlite3.OperationalError:
                pass

    def remove_nodes_by_scope(self, project_filter: set[str], path_filters: list[str]) -> set[str]:
        """Remove nodes/edges matching scope. Returns removed node IDs."""
        with self.pool.transaction() as conn:
            conditions: list[str] = []
            args: list[Any] = []
            if project_filter:
                ph = ",".join("?" for _ in project_filter)
                conditions.append(f"project IN ({ph})")
                args.extend(sorted(project_filter))
            for pf in path_filters:
                normalized = pf.replace("\\", "/").strip("/")
                conditions.append("file_path LIKE ?")
                args.append(normalized + "%")
            if not conditions:
                return set()
            where = " OR ".join(conditions)
            removed = [r["id"] for r in conn.execute(f"SELECT id FROM nodes WHERE {where}", args).fetchall()]
            if not removed:
                return set()
            ph = ",".join("?" for _ in removed)
            conn.execute(f"DELETE FROM edges WHERE source_id IN ({ph}) OR target_id IN ({ph})", removed * 2)
            conn.execute(f"DELETE FROM nodes WHERE id IN ({ph})", removed)
            try:
                conn.execute(f"DELETE FROM node_search WHERE id IN ({ph})", removed)
            except sqlite3.OperationalError:
                pass
        return set(removed)

    # ── Memory: records ──────────────────────────────────────────────────

    def append_record(self, collection: str, payload: dict[str, Any], record_id: str = "") -> None:
        nested = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
        with self.pool.transaction() as conn:
            conn.execute(
                """INSERT INTO json_records(collection, record_id, type, session_id, project, created_at, payload_json)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    collection,
                    record_id,
                    str(payload.get("type", "") or ""),
                    str(payload.get("session_id", "") or nested.get("session_id", "") or ""),
                    str(payload.get("project", "") or nested.get("project", "") or ""),
                    str(payload.get("created_at", "") or ""),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def query_records(
        self,
        *,
        collection: str = "",
        record_id: str = "",
        created_after: str = "",
        project: str = "",
        payload_type: str = "",
        session_id: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        sql = "SELECT * FROM json_records WHERE 1=1"
        args: list[Any] = []
        if collection:
            sql += " AND collection=?"; args.append(collection)
        if record_id:
            sql += " AND record_id=?"; args.append(record_id)
        if created_after:
            sql += " AND created_at>=?"; args.append(created_after)
        if project:
            sql += " AND project=?"; args.append(project)
        if payload_type:
            sql += " AND type=?"; args.append(payload_type)
        if session_id:
            sql += " AND session_id=?"; args.append(session_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.pool.connection() as conn:
            rows = conn.execute(sql, args).fetchall()
        records = [
            {
                "collection": str(r["collection"]), "record_id": str(r["record_id"]),
                "type": str(r["type"]), "session_id": str(r["session_id"]),
                "project": str(r["project"]), "created_at": str(r["created_at"]),
                "payload": json.loads(str(r["payload_json"])),
            }
            for r in rows
        ]
        return {"records": records, "count": len(records)}

    # ── Memory: refs ─────────────────────────────────────────────────────

    def upsert_ref(self, ref_path: str, payload: Any) -> None:
        created_at = payload.get("created_at", "") if isinstance(payload, dict) else ""
        with self.pool.transaction() as conn:
            conn.execute(
                """INSERT INTO refs(ref_path, created_at, payload_json)
                   VALUES(?,?,?)
                   ON CONFLICT(ref_path) DO UPDATE SET
                     created_at=excluded.created_at, payload_json=excluded.payload_json""",
                (ref_path, str(created_at), json.dumps(payload, ensure_ascii=False)),
            )

    def query_refs(self, *, ref_path: str = "", limit: int = 50) -> dict[str, Any]:
        sql = "SELECT * FROM refs WHERE 1=1"
        args: list[Any] = []
        if ref_path:
            sql += " AND ref_path=?"; args.append(ref_path)
        sql += " ORDER BY created_at DESC, ref_path DESC LIMIT ?"
        args.append(limit)
        with self.pool.connection() as conn:
            rows = conn.execute(sql, args).fetchall()
        refs = [{"ref_path": str(r["ref_path"]), "created_at": str(r["created_at"]), "payload": json.loads(str(r["payload_json"]))} for r in rows]
        return {"refs": refs, "count": len(refs)}

    # ── Memory: index mirror ─────────────────────────────────────────────

    def upsert_index(self, name: str, payload: Any) -> None:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        with self.pool.transaction() as conn:
            conn.execute(
                """INSERT INTO index_mirror(name, payload_json, updated_at)
                   VALUES(?,?,?)
                   ON CONFLICT(name) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at""",
                (name, json.dumps(payload, ensure_ascii=False), ts),
            )

    def read_index(self, name: str, default: Any = None) -> Any:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT payload_json FROM index_mirror WHERE name=?", (name,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["payload_json"])
        except (json.JSONDecodeError, UnicodeDecodeError):
            return default

    # ── Memory: stats ────────────────────────────────────────────────────

    def memory_stats(self) -> dict[str, Any]:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT collection, COUNT(*) AS cnt FROM json_records GROUP BY collection ORDER BY collection").fetchall()
            ref_count = conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
        return {
            "db_path": str(self.db_path),
            "collections": {str(r["collection"]): int(r["cnt"]) for r in rows},
            "ref_count": int(ref_count),
        }

    # ── Cleanup ──────────────────────────────────────────────────────────

    def close(self) -> None:
        self.pool.close()

    def __enter__(self) -> "UnifiedStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict, parsing metadata_json when present."""
    d = dict(row)
    if "metadata_json" in d:
        try:
            d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = {}
    return d
