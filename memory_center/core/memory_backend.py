from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict


class MemoryBackendStore:
    """Lightweight SQLite mirror for memory-side JSONL/refs data.

    This backend does not replace the existing local-first files yet. It mirrors
    them so higher-level queries, dashboards, and future migrations can rely on
    a more structured substrate.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
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

    def __enter__(self) -> "MemoryBackendStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS json_records (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  collection TEXT NOT NULL,
                  record_id TEXT DEFAULT '',
                  created_at TEXT DEFAULT '',
                  payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_json_records_collection ON json_records(collection);
                CREATE INDEX IF NOT EXISTS idx_json_records_record_id ON json_records(record_id);
                CREATE INDEX IF NOT EXISTS idx_json_records_created_at ON json_records(created_at);

                CREATE TABLE IF NOT EXISTS refs (
                  ref_path TEXT PRIMARY KEY,
                  created_at TEXT DEFAULT '',
                  payload_json TEXT NOT NULL
                );
                """
            )

    def append_record(self, collection: str, payload: Dict[str, Any], record_id: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO json_records(collection, record_id, created_at, payload_json)
                VALUES(?, ?, ?, ?)
                """,
                (
                    collection,
                    record_id,
                    str(payload.get("created_at", "") or ""),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def upsert_ref(self, ref_path: str, payload: Any) -> None:
        created_at = ""
        if isinstance(payload, dict):
            created_at = str(payload.get("created_at", "") or "")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO refs(ref_path, created_at, payload_json)
                VALUES(?, ?, ?)
                ON CONFLICT(ref_path) DO UPDATE SET
                  created_at=excluded.created_at,
                  payload_json=excluded.payload_json
                """,
                (ref_path, created_at, json.dumps(payload, ensure_ascii=False)),
            )

    def stats(self) -> Dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT collection, COUNT(*) AS count FROM json_records GROUP BY collection ORDER BY collection"
            ).fetchall()
            ref_count = conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
        return {
            "db_path": str(self.db_path),
            "collections": {str(row["collection"]): int(row["count"]) for row in rows},
            "ref_count": int(ref_count),
        }

    def query_records(
        self,
        *,
        collection: str = "",
        record_id: str = "",
        created_after: str = "",
        limit: int = 50,
    ) -> Dict[str, Any]:
        sql = "SELECT collection, record_id, created_at, payload_json FROM json_records WHERE 1=1"
        args: list[Any] = []
        if collection:
            sql += " AND collection = ?"
            args.append(collection)
        if record_id:
            sql += " AND record_id = ?"
            args.append(record_id)
        if created_after:
            sql += " AND created_at >= ?"
            args.append(created_after)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        records = [
            {
                "collection": str(row["collection"]),
                "record_id": str(row["record_id"]),
                "created_at": str(row["created_at"]),
                "payload": json.loads(str(row["payload_json"])),
            }
            for row in rows
        ]
        return {"records": list(reversed(records)), "count": len(records)}

    def query_refs(
        self,
        *,
        ref_path: str = "",
        limit: int = 50,
    ) -> Dict[str, Any]:
        sql = "SELECT ref_path, created_at, payload_json FROM refs WHERE 1=1"
        args: list[Any] = []
        if ref_path:
            sql += " AND ref_path = ?"
            args.append(ref_path)
        sql += " ORDER BY created_at DESC, ref_path DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        refs = [
            {
                "ref_path": str(row["ref_path"]),
                "created_at": str(row["created_at"]),
                "payload": json.loads(str(row["payload_json"])),
            }
            for row in rows
        ]
        return {"refs": refs, "count": len(refs)}
