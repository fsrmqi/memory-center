from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class GraphNode:
    id: str
    type: str
    name: str
    project: str = ""
    file_path: str = ""
    line: int = 0
    metadata: Dict[str, Any] | None = None


@dataclass(frozen=True)
class GraphEdge:
    id: str
    source_id: str
    target_id: str
    type: str
    confidence: float = 1.0
    metadata: Dict[str, Any] | None = None


class GraphStore:
    """Portable SQLite graph store.

    The graph is deliberately simple: node/edge tables plus an optional FTS5
    search table. This keeps Memory Center local-first and easy to inspect.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "GraphStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
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
                CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project);
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
                CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
                """
            )
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS node_search USING fts5(id UNINDEXED, type, name, project, file_path, content)"
                )
            except sqlite3.OperationalError:
                # Some embedded sqlite builds do not include FTS5. LIKE search remains available.
                pass

    def clear(self) -> None:
        conn = self.connect()
        conn.execute("DELETE FROM edges")
        conn.execute("DELETE FROM nodes")
        try:
            conn.execute("DELETE FROM node_search")
        except sqlite3.OperationalError:
            pass
        conn.commit()

    def rebuild(self, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]) -> None:
        conn = self.connect()
        conn.execute("DELETE FROM edges")
        conn.execute("DELETE FROM nodes")
        try:
            conn.execute("DELETE FROM node_search")
        except sqlite3.OperationalError:
            pass
        for node in nodes:
            metadata_json = json.dumps(node.metadata or {}, ensure_ascii=False)
            conn.execute(
                """INSERT INTO nodes(id, type, name, project, file_path, line, metadata_json)
                   VALUES(?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     type=excluded.type, name=excluded.name, project=excluded.project,
                     file_path=excluded.file_path, line=excluded.line, metadata_json=excluded.metadata_json""",
                (node.id, node.type, node.name, node.project, node.file_path, node.line, metadata_json),
            )
        for edge in edges:
            conn.execute(
                """INSERT INTO edges(id, source_id, target_id, type, confidence, metadata_json)
                   VALUES(?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     source_id=excluded.source_id, target_id=excluded.target_id, type=excluded.type,
                     confidence=excluded.confidence, metadata_json=excluded.metadata_json""",
                (edge.id, edge.source_id, edge.target_id, edge.type, edge.confidence, json.dumps(edge.metadata or {}, ensure_ascii=False)),
            )
        conn.commit()

    def upsert_node(self, node: GraphNode) -> None:
        self.bulk_write([node], [])

    def upsert_edge(self, edge: GraphEdge) -> None:
        self.bulk_write([], [edge])

    def bulk_write(self, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]) -> None:
        with self.connect() as conn:
            for node in nodes:
                metadata_json = json.dumps(node.metadata or {}, ensure_ascii=False)
                conn.execute(
                    """
                    INSERT INTO nodes(id, type, name, project, file_path, line, metadata_json)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      type=excluded.type,
                      name=excluded.name,
                      project=excluded.project,
                      file_path=excluded.file_path,
                      line=excluded.line,
                      metadata_json=excluded.metadata_json
                    """,
                    (node.id, node.type, node.name, node.project, node.file_path, node.line, metadata_json),
                )
            for edge in edges:
                conn.execute(
                    """
                    INSERT INTO edges(id, source_id, target_id, type, confidence, metadata_json)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      source_id=excluded.source_id,
                      target_id=excluded.target_id,
                      type=excluded.type,
                      confidence=excluded.confidence,
                      metadata_json=excluded.metadata_json
                    """,
                    (edge.id, edge.source_id, edge.target_id, edge.type, edge.confidence, json.dumps(edge.metadata or {}, ensure_ascii=False)),
                )

    def rebuild_search_index(self) -> None:
        with self.connect() as conn:
            try:
                conn.execute("DELETE FROM node_search")
                rows = conn.execute("SELECT * FROM nodes").fetchall()
                for row in rows:
                    content = " ".join(
                        [row["id"], row["type"], row["name"], row["project"] or "", row["file_path"] or "", row["metadata_json"] or ""]
                    )
                    conn.execute(
                        "INSERT INTO node_search(id, type, name, project, file_path, content) VALUES(?, ?, ?, ?, ?, ?)",
                        (row["id"], row["type"], row["name"], row["project"], row["file_path"], content),
                    )
            except sqlite3.OperationalError:
                pass

    def node_by_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return _row_node(row) if row else None

    def find_nodes(self, query: str, types: List[str] | None = None, limit: int = 20) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        rows = self._find_nodes_fts(query, types, limit)
        if not rows:
            rows = self._find_nodes_like(query, types, limit)
        return rows

    def _find_nodes_fts(self, query: str, types: List[str] | None, limit: int) -> List[Dict[str, Any]]:
        safe_terms = [_sanitize_fts_term(t) for t in query.replace("-", " ").replace("/", " ").split() if t.strip()]
        safe_terms = [t for t in safe_terms if t]
        if not safe_terms:
            return []
        fts_query = " OR ".join(f'"{t}"' for t in safe_terms[:8])
        sql = """
            SELECT n.*
            FROM node_search s
            JOIN nodes n ON n.id=s.id
            WHERE node_search MATCH ?
        """
        args: List[Any] = [fts_query]
        if types:
            sql += " AND n.type IN (%s)" % ",".join("?" for _ in types)
            args.extend(types)
        sql += " LIMIT ?"
        args.append(limit)
        try:
            with self.connect() as conn:
                rows = conn.execute(sql, args).fetchall()
            return [_row_node(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    def _find_nodes_like(self, query: str, types: List[str] | None, limit: int) -> List[Dict[str, Any]]:
        q = f"%{query.lower()}%"
        sql = "SELECT * FROM nodes WHERE lower(name) LIKE ? OR lower(id) LIKE ? OR lower(file_path) LIKE ? OR lower(metadata_json) LIKE ?"
        args: List[Any] = [q, q, q, q]
        if types:
            sql += " AND type IN (%s)" % ",".join("?" for _ in types)
            args.extend(types)
        sql += " LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_row_node(r) for r in rows]

    def neighbors(self, node_id: str, direction: str = "both", max_depth: int = 2, limit: int = 200) -> List[Dict[str, Any]]:
        seen = {node_id}
        frontier = [node_id]
        results: List[Dict[str, Any]] = []
        conn = self.connect()
        for depth in range(max_depth):
            if not frontier or len(results) >= limit:
                break
            clauses: List[str] = []
            args: List[Any] = []
            frontier_set = set(frontier)
            if direction in {"both", "downstream", "outgoing"}:
                placeholders = ",".join("?" for _ in frontier)
                clauses.append(f"e.source_id IN ({placeholders})")
                args.extend(frontier)
            if direction in {"both", "upstream", "incoming"}:
                placeholders = ",".join("?" for _ in frontier)
                clauses.append(f"e.target_id IN ({placeholders})")
                args.extend(frontier)
            if not clauses:
                placeholders = ",".join("?" for _ in frontier)
                clauses.append(f"e.source_id IN ({placeholders})")
                args.extend(frontier)
            sql = f"""
                SELECT e.*, ns.type AS source_type, ns.name AS source_name, ns.project AS source_project, ns.file_path AS source_file,
                       nt.type AS target_type, nt.name AS target_name, nt.project AS target_project, nt.file_path AS target_file
                FROM edges e
                LEFT JOIN nodes ns ON ns.id=e.source_id
                LEFT JOIN nodes nt ON nt.id=e.target_id
                WHERE {' OR '.join(clauses)}
                LIMIT ?
            """
            rows = conn.execute(sql, [*args, limit - len(results)]).fetchall()
            next_frontier: List[str] = []
            for row in rows:
                rec = _row_edge(row)
                rec["depth"] = depth + 1
                results.append(rec)
                next_id = row["target_id"] if row["source_id"] in frontier_set else row["source_id"]
                if next_id not in seen:
                    seen.add(next_id)
                    next_frontier.append(next_id)
            frontier = next_frontier
        return results[:limit]

    def counts(self) -> Dict[str, int]:
        with self.connect() as conn:
            nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return {"nodes": nodes, "edges": edges}

    def all_nodes(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM nodes").fetchall()
        return [_row_node(row) for row in rows]


def node_id(kind: str, *parts: str) -> str:
    body = ":".join(str(p).strip().replace(" ", "_") for p in parts if str(p).strip())
    return f"{kind}:{body}"


def edge_id(edge_type: str, source_id: str, target_id: str) -> str:
    return f"{edge_type}:{source_id}->{target_id}"


def _sanitize_fts_term(term: str) -> str:
    return re.sub(r"[^\w一-鿿]", "", term)


def _loads_json(value: str) -> Dict[str, Any]:
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}


def _row_node(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "project": row["project"],
        "file_path": row["file_path"],
        "line": row["line"],
        "metadata": _loads_json(row["metadata_json"]),
    }


def _row_edge(row: sqlite3.Row) -> Dict[str, Any]:
    metadata = _loads_json(row["metadata_json"])
    return {
        "id": row["id"],
        "type": row["type"],
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "confidence": row["confidence"],
        "metadata": metadata,
        "evidence": metadata.get("evidence", metadata),
        "source": {"type": row["source_type"], "name": row["source_name"], "project": row["source_project"], "file_path": row["source_file"]},
        "target": {"type": row["target_type"], "name": row["target_name"], "project": row["target_project"], "file_path": row["target_file"]},
    }
