"""Vector index abstraction — sqlite-vec integration with numpy fallback.

Provides ANN (Approximate Nearest Neighbor) search for code entities.
Uses sqlite-vec when available, falls back to brute-force numpy cosine similarity.
"""
from __future__ import annotations

import importlib.util
import json
import math
import struct
from typing import Any, Dict, List, Tuple

from .unified import UnifiedStore

# Try to import sqlite_vec
_HAS_SQLITE_VEC = importlib.util.find_spec("sqlite_vec") is not None

# Try to import numpy for fallback
_HAS_NUMPY = importlib.util.find_spec("numpy") is not None


class VectorIndex:
    """Vector index for semantic search over code entities.

    Uses sqlite-vec for efficient ANN search when available.
    Falls back to brute-force cosine similarity with numpy.
    Falls back to pure Python cosine similarity as last resort.
    """

    def __init__(self, store: UnifiedStore, dimension: int = 384):
        self._store = store
        self._dimension = dimension
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create vector table schema."""
        with self._store.pool.connection() as conn:
            # Always create the metadata table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vec_metadata (
                    node_id TEXT PRIMARY KEY,
                    dimension INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Try to create sqlite-vec virtual table
            if _HAS_SQLITE_VEC:
                try:
                    conn.execute(f"""
                        CREATE VIRTUAL TABLE IF NOT EXISTS node_vec USING vec0(
                            node_id TEXT PRIMARY KEY,
                            embedding FLOAT[{self._dimension}]
                        )
                    """)
                except Exception:
                    pass  # sqlite-vec not available, will use fallback

            # Always create a BLOB column for fallback storage
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vec_fallback (
                    node_id TEXT PRIMARY KEY,
                    embedding BLOB
                )
            """)

    def upsert_embedding(self, node_id: str, embedding: List[float]) -> None:
        """Store an embedding vector for a node."""
        if len(embedding) != self._dimension:
            raise ValueError(f"Embedding dimension mismatch: expected {self._dimension}, got {len(embedding)}")

        with self._store.pool.transaction() as conn:
            # Store in metadata
            conn.execute(
                "INSERT OR REPLACE INTO vec_metadata(node_id, dimension) VALUES(?, ?)",
                (node_id, self._dimension),
            )

            # Store in sqlite-vec if available
            if _HAS_SQLITE_VEC:
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO node_vec(node_id, embedding) VALUES(?, vec_f32(?))",
                        (node_id, json.dumps(embedding)),
                    )
                except Exception:
                    pass

            # Always store in fallback (as packed float32 bytes)
            blob = struct.pack(f"{self._dimension}f", *embedding)
            conn.execute(
                "INSERT OR REPLACE INTO vec_fallback(node_id, embedding) VALUES(?, ?)",
                (node_id, blob),
            )

    def upsert_embeddings_batch(self, items: List[Tuple[str, List[float]]]) -> int:
        """Batch upsert embeddings. Returns count of stored embeddings."""
        count = 0
        with self._store.pool.transaction() as conn:
            for node_id, embedding in items:
                if len(embedding) != self._dimension:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO vec_metadata(node_id, dimension) VALUES(?, ?)",
                    (node_id, self._dimension),
                )
                blob = struct.pack(f"{self._dimension}f", *embedding)
                conn.execute(
                    "INSERT OR REPLACE INTO vec_fallback(node_id, embedding) VALUES(?, ?)",
                    (node_id, blob),
                )
                count += 1

                if _HAS_SQLITE_VEC:
                    try:
                        conn.execute(
                            "INSERT OR REPLACE INTO node_vec(node_id, embedding) VALUES(?, vec_f32(?))",
                            (node_id, json.dumps(embedding)),
                        )
                    except Exception:
                        pass
        return count

    def query(self, query_embedding: List[float], limit: int = 20) -> List[Dict[str, Any]]:
        """Find the most similar nodes to a query embedding."""
        if len(query_embedding) != self._dimension:
            raise ValueError(f"Query embedding dimension mismatch: expected {self._dimension}, got {len(query_embedding)}")

        # Try sqlite-vec first
        if _HAS_SQLITE_VEC:
            results = self._query_vec(query_embedding, limit)
            if results:
                return results

        # Fallback to brute-force
        return self._query_brute_force(query_embedding, limit)

    def _query_vec(self, query_embedding: List[float], limit: int) -> List[Dict[str, Any]]:
        """Query using sqlite-vec ANN index."""
        try:
            with self._store.pool.connection() as conn:
                rows = conn.execute(
                    """SELECT node_id, distance
                        FROM node_vec
                        WHERE embedding MATCH vec_f32(?)
                        ORDER BY distance
                        LIMIT ?""",
                    (json.dumps(query_embedding), limit),
                ).fetchall()
            return [
                {"node_id": str(r["node_id"]), "distance": float(r["distance"]), "backend": "sqlite-vec"}
                for r in rows
            ]
        except Exception:
            return []

    def _query_brute_force(self, query_embedding: List[float], limit: int) -> List[Dict[str, Any]]:
        """Query using brute-force cosine similarity."""
        with self._store.pool.connection() as conn:
            rows = conn.execute("SELECT node_id, embedding FROM vec_fallback").fetchall()

        if not rows:
            return []

        results = []
        query_norm = math.sqrt(sum(x * x for x in query_embedding)) or 1.0

        for row in rows:
            raw = row["embedding"]
            blob = bytes(raw) if raw is not None else b""
            if len(blob) != self._dimension * 4:
                continue
            embedding = struct.unpack(f"{self._dimension}f", blob)
            # Cosine similarity
            dot = sum(q * e for q, e in zip(query_embedding, embedding))
            emb_norm = math.sqrt(sum(e * e for e in embedding)) or 1.0
            similarity = dot / (query_norm * emb_norm)
            if similarity > 0:
                results.append({
                    "node_id": str(row["node_id"]),
                    "distance": round(1.0 - similarity, 4),
                    "score": round(similarity, 4),
                    "backend": "brute_force",
                })

        results.sort(key=lambda x: -x["score"])
        return results[:limit]

    def stats(self) -> Dict[str, Any]:
        """Return index statistics."""
        with self._store.pool.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM vec_metadata").fetchone()[0]
            has_vec_table = bool(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='node_vec' LIMIT 1",
                ).fetchone(),
            )
        return {
            "embedding_count": count,
            "dimension": self._dimension,
            "backend": "sqlite-vec" if _HAS_SQLITE_VEC and has_vec_table else "brute_force",
            "has_numpy": _HAS_NUMPY,
        }

    def delete_embedding(self, node_id: str) -> None:
        """Delete an embedding for a node."""
        with self._store.pool.transaction() as conn:
            conn.execute("DELETE FROM vec_metadata WHERE node_id=?", (node_id,))
            conn.execute("DELETE FROM vec_fallback WHERE node_id=?", (node_id,))
            if _HAS_SQLITE_VEC:
                try:
                    conn.execute("DELETE FROM node_vec WHERE node_id=?", (node_id,))
                except Exception:
                    pass

    def clear(self) -> None:
        """Remove all stored embeddings before a full synchronization."""
        with self._store.pool.transaction() as conn:
            conn.execute("DELETE FROM vec_metadata")
            conn.execute("DELETE FROM vec_fallback")
            if _HAS_SQLITE_VEC:
                try:
                    conn.execute("DELETE FROM node_vec")
                except Exception:
                    pass
