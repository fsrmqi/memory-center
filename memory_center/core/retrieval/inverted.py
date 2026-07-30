"""Inverted index for O(K) sparse retrieval — replaces 2.x brute-force O(N) BM25.

Builds a posting-list index once, then queries only iterate candidate docs
instead of scanning every document in the workspace.
"""
from __future__ import annotations

from typing import Any

from memory_center.core.retrieval.semantic import _count_tokens, semantic_tokens

from ..storage.metadata import metadata_json as _metadata_json
from ..storage.runtime import RuntimeStore

BM25_K1 = 1.5
BM25_B = 0.75
# Code identifiers and externally visible contracts carry much more retrieval
# signal than a path fragment or arbitrary metadata value.
_FIELD_WEIGHTS = {"name": 4.0, "type": 1.5, "project": 1.0, "path": 1.4, "metadata": 0.6}


class InvertedIndex:
    """Posting-list inverted index backed by SQLite (RuntimeStore).

    Stores per-token posting lists so queries only touch matching documents
    instead of scanning all N documents.

    Schema (added to the unified DB):
        inv_postings(token TEXT, doc_idx INTEGER, tf_idf REAL)
        inv_docs(doc_idx INTEGER PRIMARY KEY, node_id TEXT, doc_len INTEGER, norm REAL)
    """

    def __init__(self, store: RuntimeStore):
        self._store = store
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._store.pool.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS inv_docs (
                    doc_idx INTEGER PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    doc_len INTEGER DEFAULT 0,
                    norm REAL DEFAULT 1.0
                );
                CREATE TABLE IF NOT EXISTS inv_postings (
                    token TEXT NOT NULL,
                    doc_idx INTEGER NOT NULL,
                    tf_idf REAL DEFAULT 0.0,
                    bm25_score REAL DEFAULT 0.0,
                    term_count REAL DEFAULT 0.0,
                    PRIMARY KEY (token, doc_idx)
                );
                CREATE INDEX IF NOT EXISTS idx_inv_postings_token ON inv_postings(token);
                CREATE TABLE IF NOT EXISTS inv_terms (
                    token TEXT PRIMARY KEY,
                    doc_freq INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inv_index_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    format_version INTEGER NOT NULL,
                    doc_count INTEGER NOT NULL,
                    total_doc_len REAL NOT NULL
                );
            """)
            try:
                conn.execute("ALTER TABLE inv_postings ADD COLUMN term_count REAL DEFAULT 0.0")
            except Exception:
                pass

    # ── Build / Rebuild ──────────────────────────────────────────────────

    def rebuild(self, nodes: list[dict[str, Any]]) -> dict[str, int]:
        """Rebuild the entire inverted index from graph nodes."""
        with self._store.pool.transaction() as conn:
            conn.execute("DELETE FROM inv_postings")
            conn.execute("DELETE FROM inv_docs")
            conn.execute("DELETE FROM inv_terms")
            conn.execute("DELETE FROM inv_index_meta")

        docs: list[dict[str, Any]] = []
        df: dict[str, int] = {}

        for idx, node in enumerate(nodes):
            counts = _weighted_node_tokens(node)
            if not counts:
                continue
            docs.append({
                "doc_idx": idx,
                "node_id": node.get("id", ""),
                "token_counts": counts,
                "doc_len": sum(counts.values()),
            })
            for token in counts:
                df[token] = df.get(token, 0) + 1

        total_doc_len = sum(doc["doc_len"] for doc in docs)
        doc_count = max(len(docs), 1)
        avgdl = total_doc_len / doc_count if docs else 1.0

        # Build posting rows
        posting_rows: list[tuple] = []
        doc_rows: list[tuple] = []
        for doc in docs:
            idx = doc["doc_idx"]
            for token, count in doc["token_counts"].items():
                # V2 scores from raw counts at query time. Keeping legacy
                # score columns at zero avoids millions of obsolete rebuild
                # calculations while preserving the additive SQLite schema.
                posting_rows.append((token, idx, 0.0, 0.0, count))
            doc_rows.append((idx, doc["node_id"], doc["doc_len"], 1.0))

        # Bulk insert
        with self._store.pool.transaction() as conn:
            conn.executemany("INSERT INTO inv_docs(doc_idx, node_id, doc_len, norm) VALUES(?,?,?,?)", doc_rows)
            conn.executemany(
                "INSERT INTO inv_postings(token, doc_idx, tf_idf, bm25_score, term_count) VALUES(?,?,?,?,?)",
                posting_rows,
            )
            conn.executemany(
                "INSERT INTO inv_terms(token, doc_freq) VALUES(?,?)",
                sorted(df.items()),
            )
            conn.execute(
                "INSERT INTO inv_index_meta(id, format_version, doc_count, total_doc_len) VALUES(1, 2, ?, ?)",
                (len(docs), total_doc_len),
            )

        return {
            "doc_count": len(docs),
            "token_count": len(df),
            "posting_count": len(posting_rows),
            "avgdl": round(avgdl, 2),
        }

    def replace_nodes(
        self,
        nodes: list[dict[str, Any]],
        changed_node_ids: set[str],
        *,
        all_nodes_for_fallback: list[dict[str, Any]] | None = None,
    ) -> dict[str, int | str]:
        """Replace changed documents while retaining untouched postings.

        BM25 scores are calculated from persisted term frequencies at query
        time, so document-frequency and average-length changes remain exactly
        equivalent to a full rebuild without rewriting unrelated postings.
        """
        changed_ids = {str(node_id) for node_id in changed_node_ids if node_id}
        if not changed_ids:
            return {**self.stats(), "mode": "partial-noop", "changed_doc_count": 0}
        state = self._state()
        if state is None:
            if all_nodes_for_fallback is None:
                raise RuntimeError("incremental BM25 requires a full rebuild for legacy index format")
            return {**self.rebuild(all_nodes_for_fallback), "mode": "full-legacy-fallback", "changed_doc_count": 0}

        fresh_docs = self._documents(nodes)
        fresh_by_id = {str(doc["node_id"]): doc for doc in fresh_docs}
        ids = sorted(changed_ids)
        with self._store.pool.transaction() as conn:
            existing_rows = self._rows_for_node_ids(conn, ids)
            existing_by_id = {str(row["node_id"]): row for row in existing_rows}
            old_doc_indices = [int(row["doc_idx"]) for row in existing_rows]
            old_tokens = self._tokens_for_doc_indices(conn, old_doc_indices)
            old_total_len = sum(float(row["doc_len"] or 0) for row in existing_rows)
            next_idx = int(conn.execute("SELECT COALESCE(MAX(doc_idx), -1) + 1 FROM inv_docs").fetchone()[0])

            if old_doc_indices:
                placeholders = ",".join("?" for _ in old_doc_indices)
                conn.execute(f"DELETE FROM inv_postings WHERE doc_idx IN ({placeholders})", old_doc_indices)
                conn.execute(f"DELETE FROM inv_docs WHERE doc_idx IN ({placeholders})", old_doc_indices)

            doc_rows: list[tuple[int, str, float, float]] = []
            posting_rows: list[tuple[str, int, float, float, float]] = []
            affected_tokens = set(old_tokens)
            for node_id in sorted(fresh_by_id):
                doc = fresh_by_id[node_id]
                old_row = existing_by_id.get(node_id)
                doc_idx = int(old_row["doc_idx"]) if old_row is not None else next_idx
                if old_row is None:
                    next_idx += 1
                doc_len = float(doc["doc_len"])
                doc_rows.append((doc_idx, node_id, doc_len, 1.0))
                for token, count in doc["token_counts"].items():
                    affected_tokens.add(token)
                    posting_rows.append((token, doc_idx, 0.0, 0.0, float(count)))

            conn.executemany("INSERT INTO inv_docs(doc_idx, node_id, doc_len, norm) VALUES(?,?,?,?)", doc_rows)
            conn.executemany(
                "INSERT INTO inv_postings(token, doc_idx, tf_idf, bm25_score, term_count) VALUES(?,?,?,?,?)",
                posting_rows,
            )
            doc_count = int(state["doc_count"]) - len(existing_rows) + len(doc_rows)
            total_doc_len = float(state["total_doc_len"]) - old_total_len + sum(row[2] for row in doc_rows)
            conn.execute(
                "UPDATE inv_index_meta SET doc_count=?, total_doc_len=? WHERE id=1",
                (max(doc_count, 0), max(total_doc_len, 0.0)),
            )
            self._refresh_term_frequencies(conn, affected_tokens)

        return {**self.stats(), "mode": "partial", "changed_doc_count": len(doc_rows)}

    def can_incrementally_update(self) -> bool:
        return self._state() is not None

    # ── Query ────────────────────────────────────────────────────────────

    def query(self, query_text: str, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve documents matching query using BM25 scoring over the inverted index.

        Only iterates posting lists for query tokens — O(K) where K = matching docs.
        """
        tokens = semantic_tokens(query_text)
        if not tokens:
            return []

        query_counts = _count_tokens(tokens)

        # Aggregate and rank inside SQLite. Returning every matching posting to
        # Python makes common query terms proportional to the entire corpus;
        # this query returns only the bounded top-K document IDs.
        with self._store.pool.connection() as conn:
            placeholders = ",".join("?" for _ in query_counts)
            if self._state() is None:
                # Existing workspaces stay queryable until their next explicit
                # reindex performs the one-time raw-term migration.
                rows = conn.execute(
                    f"""
                    SELECT doc_idx, SUM(bm25_score) AS score
                    FROM inv_postings
                    WHERE token IN ({placeholders})
                    GROUP BY doc_idx
                    ORDER BY score DESC, doc_idx ASC
                    LIMIT ?
                    """,
                    [*query_counts.keys(), limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT p.doc_idx,
                           SUM(
                             log((m.doc_count - t.doc_freq + 0.5) / (t.doc_freq + 0.5) + 1)
                             * (p.term_count * (? + 1))
                             / (p.term_count + ? * (1 - ? + ? * d.doc_len / CASE WHEN m.doc_count > 0 THEN m.total_doc_len / m.doc_count ELSE 1 END))
                           ) AS score
                    FROM inv_postings p
                    JOIN inv_docs d ON d.doc_idx=p.doc_idx
                    JOIN inv_terms t ON t.token=p.token
                    JOIN inv_index_meta m ON m.id=1
                    WHERE p.token IN ({placeholders})
                    GROUP BY p.doc_idx
                    ORDER BY score DESC, p.doc_idx ASC
                    LIMIT ?
                    """,
                    [BM25_K1, BM25_K1, BM25_B, BM25_B, *query_counts.keys(), limit],
                ).fetchall()

        if not rows:
            return []
        ranked = [(int(row["doc_idx"]), float(row["score"])) for row in rows]

        # Fetch doc metadata
        if not ranked:
            return []
        doc_indices = [idx for idx, _ in ranked]
        placeholders = ",".join("?" for _ in doc_indices)
        with self._store.pool.connection() as conn:
            doc_rows = conn.execute(
                f"SELECT doc_idx, node_id, doc_len, norm FROM inv_docs WHERE doc_idx IN ({placeholders})",
                doc_indices,
            ).fetchall()
        doc_meta = {int(r["doc_idx"]): dict(r) for r in doc_rows}

        results = []
        for doc_idx, score in ranked:
            meta = doc_meta.get(doc_idx, {})
            results.append({
                "node_id": meta.get("node_id", ""),
                "doc_len": meta.get("doc_len", 0),
                "score": round(score, 4),
                "backend": "bm25_inverted",
            })
        return results

    def stats(self) -> dict[str, int]:
        with self._store.pool.connection() as conn:
            docs = conn.execute("SELECT COUNT(*) FROM inv_docs").fetchone()[0]
            postings = conn.execute("SELECT COUNT(*) FROM inv_postings").fetchone()[0]
            tokens = conn.execute("SELECT COUNT(*) FROM inv_terms").fetchone()[0]
        return {"doc_count": docs, "posting_count": postings, "token_count": tokens}

    def _state(self) -> dict[str, float] | None:
        with self._store.pool.connection() as conn:
            row = conn.execute(
                "SELECT format_version, doc_count, total_doc_len FROM inv_index_meta WHERE id=1"
            ).fetchone()
        if row is None or int(row["format_version"] or 0) != 2:
            return None
        return {"doc_count": float(row["doc_count"]), "total_doc_len": float(row["total_doc_len"])}

    @staticmethod
    def _documents(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        docs = []
        for node in nodes:
            counts = _weighted_node_tokens(node)
            if counts:
                docs.append({"node_id": str(node.get("id", "")), "token_counts": counts, "doc_len": sum(counts.values())})
        return docs

    @staticmethod
    def _rows_for_node_ids(conn: Any, node_ids: list[str]) -> list[Any]:
        rows = []
        for start in range(0, len(node_ids), 900):
            batch = node_ids[start : start + 900]
            placeholders = ",".join("?" for _ in batch)
            rows.extend(conn.execute(f"SELECT doc_idx, node_id, doc_len FROM inv_docs WHERE node_id IN ({placeholders})", batch).fetchall())
        return rows

    @staticmethod
    def _tokens_for_doc_indices(conn: Any, doc_indices: list[int]) -> set[str]:
        tokens: set[str] = set()
        for start in range(0, len(doc_indices), 900):
            batch = doc_indices[start : start + 900]
            placeholders = ",".join("?" for _ in batch)
            tokens.update(str(row["token"]) for row in conn.execute(f"SELECT DISTINCT token FROM inv_postings WHERE doc_idx IN ({placeholders})", batch))
        return tokens

    @staticmethod
    def _refresh_term_frequencies(conn: Any, tokens: set[str]) -> None:
        for token in sorted(tokens):
            count = int(conn.execute("SELECT COUNT(*) FROM inv_postings WHERE token=?", (token,)).fetchone()[0])
            if count:
                conn.execute(
                    "INSERT INTO inv_terms(token, doc_freq) VALUES(?,?) ON CONFLICT(token) DO UPDATE SET doc_freq=excluded.doc_freq",
                    (token, count),
                )
            else:
                conn.execute("DELETE FROM inv_terms WHERE token=?", (token,))


def _weighted_node_tokens(node: dict[str, Any]) -> dict[str, float]:
    """Build BM25F-style weighted token frequencies for code entities."""
    fields = {
        "name": node.get("name", ""),
        "type": node.get("type", ""),
        "project": node.get("project", ""),
        "path": node.get("file_path", ""),
        "metadata": _metadata_json(node.get("metadata")),
    }
    counts: dict[str, float] = {}
    for field, value in fields.items():
        weight = _FIELD_WEIGHTS[field]
        for token, count in _count_tokens(semantic_tokens(str(value))).items():
            counts[token] = counts.get(token, 0.0) + count * weight
    return counts
