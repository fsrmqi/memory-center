from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_center.core.assessment.quality import evidence_level_for
from memory_center.core.knowledge.ontology import edge_strength

from .metadata import metadata_json as _metadata_json

# Pre-compiled regex for _sanitize_fts_term (P1 performance)
_RE_SANITIZE_FTS = re.compile(r"[^\w㐀-䶿一-鿿豈-﫿]")

# Impact propagation is deliberately separate from edge confidence. Confidence
# says how trustworthy one extracted relation is; this table says how strongly
# that relation should carry a code-change impact to its next endpoint.
IMPACT_EDGE_WEIGHTS: dict[str, float] = {
    "CALLS_METHOD": 0.98,
    "CALLS_SERVICE": 1.0,
    "IMPLEMENTS_FEIGN": 0.96,
    "DISPATCHES_TO": 0.9,
    "EXPOSES_ENDPOINT": 0.96,
    "HANDLES_ENDPOINT": 0.94,
    "CONSUMES_TOPIC": 0.96,
    "PRODUCES_TOPIC": 0.96,
    "ROUTES_TO": 0.95,
    "DATA_FLOWS_TO": 0.90,
    "CONFIG_PROPAGATES": 0.86,
    "READS_CONFIG": 0.82,
    "USES_DATA_RESOURCE": 0.82,
    "INJECTS_BEAN": 0.82,
    "INJECTS": 0.82,
    "READS_FIELD": 0.78,
    "IMPORTS": 0.62,
    "IMPLEMENTS_FLOW_STEP": 0.75,
    "TRANSITIVELY_CALLS": 0.68,
    "DECLARES": 0.45,
    "DECLARES_CONFIG": 0.45,
    "CONTAINS": 0.35,
}
IMPACT_DEFAULT_EDGE_WEIGHT = 0.55
IMPACT_EVIDENCE_FACTORS = {
    "VERIFIED": 1.0,
    "EXTRACTED": 1.0,
    "INFERRED": 0.86,
    "AMBIGUOUS": 0.65,
}


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


