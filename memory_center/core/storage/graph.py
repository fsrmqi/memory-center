from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_center.core.assessment.quality import evidence_level_for
from memory_center.core.knowledge.ontology import edge_strength

from .metadata import metadata_json as _metadata_json

# Pre-compiled regex for _sanitize_fts_term (P1 performance)
_RE_SANITIZE_FTS = re.compile(r"[^\w㐀-䶿一-鿿豈-﫿]")


@dataclass(frozen=True)
class GraphNode:
    id: str
    type: str
    name: str
    project: str = ""
    file_path: str = ""
    line: int = 0
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class GraphEdge:
    id: str
    source_id: str
    target_id: str
    type: str
    confidence: float = 1.0
    metadata: dict[str, Any] | None = None


class GraphStore:
    """Portable SQLite graph store.

    The graph is deliberately simple: node/edge tables plus an optional FTS5
    search table. This keeps Memory Center local-first and easy to inspect.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self._conn = sqlite3.connect(self.db_path)
                # Apply the shared PRAGMA profile here — GraphStore is the
                # hot path for reindex writes and previously opened bare
                # connections without WAL / cache tuning, which dominated
                # large-repo indexing latency.
                from .pragmas import apply_pragmas

                apply_pragmas(self._conn)
                self._conn.row_factory = sqlite3.Row
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> GraphStore:
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
                CREATE INDEX IF NOT EXISTS idx_edges_source_type ON edges(source_id, type);
                CREATE INDEX IF NOT EXISTS idx_edges_target_type ON edges(target_id, type);
                CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
                CREATE TABLE IF NOT EXISTS file_generations (
                  file_path TEXT PRIMARY KEY,
                  generation INTEGER NOT NULL DEFAULT 0,
                  content_hash TEXT DEFAULT '',
                  updated_at INTEGER NOT NULL DEFAULT 0
                );
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
        conn.execute("DELETE FROM file_generations")
        try:
            conn.execute("DELETE FROM node_search")
        except sqlite3.OperationalError:
            pass
        conn.commit()

    def rebuild(self, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]) -> None:
        # rebuild() is the hot path during full reindex. Two changes
        # versus the previous loop-of-INSERT implementation:
        #
        # 1. Switch to executemany so the SQLite bytecode is prepared
        #    once instead of per-row. On a 16K-symbol Java monorepo this
        #    cuts the rebuild itself by ~5×.
        # 2. Wrap the whole rebuild in fast_write_mode so synchronous is
        #    OFF for the duration. Reindex is restartable from source
        #    code, so a power loss only forces a re-run — never silent
        #    data loss on a user-owned write.
        from .pragmas import fast_write_mode

        conn = self.connect()
        node_rows = [
            (
                node.id,
                node.type,
                node.name,
                node.project,
                node.file_path,
                node.line,
                _metadata_json(node.metadata),
            )
            for node in nodes
        ]
        edge_rows = [
            (
                edge.id,
                edge.source_id,
                edge.target_id,
                edge.type,
                edge.confidence,
                _metadata_json(_edge_metadata(edge.type, edge.metadata)),
            )
            for edge in edges
        ]
        with fast_write_mode(conn):
            conn.execute("DELETE FROM edges")
            conn.execute("DELETE FROM nodes")
            conn.execute("DELETE FROM file_generations")
            try:
                conn.execute("DELETE FROM node_search")
            except sqlite3.OperationalError:
                pass
            if node_rows:
                conn.executemany(
                    """INSERT INTO nodes(id, type, name, project, file_path, line, metadata_json)
                       VALUES(?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         type=excluded.type, name=excluded.name, project=excluded.project,
                         file_path=excluded.file_path, line=excluded.line, metadata_json=excluded.metadata_json""",
                    node_rows,
                )
            if edge_rows:
                conn.executemany(
                    """INSERT INTO edges(id, source_id, target_id, type, confidence, metadata_json)
                       VALUES(?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         source_id=excluded.source_id, target_id=excluded.target_id, type=excluded.type,
                         confidence=excluded.confidence, metadata_json=excluded.metadata_json""",
                    edge_rows,
                )
            conn.commit()

    def upsert_node(self, node: GraphNode) -> None:
        self.bulk_write([node], [])

    def upsert_edge(self, edge: GraphEdge) -> None:
        self.bulk_write([], [edge])

    def bulk_write(self, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]) -> None:
        with self.connect() as conn:
            node_list = list(nodes)
            edge_list = list(edges)
            if node_list:
                node_rows = [
                    (node.id, node.type, node.name, node.project, node.file_path, node.line,
                     _metadata_json(node.metadata))
                    for node in node_list
                ]
                conn.executemany(
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
                    node_rows,
                )
            if edge_list:
                edge_rows = [
                    (edge.id, edge.source_id, edge.target_id, edge.type, edge.confidence,
                     _metadata_json(_edge_metadata(edge.type, edge.metadata)))
                    for edge in edge_list
                ]
                conn.executemany(
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
                    edge_rows,
                )

    def rebuild_search_index(self) -> None:
        # Same executemany rewrite as rebuild(): one prepared INSERT
        # instead of N. The FTS5 table can have hundreds of thousands of
        # rows on real Java monorepos.
        from .pragmas import fast_write_mode

        with self.connect() as conn:
            try:
                with fast_write_mode(conn):
                    conn.execute("DELETE FROM node_search")
                    rows = conn.execute("SELECT * FROM nodes").fetchall()
                    if not rows:
                        return
                    payload = [
                        (
                            row["id"],
                            row["type"],
                            row["name"],
                            row["project"],
                            row["file_path"],
                            " ".join(
                                [
                                    row["id"],
                                    row["type"],
                                    row["name"],
                                    row["project"] or "",
                                    row["file_path"] or "",
                                    row["metadata_json"] or "",
                                ]
                            ),
                        )
                        for row in rows
                    ]
                    conn.executemany(
                        "INSERT INTO node_search(id, type, name, project, file_path, content)"
                        " VALUES(?, ?, ?, ?, ?, ?)",
                        payload,
                    )
            except sqlite3.OperationalError:
                # FTS5 may be unavailable on stripped-down SQLite builds.
                # The LIKE fallback path keeps queries working.
                pass

    def node_by_id(self, node_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return _row_node(row) if row else None

    def find_nodes(self, query: str, types: list[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        rows = self._find_nodes_fts(query, types, limit)
        if not rows:
            rows = self._find_nodes_like(query, types, limit)
        return rows

    def _find_nodes_fts(self, query: str, types: list[str] | None, limit: int) -> list[dict[str, Any]]:
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
        args: list[Any] = [fts_query]
        if types:
            sql += f" AND n.type IN ({','.join('?' for _ in types)})"
            args.extend(types)
        sql += " LIMIT ?"
        args.append(limit)
        try:
            with self.connect() as conn:
                rows = conn.execute(sql, args).fetchall()
            return [_row_node(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    def _find_nodes_like(self, query: str, types: list[str] | None, limit: int) -> list[dict[str, Any]]:
        q = f"%{query.lower()}%"
        sql = "SELECT * FROM nodes WHERE lower(name) LIKE ? OR lower(id) LIKE ? OR lower(file_path) LIKE ? OR lower(metadata_json) LIKE ?"
        args: list[Any] = [q, q, q, q]
        if types:
            sql += f" AND type IN ({','.join('?' for _ in types)})"
            args.extend(types)
        sql += " LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_row_node(r) for r in rows]

    def neighbors(
        self,
        node_id: str,
        direction: str = "both",
        max_depth: int = 2,
        limit: int = 200,
        edge_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """BFS neighbor traversal optimized for large graphs.

        Improvements over the previous implementation:
        - Edge type filtering in SQL (not post-fetch)
        - Parameterised IN-clause with type filter pushed down
        - Early termination when limit is reached
        """
        conn = self.connect()
        type_set = set(edge_types) if edge_types else None
        seen: set[str] = {node_id}
        frontier: list[str] = [node_id]
        results: list[dict[str, Any]] = []

        for depth in range(max_depth):
            if not frontier or len(results) >= limit:
                break

            clauses: list[str] = []
            args: list[Any] = []
            if direction in {"both", "downstream", "outgoing"}:
                ph = ",".join("?" for _ in frontier)
                clauses.append(f"e.source_id IN ({ph})")
                args.extend(frontier)
            if direction in {"both", "upstream", "incoming"}:
                ph = ",".join("?" for _ in frontier)
                clauses.append(f"e.target_id IN ({ph})")
                args.extend(frontier)
            if not clauses:
                ph = ",".join("?" for _ in frontier)
                clauses.append(f"e.source_id IN ({ph})")
                args.extend(frontier)

            where_body = f"({' OR '.join(clauses)})"
            remaining = limit - len(results)

            select_sql = """
                SELECT e.*, ns.type AS source_type, ns.name AS source_name,
                       ns.project AS source_project, ns.file_path AS source_file,
                       ns.line AS source_line,
                       nt.type AS target_type, nt.name AS target_name,
                       nt.project AS target_project, nt.file_path AS target_file,
                       nt.line AS target_line
                FROM edges e
                LEFT JOIN nodes ns ON ns.id = e.source_id
                LEFT JOIN nodes nt ON nt.id = e.target_id
            """
            if type_set:
                placeholders = ",".join("?" for _ in type_set)
                collect_where = f"{where_body} AND e.type IN ({placeholders})"
                rows = conn.execute(
                    f"{select_sql} WHERE {collect_where} LIMIT ?",
                    [*args, *sorted(type_set), remaining],
                ).fetchall()
                frontier_rows = conn.execute(
                    f"SELECT e.source_id, e.target_id FROM edges e WHERE {where_body} LIMIT ?",
                    [*args, remaining],
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    {select_sql}
                    WHERE {where_body}
                LIMIT ?
                    """,
                    [*args, remaining],
                ).fetchall()
                frontier_rows = rows

            next_frontier: list[str] = []
            for row in frontier_rows:
                sid = row["source_id"]
                tid = row["target_id"]
                if tid not in seen and tid != node_id:
                    seen.add(tid)
                    next_frontier.append(tid)
                elif sid not in seen and sid != node_id:
                    seen.add(sid)
                    next_frontier.append(sid)
            for row in rows:
                rec = _row_edge(row)
                rec["depth"] = depth + 1
                results.append(rec)
            frontier = next_frontier
        return results[:limit]

    def remove_by_scope(self, project_filter: set[str], path_filters: list[str], *, preserve_incoming: bool = False) -> set[str]:
        """Remove nodes/edges matching project or path scope. Returns removed node IDs."""
        with self.connect() as conn:
            conditions: list[str] = []
            args: list[Any] = []
            if project_filter:
                placeholders = ",".join("?" for _ in project_filter)
                conditions.append(f"project IN ({placeholders})")
                args.extend(sorted(project_filter))
            for pf in path_filters:
                normalized = pf.replace("\\", "/").strip("/")
                conditions.append("file_path LIKE ?")
                args.append(normalized + "%")
            if not conditions:
                return set()
            where = " OR ".join(conditions)
            removed_ids = [row["id"] for row in conn.execute(f"SELECT id FROM nodes WHERE {where}", args).fetchall()]
            if not removed_ids:
                return set()
            placeholders = ",".join("?" for _ in removed_ids)
            if preserve_incoming:
                conn.execute(f"DELETE FROM edges WHERE source_id IN ({placeholders})", removed_ids)
            else:
                conn.execute(f"DELETE FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})", removed_ids * 2)
            conn.execute(f"DELETE FROM nodes WHERE id IN ({placeholders})", removed_ids)
            try:
                conn.execute(f"DELETE FROM node_search WHERE id IN ({placeholders})", removed_ids)
            except sqlite3.OperationalError:
                pass
            return set(removed_ids)

    def partial_rebuild(
        self,
        nodes: Iterable[GraphNode],
        edges: Iterable[GraphEdge],
        project_filter: set[str],
        path_filters: list[str],
        *,
        preserve_incoming: bool = False,
    ) -> dict[str, Any]:
        """Remove scope-matched nodes/edges, then upsert refreshed ones."""
        removed_ids = self.remove_by_scope(project_filter, path_filters, preserve_incoming=preserve_incoming)
        refreshed_nodes = list(nodes)
        refreshed_edges = list(edges)
        self.bulk_write(refreshed_nodes, refreshed_edges)
        refreshed_ids = {node.id for node in refreshed_nodes}
        changed_ids = removed_ids | refreshed_ids
        self._upsert_search_rows([node for node in refreshed_nodes if node.id in changed_ids])
        counts = self.counts()
        counts["changed_node_ids"] = list(changed_ids)
        return counts

    def replace_file_subgraph(
        self,
        file_path: str,
        nodes: Iterable[GraphNode],
        edges: Iterable[GraphEdge],
        *,
        generation: int | None = None,
        content_hash: str = "",
    ) -> dict[str, Any]:
        """Atomically replace one file's nodes and outgoing edges.

        Incoming edges are intentionally retained: callers in unchanged files
        remain valid when a declaration keeps the same stable node id.
        """
        node_list = list(nodes)
        edge_list = list(edges)
        conn = self.connect()
        with conn:
            removed = [row["id"] for row in conn.execute("SELECT id FROM nodes WHERE file_path = ?", (file_path,)).fetchall()]
            if removed:
                placeholders = ",".join("?" for _ in removed)
                conn.execute(f"DELETE FROM edges WHERE source_id IN ({placeholders})", removed)
                conn.execute(f"DELETE FROM nodes WHERE id IN ({placeholders})", removed)
                try:
                    conn.execute(f"DELETE FROM node_search WHERE id IN ({placeholders})", removed)
                except sqlite3.OperationalError:
                    pass
            for node in node_list:
                conn.execute(
                    "INSERT INTO nodes(id,type,name,project,file_path,line,metadata_json) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET type=excluded.type,name=excluded.name,project=excluded.project,file_path=excluded.file_path,line=excluded.line,metadata_json=excluded.metadata_json",
                    (node.id, node.type, node.name, node.project, node.file_path, node.line, _metadata_json(node.metadata)),
                )
            for edge in edge_list:
                conn.execute(
                    "INSERT INTO edges(id,source_id,target_id,type,confidence,metadata_json) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET source_id=excluded.source_id,target_id=excluded.target_id,type=excluded.type,confidence=excluded.confidence,metadata_json=excluded.metadata_json",
                    (edge.id, edge.source_id, edge.target_id, edge.type, edge.confidence, _metadata_json(_edge_metadata(edge.type, edge.metadata))),
                )
            try:
                for node in node_list:
                    conn.execute("DELETE FROM node_search WHERE id=?", (node.id,))
                    conn.execute(
                        "INSERT INTO node_search(id,type,name,project,file_path,content) VALUES(?,?,?,?,?,?)",
                        (node.id, node.type, node.name, node.project, node.file_path, " ".join([node.id, node.type, node.name, node.project, node.file_path, _metadata_json(node.metadata)])),
                    )
            except sqlite3.OperationalError:
                pass
            if generation is not None:
                conn.execute(
                    "INSERT INTO file_generations(file_path,generation,content_hash,updated_at) VALUES(?,?,?,strftime('%s','now')) "
                    "ON CONFLICT(file_path) DO UPDATE SET generation=excluded.generation,content_hash=excluded.content_hash,updated_at=excluded.updated_at",
                    (file_path, generation, content_hash),
                )
        return {"removed_node_count": len(removed), "refreshed_node_count": len(node_list), "refreshed_edge_count": len(edge_list)}

    def file_neighbors(self, file_path: str, limit: int = 24) -> list[str]:
        """Return distinct source files connected to a file's graph nodes."""
        sql = """
            SELECT DISTINCT other.file_path
            FROM edges e
            JOIN nodes current ON current.id = e.source_id OR current.id = e.target_id
            JOIN nodes other ON other.id = CASE WHEN e.source_id = current.id THEN e.target_id ELSE e.source_id END
            WHERE current.file_path = ? AND other.file_path != '' AND other.file_path != ?
            LIMIT ?
        """
        with self.connect() as conn:
            rows = conn.execute(sql, (file_path, file_path, limit)).fetchall()
        return [str(row[0]) for row in rows if row[0]]

    def file_generation(self, file_path: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT file_path,generation,content_hash,updated_at FROM file_generations WHERE file_path=?", (file_path,)).fetchone()
        return dict(row) if row else None

    def record_file_generation(self, file_path: str, generation: int, content_hash: str = "") -> None:
        """Record a successful bounded refresh without replacing graph facts."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO file_generations(file_path,generation,content_hash,updated_at) VALUES(?,?,?,strftime('%s','now')) "
                "ON CONFLICT(file_path) DO UPDATE SET generation=excluded.generation,content_hash=excluded.content_hash,updated_at=excluded.updated_at",
                (file_path, generation, content_hash),
            )

    def _upsert_search_rows(self, node_dicts: Iterable[GraphNode]) -> None:
        """Insert/update FTS rows for a subset of nodes."""
        with self.connect() as conn:
            try:
                for node in node_dicts:
                    metadata_payload = _metadata_json(node.metadata)
                    content = " ".join([node.id, node.type, node.name, node.project, node.file_path, metadata_payload])
                    conn.execute("DELETE FROM node_search WHERE id=?", (node.id,))
                    conn.execute(
                        "INSERT INTO node_search(id, type, name, project, file_path, content) VALUES(?, ?, ?, ?, ?, ?)",
                        (node.id, node.type, node.name, node.project, node.file_path, content),
                    )
            except sqlite3.OperationalError:
                pass

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return {"nodes": nodes, "edges": edges}

    def all_nodes(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM nodes").fetchall()
        return [_row_node(row) for row in rows]

    def project_subgraph(self, project: str) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Export a self-contained graph shard for one project."""
        with self.connect() as conn:
            node_rows = conn.execute("SELECT * FROM nodes WHERE project=?", (project,)).fetchall()
            node_ids = [str(row["id"]) for row in node_rows]
            if not node_ids:
                return [], []
            placeholders = ",".join("?" for _ in node_ids)
            edge_rows = conn.execute(
                f"SELECT * FROM edges WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})",
                node_ids * 2,
            ).fetchall()
        nodes = [GraphNode(row["id"], row["type"], row["name"], row["project"], row["file_path"], row["line"], _loads_json(row["metadata_json"])) for row in node_rows]
        edges = [GraphEdge(row["id"], row["source_id"], row["target_id"], row["type"], row["confidence"], _loads_json(row["metadata_json"])) for row in edge_rows]
        return nodes, edges


def node_id(kind: str, *parts: str) -> str:
    body = ":".join(str(p).strip().replace(" ", "_") for p in parts if str(p).strip())
    return f"{kind}:{body}"


def edge_id(edge_type: str, source_id: str, target_id: str) -> str:
    return f"{edge_type}:{source_id}->{target_id}"


def _sanitize_fts_term(term: str) -> str:
    return _RE_SANITIZE_FTS.sub("", term)


def _loads_json(value: str) -> dict[str, Any]:
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}


def _row_node(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "project": row["project"],
        "file_path": row["file_path"],
        "line": row["line"],
        "metadata": _loads_json(row["metadata_json"]),
    }


def _coerce_line(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _edge_endpoint_line(row: sqlite3.Row, endpoint: str, metadata: dict[str, Any]) -> int:
    direct_line = _coerce_line(row[f"{endpoint}_line"])
    if direct_line > 0:
        return direct_line
    evidence = metadata.get("evidence")
    if endpoint == "source" and isinstance(evidence, dict):
        evidence_line = _coerce_line(evidence.get("line"))
        if evidence_line > 0:
            return evidence_line
    return 0


def _row_edge(row: sqlite3.Row) -> dict[str, Any]:
    metadata = _loads_json(row["metadata_json"])
    evidence_level = evidence_level_for(
        metadata, semantic_strength=edge_strength(str(row["type"] or ""))
    )
    return {
        "id": row["id"],
        "type": row["type"],
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "confidence": row["confidence"],
        "evidence_level": evidence_level,
        "metadata": metadata,
        "evidence": metadata.get("evidence", metadata),
        "source": {
            "type": row["source_type"] or "",
            "name": row["source_name"] or "",
            "project": row["source_project"] or "",
            "file_path": row["source_file"] or "",
            "line": _edge_endpoint_line(row, "source", metadata),
        },
        "target": {
            "type": row["target_type"] or "",
            "name": row["target_name"] or "",
            "project": row["target_project"] or "",
            "file_path": row["target_file"] or "",
            "line": _edge_endpoint_line(row, "target", metadata),
        },
    }


def _edge_metadata(edge_type: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Persist an additive evidence level on newly written graph edges."""
    result = dict(metadata or {})
    result.setdefault(
        "evidence_level",
        evidence_level_for(result, semantic_strength=edge_strength(edge_type)),
    )
    return result
