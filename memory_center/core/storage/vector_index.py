"""持久化向量检索索引。

优先使用 sqlite-vec；未安装时使用 hnswlib 持久化 HNSW 索引。大索引绝不
退化为 Python 全量余弦扫描，避免一次语义查询占满解释器并拖慢 MCP 会话。
小于 ``EXACT_TINY_VECTOR_LIMIT`` 的开发/测试索引允许精确检索，作为结果校验
路径，而不是大索引的运行时回退。
"""
from __future__ import annotations

import importlib.util
import json
import math
import sqlite3
import struct
from pathlib import Path
from typing import Any

from .runtime import RuntimeStore

_HAS_SQLITE_VEC = importlib.util.find_spec("sqlite_vec") is not None
_HAS_HNSWLIB = importlib.util.find_spec("hnswlib") is not None
_HAS_NUMPY = importlib.util.find_spec("numpy") is not None
EXACT_TINY_VECTOR_LIMIT = 64
_HNSW_MIN_CAPACITY = 1024


class VectorIndex:
    """语义检索向量索引，提供可观察的 ANN 就绪状态。"""

    def __init__(self, store: RuntimeStore, dimension: int = 384):
        self._store = store
        self._dimension = dimension
        self._hnsw_path = Path(store.db_path).with_suffix(".hnsw")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._store.pool.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vec_metadata (
                    node_id TEXT PRIMARY KEY,
                    dimension INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vec_fallback (
                    node_id TEXT PRIMARY KEY,
                    embedding BLOB NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vec_ann_labels (
                    node_id TEXT PRIMARY KEY,
                    label INTEGER NOT NULL UNIQUE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vec_ann_meta (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    dimension INTEGER NOT NULL,
                    capacity INTEGER NOT NULL,
                    embedding_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            if _HAS_SQLITE_VEC:
                try:
                    conn.execute(f"""
                        CREATE VIRTUAL TABLE IF NOT EXISTS node_vec USING vec0(
                            node_id TEXT PRIMARY KEY,
                            embedding FLOAT[{self._dimension}]
                        )
                    """)
                except sqlite3.Error:
                    pass

    def upsert_embedding(self, node_id: str, embedding: list[float]) -> None:
        if len(embedding) != self._dimension:
            raise ValueError(f"Embedding dimension mismatch: expected {self._dimension}, got {len(embedding)}")
        self.upsert_embeddings_batch([(node_id, embedding)])

    def upsert_embeddings_batch(self, items: list[tuple[str, list[float]]]) -> int:
        """批量写入向量，并在可用时增量同步 HNSW。"""
        valid = [(node_id, embedding) for node_id, embedding in items if len(embedding) == self._dimension]
        if not valid:
            return 0
        with self._store.pool.connection() as conn:
            existing_count = int(conn.execute("SELECT COUNT(*) FROM vec_metadata").fetchone()[0])
        with self._store.pool.transaction() as conn:
            for node_id, embedding in valid:
                conn.execute(
                    "INSERT OR REPLACE INTO vec_metadata(node_id, dimension) VALUES(?, ?)",
                    (node_id, self._dimension),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO vec_fallback(node_id, embedding) VALUES(?, ?)",
                    (node_id, struct.pack(f"{self._dimension}f", *embedding)),
                )
                if _HAS_SQLITE_VEC:
                    try:
                        conn.execute(
                            "INSERT OR REPLACE INTO node_vec(node_id, embedding) VALUES(?, vec_f32(?))",
                            (node_id, json.dumps(embedding)),
                        )
                    except sqlite3.Error:
                        pass
        if not self._has_sqlite_vec_table() and _HAS_HNSWLIB and _HAS_NUMPY:
            # 旧索引升级时不能在局部 refresh 中偷跑一次全库重建。
            if self._hnsw_path.exists() or existing_count == 0:
                self._sync_hnsw_items(valid)
        return len(valid)

    def query(self, query_embedding: list[float], limit: int = 20) -> list[dict[str, Any]]:
        """查询 ANN；大索引没有 ANN 时返回空结果，由 stats 提供下一步动作。"""
        if len(query_embedding) != self._dimension:
            raise ValueError(f"Embedding dimension mismatch: expected {self._dimension}, got {len(query_embedding)}")
        if limit <= 0:
            return []
        if self._has_sqlite_vec_table():
            return self._query_vec(query_embedding, limit)
        if self._hnsw_ready():
            return self._query_hnsw(query_embedding, limit)
        if self._embedding_count() <= EXACT_TINY_VECTOR_LIMIT:
            return self._query_tiny_exact(query_embedding, limit)
        return []

    def rebuild_ann(self) -> dict[str, Any]:
        """显式从持久化向量重建 HNSW，不在查询热路径执行。"""
        if self._has_sqlite_vec_table():
            return {"rebuilt": False, "reason": "sqlite_vec_active", **self.stats()}
        if not (_HAS_HNSWLIB and _HAS_NUMPY):
            return {"rebuilt": False, "reason": "hnswlib_unavailable", **self.stats()}
        with self._store.pool.connection() as conn:
            rows = conn.execute("SELECT node_id, embedding FROM vec_fallback ORDER BY node_id").fetchall()
        items = [
            (str(row["node_id"]), self._unpack_embedding(row["embedding"]))
            for row in rows
            if self._valid_blob(row["embedding"])
        ]
        try:
            self._build_hnsw(items)
        except (ImportError, OSError, RuntimeError, ValueError):
            return {"rebuilt": False, "reason": "hnswlib_initialization_failed", **self.stats()}
        return {"rebuilt": True, "indexed": len(items), **self.stats()}

    def _query_vec(self, query_embedding: list[float], limit: int) -> list[dict[str, Any]]:
        try:
            with self._store.pool.connection() as conn:
                rows = conn.execute(
                    """SELECT node_id, distance FROM node_vec
                       WHERE embedding MATCH vec_f32(?) ORDER BY distance LIMIT ?""",
                    (json.dumps(query_embedding), limit),
                ).fetchall()
            return [
                {"node_id": str(row["node_id"]), "distance": float(row["distance"]), "backend": "sqlite-vec"}
                for row in rows
            ]
        except sqlite3.Error:
            return []

    def _query_hnsw(self, query_embedding: list[float], limit: int) -> list[dict[str, Any]]:
        try:
            import hnswlib  # type: ignore[import-not-found]
            import numpy as np  # type: ignore[import-not-found]

            meta = self._ann_meta()
            if not meta:
                return []
            index = hnswlib.Index(space="cosine", dim=self._dimension)
            index.load_index(str(self._hnsw_path), max_elements=int(meta["capacity"]))
            index.set_ef(max(64, limit * 4))
            active_count = self._embedding_count()
            if active_count <= 0:
                return []
            labels, distances = index.knn_query(np.asarray([query_embedding], dtype=np.float32), k=min(limit, active_count))
            label_values = [int(label) for label in labels[0]]
            if not label_values:
                return []
            placeholders = ",".join("?" for _ in label_values)
            with self._store.pool.connection() as conn:
                rows = conn.execute(
                    f"SELECT node_id, label FROM vec_ann_labels WHERE label IN ({placeholders})",
                    label_values,
                ).fetchall()
            ids = {int(row["label"]): str(row["node_id"]) for row in rows}
            return [
                {"node_id": ids[label], "distance": float(distance), "score": round(1.0 - float(distance), 4), "backend": "hnswlib"}
                for label, distance in zip(label_values, distances[0], strict=True)
                if label in ids
            ]
        except (ImportError, OSError, RuntimeError, ValueError):
            return []

    def _query_tiny_exact(self, query_embedding: list[float], limit: int) -> list[dict[str, Any]]:
        """仅用于很小索引的精确校验，不允许扩展为大索引回退。"""
        with self._store.pool.connection() as conn:
            rows = conn.execute("SELECT node_id, embedding FROM vec_fallback").fetchall()
        query_norm = math.sqrt(sum(value * value for value in query_embedding)) or 1.0
        results: list[dict[str, Any]] = []
        for row in rows:
            if not self._valid_blob(row["embedding"]):
                continue
            embedding = self._unpack_embedding(row["embedding"])
            norm = math.sqrt(sum(value * value for value in embedding)) or 1.0
            score = sum(query_embedding[index] * embedding[index] for index in range(self._dimension)) / (query_norm * norm)
            if score > 0:
                results.append({"node_id": str(row["node_id"]), "distance": round(1.0 - score, 4), "score": round(score, 4), "backend": "exact_small"})
        return sorted(results, key=lambda item: -float(item["score"]))[:limit]

    def _sync_hnsw_items(self, items: list[tuple[str, list[float]]]) -> None:
        if not items:
            return
        if not self._hnsw_ready():
            self._build_hnsw(items)
            return
        try:
            import hnswlib  # type: ignore[import-not-found]
            import numpy as np  # type: ignore[import-not-found]

            meta = self._ann_meta()
            if not meta:
                return
            with self._store.pool.connection() as conn:
                existing = {
                    str(row["node_id"]): int(row["label"])
                    for row in conn.execute(
                        f"SELECT node_id, label FROM vec_ann_labels WHERE node_id IN ({','.join('?' for _ in items)})",
                        [node_id for node_id, _ in items],
                    ).fetchall()
                }
                next_label = int(conn.execute("SELECT COALESCE(MAX(label), -1) + 1 FROM vec_ann_labels").fetchone()[0])
            labels = []
            new_rows: list[tuple[str, int]] = []
            for node_id, _ in items:
                label = existing.get(node_id)
                if label is None:
                    label = next_label
                    next_label += 1
                    new_rows.append((node_id, label))
                labels.append(label)
            required = max(int(meta["embedding_count"]), max(labels, default=-1) + 1)
            capacity = max(int(meta["capacity"]), _capacity_for(required))
            index = hnswlib.Index(space="cosine", dim=self._dimension)
            index.load_index(str(self._hnsw_path), max_elements=max(capacity, int(meta["capacity"])))
            if capacity > int(meta["capacity"]):
                index.resize_index(capacity)
            index.add_items(np.asarray([vector for _, vector in items], dtype=np.float32), np.asarray(labels, dtype=np.int64))
            index.save_index(str(self._hnsw_path))
            with self._store.pool.transaction() as conn:
                conn.executemany("INSERT OR REPLACE INTO vec_ann_labels(node_id, label) VALUES(?, ?)", new_rows)
                conn.execute(
                    "UPDATE vec_ann_meta SET capacity=?, embedding_count=?, updated_at=CURRENT_TIMESTAMP WHERE singleton=1",
                    (capacity, self._embedding_count()),
                )
        except (ImportError, OSError, RuntimeError, ValueError):
            # 向量事实已写入 SQLite；后续显式 rebuild-ann 可以恢复 ANN 文件。
            return

    def _build_hnsw(self, items: list[tuple[str, list[float]]]) -> None:
        import hnswlib  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]

        capacity = _capacity_for(len(items))
        index = hnswlib.Index(space="cosine", dim=self._dimension)
        index.init_index(max_elements=capacity, ef_construction=200, M=16, allow_replace_deleted=True)
        if items:
            index.add_items(
                np.asarray([vector for _, vector in items], dtype=np.float32),
                np.arange(len(items), dtype=np.int64),
            )
        index.save_index(str(self._hnsw_path))
        with self._store.pool.transaction() as conn:
            conn.execute("DELETE FROM vec_ann_labels")
            conn.executemany("INSERT INTO vec_ann_labels(node_id, label) VALUES(?, ?)", [(node_id, label) for label, (node_id, _) in enumerate(items)])
            conn.execute(
                "INSERT OR REPLACE INTO vec_ann_meta(singleton, dimension, capacity, embedding_count, updated_at) VALUES(1, ?, ?, ?, CURRENT_TIMESTAMP)",
                (self._dimension, capacity, len(items)),
            )

    def _has_sqlite_vec_table(self) -> bool:
        if not _HAS_SQLITE_VEC:
            return False
        with self._store.pool.connection() as conn:
            return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='node_vec' LIMIT 1").fetchone())

    def _ann_meta(self) -> sqlite3.Row | None:
        with self._store.pool.connection() as conn:
            return conn.execute("SELECT * FROM vec_ann_meta WHERE singleton=1 AND dimension=?", (self._dimension,)).fetchone()

    def _hnsw_ready(self) -> bool:
        if not (_HAS_HNSWLIB and _HAS_NUMPY and self._hnsw_path.exists()):
            return False
        meta = self._ann_meta()
        if not meta or int(meta["embedding_count"]) != self._embedding_count():
            return False
        with self._store.pool.connection() as conn:
            label_count = int(conn.execute("SELECT COUNT(*) FROM vec_ann_labels").fetchone()[0])
        return label_count == self._embedding_count()

    def _embedding_count(self) -> int:
        with self._store.pool.connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM vec_metadata").fetchone()[0])

    def _valid_blob(self, raw: Any) -> bool:
        return raw is not None and len(bytes(raw)) == self._dimension * 4

    def _unpack_embedding(self, raw: Any) -> list[float]:
        return list(struct.unpack(f"{self._dimension}f", bytes(raw)))

    def stats(self) -> dict[str, Any]:
        count = self._embedding_count()
        sqlite_vec_ready = self._has_sqlite_vec_table()
        hnsw_ready = self._hnsw_ready()
        backend = "sqlite-vec" if sqlite_vec_ready else "hnswlib" if hnsw_ready else "exact_small" if count <= EXACT_TINY_VECTOR_LIMIT else "unavailable"
        reason = ""
        if backend == "unavailable":
            reason = (
                "run vector-ann-rebuild to create the persistent HNSW index"
                if _HAS_HNSWLIB and _HAS_NUMPY
                else "install hnswlib and run vector-ann-rebuild; large indexes do not use exact Python fallback"
            )
        return {
            "embedding_count": count,
            "dimension": self._dimension,
            "backend": backend,
            "ann_ready": sqlite_vec_ready or hnsw_ready,
            "ann_backend": "sqlite-vec" if sqlite_vec_ready else "hnswlib" if hnsw_ready else "",
            "exact_small_limit": EXACT_TINY_VECTOR_LIMIT,
            "has_hnswlib": _HAS_HNSWLIB,
            "has_numpy": _HAS_NUMPY,
            "reason": reason,
            "next_action": "vector-ann-rebuild" if backend == "unavailable" else "",
        }

    def delete_embedding(self, node_id: str) -> None:
        hnsw_was_ready = self._hnsw_ready()
        with self._store.pool.transaction() as conn:
            row = conn.execute("SELECT label FROM vec_ann_labels WHERE node_id=?", (node_id,)).fetchone()
            conn.execute("DELETE FROM vec_metadata WHERE node_id=?", (node_id,))
            conn.execute("DELETE FROM vec_fallback WHERE node_id=?", (node_id,))
            conn.execute("DELETE FROM vec_ann_labels WHERE node_id=?", (node_id,))
            if _HAS_SQLITE_VEC:
                try:
                    conn.execute("DELETE FROM node_vec WHERE node_id=?", (node_id,))
                except sqlite3.Error:
                    pass
        if row and hnsw_was_ready:
            try:
                import hnswlib  # type: ignore[import-not-found]

                meta = self._ann_meta()
                if meta:
                    index = hnswlib.Index(space="cosine", dim=self._dimension)
                    index.load_index(str(self._hnsw_path), max_elements=int(meta["capacity"]))
                    index.mark_deleted(int(row["label"]))
                    index.save_index(str(self._hnsw_path))
                    with self._store.pool.transaction() as conn:
                        conn.execute(
                            "UPDATE vec_ann_meta SET embedding_count=?, updated_at=CURRENT_TIMESTAMP WHERE singleton=1",
                            (self._embedding_count(),),
                        )
            except (ImportError, OSError, RuntimeError, ValueError):
                pass

    def clear(self) -> None:
        with self._store.pool.transaction() as conn:
            conn.execute("DELETE FROM vec_metadata")
            conn.execute("DELETE FROM vec_fallback")
            conn.execute("DELETE FROM vec_ann_labels")
            conn.execute("DELETE FROM vec_ann_meta")
            if _HAS_SQLITE_VEC:
                try:
                    conn.execute("DELETE FROM node_vec")
                except sqlite3.Error:
                    pass
        self._hnsw_path.unlink(missing_ok=True)


def _capacity_for(count: int) -> int:
    return max(_HNSW_MIN_CAPACITY, int(max(count, 1) * 1.25) + 32)