class _GraphOperations:
    """`RuntimeStore` 的图索引实现组件，不作为独立存储入口暴露。

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
                # Apply the shared PRAGMA profile here — RuntimeStore is the
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

    def __enter__(self) -> _GraphOperations:
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
                CREATE TABLE IF NOT EXISTS cochange_priors (
                  seed_ref TEXT NOT NULL,
                  candidate_ref TEXT NOT NULL,
                  support INTEGER NOT NULL DEFAULT 0,
                  score REAL NOT NULL DEFAULT 0,
                  trained_at TEXT DEFAULT '',
                  PRIMARY KEY(seed_ref, candidate_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_cochange_priors_seed_score
                  ON cochange_priors(seed_ref, score DESC, support DESC);
                CREATE INDEX IF NOT EXISTS idx_nodes_type_name ON nodes(type, name);
                CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project);
                CREATE INDEX IF NOT EXISTS idx_nodes_file_path ON nodes(file_path);
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

    def rebuild(
        self,
        nodes: Iterable[GraphNode],
        edges: Iterable[GraphEdge],
        *,
        clear_search: bool = True,
    ) -> None:
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
            if clear_search:
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

    def rebuild_search_index(self) -> dict[str, int | float | str]:
        """Rebuild FTS in SQLite without materializing all graph rows in Python."""
        from .pragmas import fast_write_mode

        started = time.perf_counter()
        with self.connect() as conn:
            try:
                with fast_write_mode(conn):
                    conn.execute("DELETE FROM node_search")
                    conn.execute(
                        """
                        INSERT INTO node_search(id, type, name, project, file_path, content)
                        SELECT id, type, name, project, file_path,
                               id || ' ' || type || ' ' || name || ' ' ||
                               COALESCE(project, '') || ' ' || COALESCE(file_path, '') || ' ' ||
                               COALESCE(metadata_json, '')
                        FROM nodes
                        """
                    )
                    indexed = int(conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0])
                    # ``fast_write_mode`` restores synchronous on exit; SQLite
                    # forbids that PRAGMA transition while this FTS write
                    # transaction is still open.
                    conn.commit()
                    return {
                        "fts_sync_mode": "full_sql",
                        "fts_changed_nodes": indexed,
                        "fts_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    }
            except sqlite3.OperationalError:
                # FTS5 may be unavailable on stripped-down SQLite builds.
                # The LIKE fallback path keeps queries working.
                return {
                    "fts_sync_mode": "unavailable",
                    "fts_changed_nodes": 0,
                    "fts_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                }

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
        # FTS5 bm25 values are lower for better matches. Ordering here keeps
        # the first graph candidates stable and relevant before hybrid fusion.
        sql += " ORDER BY bm25(node_search), n.name, n.id LIMIT ?"
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

    def weighted_impact_paths(
        self,
        node_id: str,
        *,
        direction: str = "upstream",
        max_depth: int = 3,
        limit: int = 300,
        minimum_score: float = 0.05,
        edge_weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Return bounded best-path impact records without materializing the graph.

        Each frontier expansion uses indexed SQLite lookups. Cycles and dense
        graphs remain bounded because only the highest-scoring path per endpoint
        is retained and expanded at the next depth.
        """
        if not node_id or max_depth <= 0 or limit <= 0:
            return []
        normalized = {"incoming": "upstream", "outgoing": "downstream"}.get(direction, direction)
        directions = ("upstream", "downstream") if normalized == "both" else (normalized,)
        if not set(directions).issubset({"upstream", "downstream"}):
            directions = ("upstream",)

        weights = {**IMPACT_EDGE_WEIGHTS, **(edge_weights or {})}
        best: dict[str, dict[str, Any]] = {
            node_id: {"score": 1.0, "node_path": [node_id], "edge_path": []}
        }
        frontier = [node_id]
        output_by_node: dict[str, dict[str, Any]] = {}
        alternative_by_relation: dict[tuple[str, str], dict[str, Any]] = {}
        truncated = False

        with self.connect() as conn:
            for depth in range(1, min(int(max_depth), 8) + 1):
                if not frontier or len(output_by_node) >= limit:
                    truncated = len(output_by_node) >= limit
                    break
                next_candidates: dict[str, dict[str, Any]] = {}
                for start in range(0, len(frontier), 400):
                    batch = frontier[start : start + 400]
                    placeholders = ",".join("?" for _ in batch)
                    for traversal_direction in directions:
                        source_column, target_column = (
                            ("target_id", "source_id")
                            if traversal_direction == "upstream"
                            else ("source_id", "target_id")
                        )
                        rows = conn.execute(
                            f"""
                            SELECT e.*, ns.type AS source_type, ns.name AS source_name,
                                   ns.project AS source_project, ns.file_path AS source_file,
                                   ns.line AS source_line, nt.type AS target_type,
                                   nt.name AS target_name, nt.project AS target_project,
                                   nt.file_path AS target_file, nt.line AS target_line,
                                   e.{source_column} AS frontier_id,
                                   e.{target_column} AS neighbor_id
                            FROM edges e
                            LEFT JOIN nodes ns ON ns.id=e.source_id
                            LEFT JOIN nodes nt ON nt.id=e.target_id
                            WHERE e.{source_column} IN ({placeholders})
                            ORDER BY e.{source_column}, e.id
                            LIMIT ?
                            """,
                            [*batch, min(4096, max(256, limit * 12))],
                        ).fetchall()
                        for row in rows:
                            current_id = str(row["frontier_id"] or "")
                            neighbor_id = str(row["neighbor_id"] or "")
                            if not neighbor_id or neighbor_id == node_id:
                                continue
                            parent = best.get(current_id)
                            if not parent:
                                continue
                            edge = _row_edge(row)
                            edge_weight = min(1.0, max(0.0, float(weights.get(edge["type"], IMPACT_DEFAULT_EDGE_WEIGHT))))
                            edge_confidence = min(1.0, max(0.0, float(edge.get("confidence", 0.0) or 0.0)))
                            evidence_factor = IMPACT_EVIDENCE_FACTORS.get(str(edge.get("evidence_level", "AMBIGUOUS")), 0.65)
                            freshness_status = str((edge.get("metadata", {}) or {}).get("freshness_status", "fresh")).lower()
                            freshness_factor = 0.70 if freshness_status in {"stale", "outdated"} else 0.85 if freshness_status == "unknown" else 1.0
                            depth_factor = 1.0 if depth == 1 else 0.90
                            score = float(parent["score"]) * edge_weight * edge_confidence * evidence_factor * freshness_factor * depth_factor
                            if score < max(0.0, float(minimum_score)):
                                continue
                            candidate_path = [*parent["node_path"], neighbor_id]
                            candidate_edges = [*parent["edge_path"], edge["id"]]
                            record = {
                                **edge,
                                "depth": depth,
                                "impact_score": round(score, 6),
                                "best_path": {
                                    "node_ids": candidate_path,
                                    "edge_ids": candidate_edges,
                                    "hop_count": depth,
                                },
                                "score_breakdown": {
                                    "relation_weight": round(edge_weight, 4),
                                    "edge_confidence": round(edge_confidence, 4),
                                    "evidence_factor": round(evidence_factor, 4),
                                    "freshness_factor": round(freshness_factor, 4),
                                    "depth_factor": round(depth_factor, 4),
                                },
                            }
                            previous = next_candidates.get(neighbor_id) or best.get(neighbor_id)
                            if previous and (
                                score < float(previous["score"])
                                or (score == float(previous["score"]) and candidate_path >= previous["node_path"])
                            ):
                                previous_type = str((previous.get("record", {}) or {}).get("type", ""))
                                edge_type = str(edge.get("type", ""))
                                if edge_type and edge_type != previous_type:
                                    alternative_by_relation[(neighbor_id, edge_type)] = {
                                        **record,
                                        "alternative_path_evidence": True,
                                        "propagated": False,
                                    }
                                continue
                            pending = next_candidates.get(neighbor_id)
                            if pending:
                                pending_record = dict(pending["record"])
                                pending_type = str(pending_record.get("type", ""))
                                if pending_type and pending_type != str(edge.get("type", "")):
                                    alternative_by_relation[(neighbor_id, pending_type)] = {
                                        **pending_record,
                                        "alternative_path_evidence": True,
                                        "propagated": False,
                                    }
                            next_candidates[neighbor_id] = {
                                "score": score,
                                "node_path": candidate_path,
                                "edge_path": candidate_edges,
                                "record": record,
                            }
                frontier = []
                for neighbor_id, candidate in sorted(
                    next_candidates.items(), key=lambda item: (-float(item[1]["score"]), item[0])
                ):
                    previous = best.get(neighbor_id)
                    if previous and float(previous["score"]) >= float(candidate["score"]):
                        continue
                    best[neighbor_id] = candidate
                    output_by_node[neighbor_id] = candidate["record"]
                    frontier.append(neighbor_id)
                    if len(output_by_node) >= limit:
                        truncated = True
                        break

        ordered = sorted(
            [*output_by_node.values(), *alternative_by_relation.values()],
            key=lambda item: (-float(item.get("impact_score", 0.0)), int(item.get("depth", 0)), str(item.get("id", ""))),
        )[:limit]
        if ordered:
            ordered[0]["traversal"] = {
                "algorithm": "bounded_weighted_best_path_v1",
                "truncated": truncated,
                "max_depth": min(int(max_depth), 8),
                "limit": limit,
                "minimum_score": minimum_score,
            }
        return ordered

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
                # build_graph_store expands directory filters against the
                # file index before reaching this low-level operation. The
                # graph therefore receives canonical file paths and can use
                # an index-only exact lookup instead of a LIKE table scan.
                conditions.append("file_path = ?")
                args.append(normalized)
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
        fts_metrics = self._upsert_search_rows([node for node in refreshed_nodes if node.id in changed_ids])
        counts = self.counts()
        counts["changed_node_ids"] = list(changed_ids)
        counts.update(fts_metrics)
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
        """Return deterministic weighted file neighbors."""
        return [row["file_path"] for row in self.ranked_file_neighbors(file_path, limit=limit)]

    def ranked_file_neighbors(self, file_path: str, *, limit: int = 24) -> list[dict[str, Any]]:
        """Rank a bounded connected-edge projection without scanning a large file subgraph."""
        bounded_limit = min(max(1, int(limit)), 100)
        candidate_limit = min(1600, max(128, bounded_limit * 16))
        sql = """
            SELECT other.file_path, e.type AS edge_type, e.confidence
            FROM edges e
            JOIN nodes current ON current.id = e.source_id OR current.id = e.target_id
            JOIN nodes other ON other.id = CASE
                WHEN e.source_id = current.id THEN e.target_id ELSE e.source_id END
            WHERE current.file_path = ? AND other.file_path != '' AND other.file_path != ?
            LIMIT ?
        """
        with self.connect() as conn:
            rows = conn.execute(sql, (file_path, file_path, candidate_limit)).fetchall()
        ranked: dict[str, dict[str, Any]] = {}
        for row in rows:
            path = str(row["file_path"] or "")
            if not path:
                continue
            edge_type = str(row["edge_type"] or "")
            score = float(row["confidence"] or 0.0) * float(
                IMPACT_EDGE_WEIGHTS.get(edge_type, IMPACT_DEFAULT_EDGE_WEIGHT)
            )
            item = ranked.setdefault(
                path,
                {
                    "file_path": path,
                    "evidence_count": 0,
                    "strongest_score": 0.0,
                    "aggregate_score": 0.0,
                    "relation_types": set(),
                },
            )
            item["evidence_count"] += 1
            item["strongest_score"] = max(float(item["strongest_score"]), score)
            item["aggregate_score"] += score
            item["relation_types"].add(edge_type)
        if ranked:
            seed_ref = _path_ref(file_path)
            candidate_by_ref = {_path_ref(path): path for path in ranked}
            placeholders = ",".join("?" for _ in candidate_by_ref)
            with self.connect() as conn:
                prior_rows = conn.execute(
                    f"SELECT candidate_ref, support, score FROM cochange_priors WHERE seed_ref=? AND candidate_ref IN ({placeholders})",
                    [seed_ref, *candidate_by_ref],
                ).fetchall()
            for prior in prior_rows:
                path = candidate_by_ref.get(str(prior["candidate_ref"] or ""))
                if path and path in ranked:
                    ranked[path]["cochange_support"] = int(prior["support"] or 0)
                    ranked[path]["cochange_score"] = float(prior["score"] or 0.0)
        ordered = sorted(
            ranked.values(),
            key=lambda item: (
                -(float(item["strongest_score"]) + 0.12 * float(item.get("cochange_score", 0.0))),
                -int(item["evidence_count"]),
                -float(item["aggregate_score"]),
                str(item["file_path"]),
            ),
        )[:bounded_limit]
        for item in ordered:
            item["strongest_score"] = round(float(item["strongest_score"]), 6)
            item["aggregate_score"] = round(float(item["aggregate_score"]), 6)
            item["relation_types"] = sorted(item["relation_types"])
        return ordered

    def replace_cochange_priors(self, rows: list[dict[str, Any]], *, trained_at: str) -> int:
        """Atomically replace hashed walk-forward priors."""
        with self.connect() as conn:
            conn.execute("DELETE FROM cochange_priors")
            conn.executemany(
                "INSERT INTO cochange_priors(seed_ref,candidate_ref,support,score,trained_at) VALUES(?,?,?,?,?)",
                [
                    (
                        str(row.get("seed_ref", "")),
                        str(row.get("candidate_ref", "")),
                        int(row.get("support", 0) or 0),
                        float(row.get("score", 0.0) or 0.0),
                        trained_at,
                    )
                    for row in rows
                    if row.get("seed_ref") and row.get("candidate_ref")
                ],
            )
        return len(rows)

    def nodes_for_files(
        self,
        file_paths: list[str],
        *,
        limit: int = 200,
        types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return a bounded deterministic node slice for explicit logical paths."""
        paths = list(dict.fromkeys(str(path) for path in file_paths if path))[:100]
        node_types = sorted({str(node_type) for node_type in (types or []) if node_type})
        if not paths or limit <= 0:
            return []
        rows: list[sqlite3.Row] = []
        with self.connect() as conn:
            for start in range(0, len(paths), 400):
                batch = paths[start : start + 400]
                placeholders = ",".join("?" for _ in batch)
                type_clause = ""
                query_args: list[Any] = [*batch]
                if node_types:
                    type_placeholders = ",".join("?" for _ in node_types)
                    type_clause = f" AND type IN ({type_placeholders})"
                    query_args.extend(node_types)
                rows.extend(
                    conn.execute(
                        f"""
                        SELECT * FROM nodes
                        WHERE file_path IN ({placeholders}){type_clause}
                        ORDER BY CASE type
                            WHEN 'Method' THEN 0 WHEN 'Endpoint' THEN 1
                            WHEN 'FeignMethod' THEN 2 WHEN 'Class' THEN 3
                            WHEN 'File' THEN 9 ELSE 5 END,
                            file_path, line, id
                        LIMIT ?
                        """,
                        [*query_args, max(1, limit - len(rows))],
                    ).fetchall()
                )
                if len(rows) >= limit:
                    break
        return [_row_node(row) for row in rows[:limit]]

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

    def _upsert_search_rows(self, node_dicts: Iterable[GraphNode]) -> dict[str, int | float | str]:
        """Replace FTS rows for one bounded refresh scope in a single transaction."""
        started = time.perf_counter()
        nodes = list(node_dicts)
        if not nodes:
            return {"fts_sync_mode": "partial", "fts_changed_nodes": 0, "fts_elapsed_ms": 0.0}
        with self.connect() as conn:
            try:
                ids = [node.id for node in nodes]
                conn.execute(
                    f"DELETE FROM node_search WHERE id IN ({','.join('?' for _ in ids)})",
                    ids,
                )
                conn.executemany(
                    "INSERT INTO node_search(id, type, name, project, file_path, content) VALUES(?, ?, ?, ?, ?, ?)",
                    [
                        (
                            node.id,
                            node.type,
                            node.name,
                            node.project,
                            node.file_path,
                            " ".join([node.id, node.type, node.name, node.project, node.file_path, _metadata_json(node.metadata)]),
                        )
                        for node in nodes
                    ],
                )
                return {
                    "fts_sync_mode": "partial",
                    "fts_changed_nodes": len(nodes),
                    "fts_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            except sqlite3.OperationalError:
                return {
                    "fts_sync_mode": "unavailable",
                    "fts_changed_nodes": 0,
                    "fts_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                }

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return {"nodes": nodes, "edges": edges}

    def community_projection(self, *, limit: int = 30) -> dict[str, list[dict[str, Any]]]:
        """Aggregate cross-project relationships and central nodes in SQLite.

        This is intentionally an explicit offline query: it transfers only
        grouped rows, never the complete graph, to the caller.
        """
        bounded_limit = min(max(1, limit), 100)
        with self.connect() as conn:
            relationships = conn.execute(
                """
                SELECT source.project AS source_project, target.project AS target_project, COUNT(*) AS edge_count
                FROM edges edge
                JOIN nodes source ON source.id=edge.source_id
                JOIN nodes target ON target.id=edge.target_id
                WHERE source.project <> '' AND target.project <> '' AND source.project <> target.project
                GROUP BY source.project, target.project
                ORDER BY edge_count DESC, source.project, target.project
                LIMIT ?
                """,
                (bounded_limit * 4,),
            ).fetchall()
            central_nodes = conn.execute(
                """
                SELECT node.id, node.name, node.type, node.project, node.file_path, node.line,
                       COUNT(edge.id) AS degree,
                       COUNT(DISTINCT CASE
                           WHEN source.project = node.project THEN target.project ELSE source.project END) AS connected_projects
                       ,SUM(CASE WHEN lower(source.file_path) LIKE '%/test/%'
                                      OR lower(target.file_path) LIKE '%/test/%'
                                      OR lower(source.file_path) LIKE '%test.java'
                                      OR lower(target.file_path) LIKE '%test.java'
                                 THEN 1 ELSE 0 END) AS test_edge_count
                FROM nodes node
                JOIN edges edge ON edge.source_id=node.id OR edge.target_id=node.id
                LEFT JOIN nodes source ON source.id=edge.source_id
                LEFT JOIN nodes target ON target.id=edge.target_id
                WHERE node.project <> ''
                GROUP BY node.id
                ORDER BY connected_projects DESC, degree DESC, node.name
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
            typed_relationships = conn.execute(
                """
                SELECT source.project AS source_project, target.project AS target_project,
                       edge.type AS edge_type, COUNT(*) AS edge_count,
                       AVG(edge.confidence) AS average_confidence
                FROM edges edge
                JOIN nodes source ON source.id=edge.source_id
                JOIN nodes target ON target.id=edge.target_id
                WHERE source.project <> '' AND target.project <> '' AND source.project <> target.project
                GROUP BY source.project, target.project, edge.type
                ORDER BY edge_count DESC, source.project, target.project, edge.type
                LIMIT ?
                """,
                (bounded_limit * 8,),
            ).fetchall()
        return {
            "relationships": [dict(row) for row in relationships],
            "central_nodes": [dict(row) for row in central_nodes],
            "typed_relationships": [dict(row) for row in typed_relationships],
        }

    def all_nodes(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM nodes").fetchall()
        return [_row_node(row) for row in rows]

    def nodes_by_ids(self, node_ids: set[str] | list[str]) -> list[dict[str, Any]]:
        """Read a bounded node set without materializing the full graph."""
        ids = sorted({str(node_id) for node_id in node_ids if node_id})
        if not ids:
            return []
        rows = []
        with self.connect() as conn:
            for start in range(0, len(ids), 900):
                batch = ids[start : start + 900]
                placeholders = ",".join("?" for _ in batch)
                rows.extend(conn.execute(f"SELECT * FROM nodes WHERE id IN ({placeholders})", batch).fetchall())
        return [_row_node(row) for row in rows]

    def iter_assertion_rows(
        self,
        *,
        batch_size: int = 1000,
        paths: list[str] | None = None,
        projects: list[str] | None = None,
    ):
        """Stream graph relations with endpoint types for assertion materialization."""
        size = min(max(1, batch_size), 5000)
        path_scope = sorted({str(path).replace("\\", "/").lstrip("/") for path in paths or [] if path})
        project_scope = sorted({str(project) for project in projects or [] if project})
        last_id = ""
        while True:
            scope_clauses: list[str] = []
            scope_args: list[Any] = []
            if path_scope:
                placeholders = ",".join("?" for _ in path_scope)
                scope_clauses.append(f"(source.file_path IN ({placeholders}) OR target.file_path IN ({placeholders}))")
                scope_args.extend(path_scope * 2)
            if project_scope:
                placeholders = ",".join("?" for _ in project_scope)
                scope_clauses.append(f"(source.project IN ({placeholders}) OR target.project IN ({placeholders}))")
                scope_args.extend(project_scope * 2)
            scope_sql = f" AND ({' OR '.join(scope_clauses)})" if scope_clauses else ""
            with self.connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT edge.id, edge.source_id, edge.target_id, edge.type, edge.confidence,
                           edge.metadata_json, source.type AS subject_type, target.type AS object_type,
                           source.file_path AS source_file, target.file_path AS target_file,
                           source.project AS source_project, target.project AS target_project
                    FROM edges edge
                    JOIN nodes source ON source.id=edge.source_id
                    JOIN nodes target ON target.id=edge.target_id
                    WHERE edge.id > ? {scope_sql} ORDER BY edge.id LIMIT ?
                    """,
                    [last_id, *scope_args, size],
                ).fetchall()
            if not rows:
                return
            for row in rows:
                yield dict(row)
            last_id = str(rows[-1]["id"])

    def assertion_row_by_edge_id(self, edge_id: str) -> dict[str, Any] | None:
        """Return one graph edge in the same shape as derived assertions."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT edge.id, edge.source_id, edge.target_id, edge.type, edge.confidence,
                       edge.metadata_json, source.type AS subject_type, target.type AS object_type,
                       source.file_path AS source_file, target.file_path AS target_file,
                       source.project AS source_project, target.project AS target_project
                FROM edges edge
                JOIN nodes source ON source.id=edge.source_id
                JOIN nodes target ON target.id=edge.target_id
                WHERE edge.id=?
                """,
                (edge_id,),
            ).fetchone()
        return dict(row) if row else None

    def project_subgraph(self, project: str) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Export a self-contained graph shard for one project."""
        with self.connect() as conn:
            node_rows = conn.execute("SELECT * FROM nodes WHERE project=?", (project,)).fetchall()
            if not node_rows:
                return [], []
            # A large service can have tens of thousands of nodes. Joining
            # through the indexed node project avoids two giant IN lists and
            # keeps partial-generation export bounded by SQLite's planner.
            edge_rows = conn.execute(
                """
                SELECT edge.*
                FROM edges AS edge
                JOIN nodes AS source_node ON source_node.id = edge.source_id
                JOIN nodes AS target_node ON target_node.id = edge.target_id
                WHERE source_node.project = ? AND target_node.project = ?
                """,
                (project, project),
            ).fetchall()
        nodes = [GraphNode(row["id"], row["type"], row["name"], row["project"], row["file_path"], row["line"], _loads_json(row["metadata_json"])) for row in node_rows]
        edges = [GraphEdge(row["id"], row["source_id"], row["target_id"], row["type"], row["confidence"], _loads_json(row["metadata_json"])) for row in edge_rows]
        return nodes, edges


def node_id(kind: str, *parts: str) -> str:
    body = ":".join(str(p).strip().replace(" ", "_") for p in parts if str(p).strip())
    return f"{kind}:{body}"


def edge_id(edge_type: str, source_id: str, target_id: str) -> str:
    return f"{edge_type}:{source_id}->{target_id}"


def _path_ref(path: str) -> str:
    import hashlib

    return hashlib.sha256(path.encode("utf-8", errors="replace")).hexdigest()[:24]


def _sanitize_fts_term(term: str) -> str:
    return _RE_SANITIZE_FTS.sub("", term)


def _loads_json(value: str) -> dict[str, Any]:
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
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
