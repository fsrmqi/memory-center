from __future__ import annotations

import json
import sqlite3
import threading
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
        self._lock = threading.Lock()
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self._conn = sqlite3.connect(self.db_path)
                self._conn.row_factory = sqlite3.Row
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "MemoryBackendStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init_schema(self) -> None:
        conn = self.connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS json_records (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              collection TEXT NOT NULL,
              record_id TEXT DEFAULT '',
              created_at TEXT DEFAULT '',
              payload_json TEXT NOT NULL
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_json_records_collection ON json_records(collection)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_json_records_record_id ON json_records(record_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_json_records_created_at ON json_records(created_at)")
        try:
            conn.execute("ALTER TABLE json_records ADD COLUMN type TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE json_records ADD COLUMN session_id TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE json_records ADD COLUMN project TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        conn.execute("CREATE INDEX IF NOT EXISTS idx_json_records_type ON json_records(type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_json_records_session_id ON json_records(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_json_records_project ON json_records(project)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS refs (
              ref_path TEXT PRIMARY KEY,
              created_at TEXT DEFAULT '',
              payload_json TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS index_mirror (
              name TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL,
              updated_at TEXT DEFAULT ''
            );
            """
        )
        conn.commit()

    def append_record(self, collection: str, payload: Dict[str, Any], record_id: str = "") -> None:
        payload_type = str(payload.get("type", "") or "")
        # Extract session_id/project: may be at top level or nested inside a "payload" sub-dict
        nested_payload = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
        payload_session_id = str(payload.get("session_id", "") or nested_payload.get("session_id", "") or "")
        payload_project = str(payload.get("project", "") or nested_payload.get("project", "") or "")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO json_records(collection, record_id, type, session_id, project, created_at, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collection,
                    record_id,
                    payload_type,
                    payload_session_id,
                    payload_project,
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
        project: str = "",
        payload_type: str = "",
        session_id: str = "",
        limit: int = 50,
    ) -> Dict[str, Any]:
        where = " FROM json_records WHERE 1=1"
        sql = "SELECT collection, record_id, type, session_id, project, created_at, payload_json" + where
        count_sql = "SELECT COUNT(*)" + where
        args: list[Any] = []
        if collection:
            sql += " AND collection = ?"
            count_sql += " AND collection = ?"
            args.append(collection)
        if record_id:
            sql += " AND record_id = ?"
            count_sql += " AND record_id = ?"
            args.append(record_id)
        if created_after:
            sql += " AND created_at >= ?"
            count_sql += " AND created_at >= ?"
            args.append(created_after)
        if payload_type:
            sql += " AND type = ?"
            count_sql += " AND type = ?"
            args.append(payload_type)
        if session_id:
            sql += " AND session_id = ?"
            count_sql += " AND session_id = ?"
            args.append(session_id)
        if project:
            sql += " AND project = ?"
            count_sql += " AND project = ?"
            args.append(project)
        count_args = list(args)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            total_count = int(conn.execute(count_sql, count_args).fetchone()[0])
            rows = conn.execute(sql, args).fetchall()
        records = [
            {
                "collection": str(row["collection"]),
                "record_id": str(row["record_id"]),
                "type": str(row["type"]),
                "session_id": str(row["session_id"]),
                "project": str(row["project"]),
                "created_at": str(row["created_at"]),
                "payload": json.loads(str(row["payload_json"])),
            }
            for row in rows
        ]
        return {"records": records, "count": len(records), "total_count": total_count}

    def upsert_index(self, name: str, payload: Any) -> None:
        from datetime import datetime, timezone
        updated_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO index_mirror(name, payload_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at
                """,
                (name, json.dumps(payload, ensure_ascii=False), updated_at),
            )

    def read_index(self, name: str, default: Any = None) -> Any:
        entry = self.read_index_entry(name)
        return entry["value"] if entry["found"] else default

    def read_index_entry(self, name: str) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT payload_json, updated_at FROM index_mirror WHERE name=?", (name,)).fetchone()
        if row is None:
            return {"found": False, "value": None, "updated_at": ""}
        try:
            return {"found": True, "value": json.loads(row["payload_json"]), "updated_at": str(row["updated_at"] or "")}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"found": False, "value": None, "updated_at": str(row["updated_at"] or ""), "error": "invalid_json"}

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
