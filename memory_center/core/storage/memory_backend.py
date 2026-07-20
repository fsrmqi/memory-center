from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class MemoryBackendStore:
    """访问 ``graph.db`` 中的运行记录、审计流和引用读模型。

    JSON/JSONL 是便于检查与导出的投影；运行时查询与状态判定只读取 SQLite。
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
                # Apply the same PRAGMA profile as GraphStore so memory
                # writes also benefit from WAL + large cache + temp_store
                # in memory. Without this, status/sniff queries hit cold
                # pages on cold start.
                from .pragmas import apply_pragmas

                apply_pragmas(self._conn)
                self._conn.row_factory = sqlite3.Row
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> MemoryBackendStore:
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
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS assertions (
              assertion_id TEXT PRIMARY KEY,
              subject_id TEXT NOT NULL,
              predicate TEXT NOT NULL,
              object_id TEXT NOT NULL,
              status TEXT NOT NULL,
              generation TEXT NOT NULL,
              valid_from TEXT NOT NULL,
              valid_to TEXT DEFAULT '',
              event_at TEXT DEFAULT '',
              observed_at TEXT DEFAULT '',
              provenance_kind TEXT DEFAULT '',
              relation_mode TEXT DEFAULT '',
              evidence_refs_json TEXT DEFAULT '[]',
              source_file TEXT DEFAULT '',
              target_file TEXT DEFAULT '',
              source_project TEXT DEFAULT '',
              target_project TEXT DEFAULT '',
              payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_assertions_subject_active
              ON assertions(subject_id, status, valid_to);
            CREATE INDEX IF NOT EXISTS idx_assertions_object_active
              ON assertions(object_id, status, valid_to);
            CREATE INDEX IF NOT EXISTS idx_assertions_relation_active
              ON assertions(subject_id, predicate, object_id, valid_to);
            """
        )
        for column in (
            "source_file", "target_file", "source_project", "target_project",
            "event_at", "observed_at", "provenance_kind", "relation_mode", "evidence_refs_json",
        ):
            try:
                conn.execute(f"ALTER TABLE assertions ADD COLUMN {column} TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assertions_source_file_active ON assertions(source_file, valid_to)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assertions_target_file_active ON assertions(target_file, valid_to)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assertions_source_project_active ON assertions(source_project, valid_to)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assertions_target_project_active ON assertions(target_project, valid_to)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assertions_event_at ON assertions(event_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assertions_observed_at ON assertions(observed_at)")
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

    def append_record(self, collection: str, payload: dict[str, Any], record_id: str = "") -> None:
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

    def append_records(self, collection: str, payloads: list[dict[str, Any]], record_ids: list[str] | None = None) -> None:
        """Batch variant used by high-volume sidecars such as assertions."""
        if not payloads:
            return
        ids = record_ids or [""] * len(payloads)
        rows = []
        for payload, record_id in zip(payloads, ids, strict=True):
            nested = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
            rows.append((
                collection,
                record_id,
                str(payload.get("type", "") or ""),
                str(payload.get("session_id", "") or nested.get("session_id", "") or ""),
                str(payload.get("project", "") or nested.get("project", "") or ""),
                str(payload.get("created_at", "") or ""),
                json.dumps(payload, ensure_ascii=False),
            ))
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO json_records(collection, record_id, type, session_id, project, created_at, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def upsert_assertions(self, assertions: list[dict[str, Any]]) -> int:
        """Publish a batch of static assertions without loading historical rows."""
        if not assertions:
            return 0
        rows = [
            (
                row["assertion_id"], row["subject_id"], row["predicate"], row["object_id"],
                row["status"], row["generation"], row["valid_from"], row.get("valid_to", ""),
                row.get("event_at", row["valid_from"]), row.get("observed_at", row["valid_from"]),
                row.get("provenance_kind", row.get("source_kind", "")), row.get("relation_mode", ""),
                json.dumps(row.get("evidence_refs", []), ensure_ascii=False),
                row.get("source_file", ""), row.get("target_file", ""),
                row.get("source_project", ""), row.get("target_project", ""),
                json.dumps(row, ensure_ascii=False),
            )
            for row in assertions
        ]
        with self.connect() as conn:
            for row in assertions:
                conn.execute(
                    """
                    UPDATE assertions SET valid_to=?, status='SUPERSEDED'
                    WHERE subject_id=? AND predicate=? AND object_id=?
                      AND valid_to='' AND generation<>?
                    """,
                    (row["valid_from"], row["subject_id"], row["predicate"], row["object_id"], row["generation"]),
                )
            conn.executemany(
                """
                INSERT INTO assertions(assertion_id, subject_id, predicate, object_id, status, generation, valid_from, valid_to, event_at, observed_at, provenance_kind, relation_mode, evidence_refs_json, source_file, target_file, source_project, target_project, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(assertion_id) DO NOTHING
                """,
                rows,
            )
        return len(rows)

    def supersede_assertions_in_scope(
        self,
        *,
        paths: list[str] | None = None,
        projects: list[str] | None = None,
        generation: str,
        valid_to: str,
    ) -> int:
        """Close only the active facts affected by a partial reindex scope."""
        path_scope = sorted({str(path).replace("\\", "/").lstrip("/") for path in paths or [] if path})
        project_scope = sorted({str(project) for project in projects or [] if project})
        clauses: list[str] = []
        args: list[Any] = []
        if path_scope:
            placeholders = ",".join("?" for _ in path_scope)
            clauses.append(f"(source_file IN ({placeholders}) OR target_file IN ({placeholders}))")
            args.extend(path_scope * 2)
        if project_scope:
            placeholders = ",".join("?" for _ in project_scope)
            clauses.append(f"(source_project IN ({placeholders}) OR target_project IN ({placeholders}))")
            args.extend(project_scope * 2)
        if not clauses:
            return 0
        with self.connect() as conn:
            return int(
                conn.execute(
                    f"""
                    UPDATE assertions SET valid_to=?, status='SUPERSEDED'
                    WHERE valid_to='' AND generation<>? AND ({' OR '.join(clauses)})
                    """,
                    [valid_to, generation, *args],
                ).rowcount
            )

    def assertion_summary(self, *, limit: int = 20) -> dict[str, Any]:
        with self.connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM assertions WHERE valid_to='' ").fetchone()[0])
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count FROM assertions
                WHERE valid_to='' GROUP BY status ORDER BY status
                """
            ).fetchall()
            recent = conn.execute(
                """
                SELECT status, payload_json FROM assertions WHERE valid_to=''
                ORDER BY valid_from DESC, assertion_id DESC LIMIT ?
                """,
                (min(max(1, limit), 100),),
            ).fetchall()
        return {
            "active": total,
            "by_status": {str(row["status"]): int(row["count"]) for row in rows},
            "recent": [{**json.loads(str(row["payload_json"])), "status": str(row["status"])} for row in recent],
        }

    def query_assertions(self, *, as_of_generation: str = "", as_of_time: str = "", time_axis: str = "valid", limit: int = 20) -> list[dict[str, Any]]:
        """Read a bounded historical assertion slice; defaults to active facts."""
        clauses = ["1=1"]
        args: list[Any] = []
        if as_of_generation:
            clauses.append("generation = ?")
            args.append(as_of_generation)
        elif as_of_time:
            if time_axis == "event":
                clauses.append("event_at <= ?")
                args.append(as_of_time)
            elif time_axis == "observed":
                clauses.append("observed_at <= ?")
                args.append(as_of_time)
            else:
                clauses.extend(["valid_from <= ?", "(valid_to = '' OR valid_to > ?)"])
                args.extend([as_of_time, as_of_time])
        else:
            clauses.append("valid_to = ''")
        args.append(min(max(1, limit), 500))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT status, payload_json FROM assertions WHERE {' AND '.join(clauses)} ORDER BY valid_from DESC, assertion_id DESC LIMIT ?",
                args,
            ).fetchall()
        result = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            payload["status"] = str(row["status"])
            result.append(payload)
        return result

    def set_assertion_status(self, assertion_id: str, status: str, *, verification_ref: str = "") -> bool:
        """Update the active read model while callers preserve the audit event."""
        allowed = {"VERIFIED", "REJECTED", "EXTRACTED", "INFERRED", "AMBIGUOUS"}
        if status not in allowed:
            raise ValueError(f"unsupported assertion status: {status}")
        with self.connect() as conn:
            row = conn.execute("SELECT payload_json FROM assertions WHERE assertion_id=?", (assertion_id,)).fetchone()
            if row is None:
                return False
            payload = json.loads(str(row["payload_json"]))
            payload["status"] = status
            if verification_ref:
                payload["verification_ref"] = verification_ref[:240]
            conn.execute(
                "UPDATE assertions SET status=?, payload_json=? WHERE assertion_id=?",
                (status, json.dumps(payload, ensure_ascii=False), assertion_id),
            )
        return True

    def assertion_statuses(self, assertion_ids: list[str]) -> dict[str, str]:
        ids = [item for item in dict.fromkeys(assertion_ids) if item][:120]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT assertion_id, status FROM assertions WHERE assertion_id IN ({placeholders})", ids
            ).fetchall()
        return {str(row["assertion_id"]): str(row["status"]) for row in rows}

    def assertion_by_id(self, assertion_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT status, payload_json FROM assertions WHERE assertion_id=?", (assertion_id,)).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        payload["status"] = str(row["status"])
        return payload

    def mark_assertions_stale(self, paths: list[str]) -> int:
        """Mark only assertions whose persisted source path is dirty."""
        normalized = sorted({str(path).replace("\\", "/").lstrip("/") for path in paths if path})[:200]
        if not normalized:
            return 0
        placeholders = ",".join("?" for _ in normalized)
        with self.connect() as conn:
            return int(conn.execute(
                f"""
                UPDATE assertions SET status='STALE'
                WHERE valid_to='' AND status<>'STALE'
                  AND (source_file IN ({placeholders}) OR target_file IN ({placeholders}))
                """,
                normalized * 2,
            ).rowcount)

    def assertion_diagnostics(self, active_generation: str = "") -> dict[str, int]:
        """Small aggregate checks used only by explicit runtime inspection."""
        with self.connect() as conn:
            verified_without_source = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM assertions
                    WHERE status='VERIFIED' AND (payload_json NOT LIKE '%verification%' AND payload_json NOT LIKE '%evidence_ref%')
                    """
                ).fetchone()[0]
            )
            old_generation = 0
            if active_generation:
                old_generation = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM assertions WHERE valid_to='' AND generation<>?", (active_generation,)
                    ).fetchone()[0]
                )
        return {"verified_without_source": verified_without_source, "active_old_generation": old_generation}

    def prune_closed_assertions(self, *, valid_before: str, max_closed: int) -> dict[str, int]:
        """Retain all active facts while bounding closed static assertion history."""
        with self.connect() as conn:
            expired = int(
                conn.execute("DELETE FROM assertions WHERE valid_to<>'' AND valid_to < ?", (valid_before,)).rowcount
            )
            total_closed = int(conn.execute("SELECT COUNT(*) FROM assertions WHERE valid_to<>''").fetchone()[0])
            overflow = max(0, total_closed - max_closed)
            if overflow:
                conn.execute(
                    """
                    DELETE FROM assertions WHERE assertion_id IN (
                        SELECT assertion_id FROM assertions WHERE valid_to<>'' ORDER BY valid_to ASC LIMIT ?
                    )
                    """,
                    (overflow,),
                )
        return {"expired": expired, "overflow": overflow}

    def prune_records(self, collection: str, *, created_before: str, max_records: int) -> dict[str, int]:
        """删除过期记录，并仅保留指定集合中最新的有限条目。"""
        if max_records < 1:
            raise ValueError("max_records must be at least 1")
        with self.connect() as conn:
            expired = conn.execute(
                "DELETE FROM json_records WHERE collection = ? AND created_at < ?",
                (collection, created_before),
            ).rowcount
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM json_records WHERE collection = ?",
                    (collection,),
                ).fetchone()[0]
            )
            overflow = max(0, total - max_records)
            if overflow:
                conn.execute(
                    """
                    DELETE FROM json_records
                    WHERE id IN (
                        SELECT id FROM json_records
                        WHERE collection = ?
                        ORDER BY id ASC
                        LIMIT ?
                    )
                    """,
                    (collection, overflow),
                )
            return {"expired": max(0, expired), "overflow": overflow, "kept": total - overflow}

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

    def stats(self) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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

    def read_index_entry(self, name: str) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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
