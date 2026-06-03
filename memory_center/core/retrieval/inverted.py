"""Inverted index for O(K) sparse retrieval — replaces 2.x brute-force O(N) BM25.

Builds a posting-list index once, then queries only iterate candidate docs
instead of scanning every document in the workspace.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..storage.unified import UnifiedStore
from ..semantic import semantic_tokens, _count_tokens, _split_camel

BM25_K1 = 1.5
BM25_B = 0.75


class InvertedIndex:
    """Posting-list inverted index backed by SQLite (UnifiedStore).

    Stores per-token posting lists so queries only touch matching documents
    instead of scanning all N documents.

    Schema (added to the unified DB):
        inv_postings(token TEXT, doc_idx INTEGER, tf_idf REAL)
        inv_docs(doc_idx INTEGER PRIMARY KEY, node_id TEXT, doc_len INTEGER, norm REAL)
    """

    def __init__(self, store: UnifiedStore):
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
                    PRIMARY KEY (token, doc_idx)
                );
                CREATE INDEX IF NOT EXISTS idx_inv_postings_token ON inv_postings(token);
            """)

    # ── Build / Rebuild ──────────────────────────────────────────────────

    def rebuild(self, nodes: list[dict[str, Any]]) -> dict[str, int]:
        """Rebuild the entire inverted index from graph nodes."""
        with self._store.pool.transaction() as conn:
            conn.execute("DELETE FROM inv_postings")
            conn.execute("DELETE FROM inv_docs")

        docs: list[dict[str, Any]] = []
        df: dict[str, int] = {}

        for idx, node in enumerate(nodes):
            text = _node_text(node)
            tokens = semantic_tokens(text)
            if not tokens:
                continue
            counts = _count_tokens(tokens)
            docs.append({
                "doc_idx": idx,
                "node_id": node.get("id", ""),
                "token_counts": counts,
                "doc_len": sum(counts.values()),
            })
            for token in counts:
                df[token] = df.get(token, 0) + 1

        doc_count = max(len(docs), 1)
        avgdl = sum(d["doc_len"] for d in docs) / doc_count if docs else 1.0

        # Build posting rows
        posting_rows: list[tuple] = []
        doc_rows: list[tuple] = []
        for doc in docs:
            idx = doc["doc_idx"]
            total = doc["doc_len"] or 1
            norm_sq = 0.0
            for token, count in doc["token_counts"].items():
                idf = math.log((1 + doc_count) / (1 + df.get(token, 0))) + 1.0
                tf_idf = (count / total) * idf
                # BM25 component
                bm25_idf = math.log((doc_count - df.get(token, 0) + 0.5) / (df.get(token, 0) + 0.5) + 1)
                bm25 = bm25_idf * (count * (BM25_K1 + 1)) / (count + BM25_K1 * (1 - BM25_B + BM25_B * doc["doc_len"] / avgdl))
                posting_rows.append((token, idx, tf_idf, bm25))
                norm_sq += tf_idf * tf_idf
            norm = math.sqrt(norm_sq) or 1.0
            doc_rows.append((idx, doc["node_id"], doc["doc_len"], norm))

        # Bulk insert
        with self._store.pool.transaction() as conn:
            conn.executemany("INSERT INTO inv_docs(doc_idx, node_id, doc_len, norm) VALUES(?,?,?,?)", doc_rows)
            conn.executemany("INSERT INTO inv_postings(token, doc_idx, tf_idf, bm25_score) VALUES(?,?,?,?)", posting_rows)

        return {
            "doc_count": len(docs),
            "token_count": len(df),
            "posting_count": len(posting_rows),
            "avgdl": round(avgdl, 2),
        }

    # ── Query ────────────────────────────────────────────────────────────

    def query(self, query_text: str, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve documents matching query using BM25 scoring over the inverted index.

        Only iterates posting lists for query tokens — O(K) where K = matching docs.
        """
        tokens = semantic_tokens(query_text)
        if not tokens:
            return []

        query_counts = _count_tokens(tokens)

        # Fetch doc_count and avgdl from inv_docs
        with self._store.pool.connection() as conn:
            stats = conn.execute("SELECT COUNT(*) AS cnt, COALESCE(AVG(doc_len), 1.0) AS avgdl FROM inv_docs").fetchone()
            doc_count = max(int(stats["cnt"]), 1)
            avgdl = float(stats["avgdl"]) or 1.0

            # Fetch candidate postings for query tokens
            placeholders = ",".join("?" for _ in query_counts)
            rows = conn.execute(
                f"SELECT token, doc_idx, bm25_score FROM inv_postings WHERE token IN ({placeholders})",
                list(query_counts.keys()),
            ).fetchall()

        if not rows:
            return []

        # Aggregate BM25 scores per doc
        doc_scores: dict[int, float] = {}
        for row in rows:
            doc_idx = int(row["doc_idx"])
            doc_scores[doc_idx] = doc_scores.get(doc_idx, 0.0) + float(row["bm25_score"])

        # Sort by score, take top-K
        ranked = sorted(doc_scores.items(), key=lambda x: -x[1])[:limit]

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
            tokens = conn.execute("SELECT COUNT(DISTINCT token) FROM inv_postings").fetchone()[0]
        return {"doc_count": docs, "posting_count": postings, "token_count": tokens}


def _node_text(node: dict[str, Any]) -> str:
    parts = [
        node.get("type", ""),
        node.get("name", ""),
        node.get("project", ""),
        node.get("file_path", ""),
        json.dumps(node.get("metadata", {}), ensure_ascii=False),
    ]
    return " ".join(str(p) for p in parts if p)
