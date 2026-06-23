"""Unified backend query layer — consolidates SQLite reads for consistency.

This module implements Phase C of NEXT_PHASE_MASTER_PLAN:
- Move more reads to backend
- Unify read_json*_prefer_backend strategy
- Better aggregation and filtering
- Single source of truth for high-frequency queries
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..memory_backend import MemoryBackendStore


class UnifiedBackendQuery:
    """Unified query layer over SQLite backend.

    Provides consistent access patterns for all high-frequency reads.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._store: Optional[MemoryBackendStore] = None

    @property
    def store(self) -> MemoryBackendStore:
        if self._store is None:
            self._store = MemoryBackendStore(self.db_path)
        return self._store

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    def __enter__(self) -> "UnifiedBackendQuery":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---- Index queries -------------------------------------------------------

    def read_index(self, name: str, default: Any = None) -> Any:
        """Read an index from the backend mirror."""
        return self.store.read_index(name, default)

    def read_index_list(self, name: str) -> List[Dict[str, Any]]:
        """Read an index that contains a list."""
        data = self.store.read_index(name, [])
        return data if isinstance(data, list) else []

    def read_index_dict(self, name: str) -> Dict[str, Any]:
        """Read an index that contains a dict."""
        data = self.store.read_index(name, {})
        return data if isinstance(data, dict) else {}

    # ---- Record queries ------------------------------------------------------

    def query_records(
        self,
        collection: str = "",
        record_id: str = "",
        created_after: str = "",
        project: str = "",
        payload_type: str = "",
        session_id: str = "",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Query records with flexible filtering."""
        return self.store.query_records(
            collection=collection,
            record_id=record_id,
            created_after=created_after,
            project=project,
            payload_type=payload_type,
            session_id=session_id,
            limit=limit,
        )

    def query_session_events(
        self,
        session_id: str = "",
        event_type: str = "",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query session events with filtering."""
        result = self.store.query_records(
            collection="session-events.jsonl",
            session_id=session_id,
            payload_type=event_type,
            limit=limit,
        )
        return result.get("records", [])

    def query_write_receipts(
        self,
        session_id: str = "",
        project: str = "",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query write receipts."""
        result = self.store.query_records(
            collection="write-receipts.jsonl",
            session_id=session_id,
            project=project,
            limit=limit,
        )
        return result.get("records", [])

    def query_token_gain(
        self,
        tool_name: str = "",
        budget: str = "",
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Query token gain records."""
        result = self.store.query_records(
            collection="token-gain-log.jsonl",
            limit=max(limit, 1000),
        )
        records = result.get("records", [])

        if tool_name:
            records = [r for r in records if r.get("payload", {}).get("tool_name") == tool_name]
        if budget:
            records = [r for r in records if r.get("payload", {}).get("budget") == budget]

        return records[-limit:]

    # ---- Ref queries ---------------------------------------------------------

    def query_refs(
        self,
        ref_path: str = "",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Query refs with optional path filter."""
        return self.store.query_refs(ref_path=ref_path, limit=limit)

    def get_ref(self, ref_path: str) -> Optional[Dict[str, Any]]:
        """Get a single ref by path."""
        result = self.store.query_refs(ref_path=ref_path, limit=1)
        refs = result.get("refs", [])
        return refs[0] if refs else None

    # ---- Aggregation queries -------------------------------------------------

    def aggregate_by_collection(
        self,
        collection: str,
        group_by: str = "type",
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Aggregate records by a field."""
        result = self.store.query_records(collection=collection, limit=limit)
        records = result.get("records", [])

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for record in records:
            payload = record.get("payload", {})
            key = str(payload.get(group_by, "unknown"))
            groups.setdefault(key, []).append(record)

        return {
            "collection": collection,
            "group_by": group_by,
            "groups": {k: len(v) for k, v in groups.items()},
            "total_records": len(records),
        }

    def aggregate_by_session(
        self,
        collection: str = "session-events.jsonl",
        limit: int = 500,
    ) -> Dict[str, Any]:
        """Aggregate records by session."""
        result = self.store.query_records(collection=collection, limit=limit)
        records = result.get("records", [])

        sessions: Dict[str, List[Dict[str, Any]]] = {}
        for record in records:
            session_id = record.get("session_id", "unknown")
            sessions.setdefault(session_id, []).append(record)

        return {
            "collection": collection,
            "session_count": len(sessions),
            "sessions": {
                sid: {
                    "event_count": len(events),
                    "first_event": events[0].get("created_at", "") if events else "",
                    "last_event": events[-1].get("created_at", "") if events else "",
                }
                for sid, events in sessions.items()
            },
        }

    def aggregate_by_project(
        self,
        collection: str = "write-receipts.jsonl",
        limit: int = 500,
    ) -> Dict[str, Any]:
        """Aggregate records by project."""
        result = self.store.query_records(collection=collection, limit=limit)
        records = result.get("records", [])

        projects: Dict[str, List[Dict[str, Any]]] = {}
        for record in records:
            project = record.get("project", "unknown")
            projects.setdefault(project, []).append(record)

        return {
            "collection": collection,
            "project_count": len(projects),
            "projects": {
                proj: {
                    "record_count": len(recs),
                    "latest": recs[0].get("created_at", "") if recs else "",
                }
                for proj, recs in projects.items()
            },
        }

    # ---- Statistics ----------------------------------------------------------

    def get_backend_stats(self) -> Dict[str, Any]:
        """Get overall backend statistics."""
        return self.store.stats()

    def get_collection_stats(self, collection: str) -> Dict[str, Any]:
        """Get stats for a specific collection."""
        result = self.store.query_records(collection=collection, limit=1)
        records = result.get("records", [])

        return {
            "collection": collection,
            "has_records": len(records) > 0,
            "sample_record": records[0] if records else None,
        }

    # ---- Timeline queries ----------------------------------------------------

    def query_timeline(
        self,
        session_id: str = "",
        task_id: str = "",
        event_type: str = "",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query timeline events with filtering."""
        records = self.query_session_events(session_id=session_id, limit=limit * 2)

        if task_id:
            records = [
                r for r in records
                if r.get("payload", {}).get("task_id") == task_id
                or r.get("task_id") == task_id
            ]

        if event_type:
            records = [
                r for r in records
                if r.get("type", "") == event_type
                or r.get("payload", {}).get("event_type") == event_type
            ]

        return records[:limit]

    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Get summary of a session's activity."""
        events = self.query_session_events(session_id=session_id, limit=500)

        if not events:
            return {"session_id": session_id, "found": False}

        event_types: Dict[str, int] = {}
        for event in events:
            etype = event.get("type", "unknown")
            event_types[etype] = event_types.get(etype, 0) + 1

        return {
            "session_id": session_id,
            "found": True,
            "event_count": len(events),
            "event_types": event_types,
            "first_event": events[-1].get("created_at", ""),
            "last_event": events[0].get("created_at", ""),
        }

    # ---- Health checks -------------------------------------------------------

    def check_health(self) -> Dict[str, Any]:
        """Check backend health and data consistency."""
        stats = self.get_backend_stats()

        issues = []
        if not stats.get("collections"):
            issues.append("No collections found in backend")

        # Check for expected collections
        expected = {"session-events.jsonl", "write-receipts.jsonl", "token-gain-log.jsonl"}
        actual = set(stats.get("collections", {}).keys())
        missing = expected - actual
        if missing:
            issues.append(f"Missing collections: {missing}")

        return {
            "healthy": len(issues) == 0,
            "db_path": str(self.db_path),
            "stats": stats,
            "issues": issues,
        }

    def check_consistency(
        self,
        workspace_dir: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """Compare JSONL file counts vs SQLite record counts per collection.

        Reports divergences between the file system and the backend mirror.
        """
        stats = self.get_backend_stats()
        backend_collections = stats.get("collections", {})
        comparisons: List[Dict[str, Any]] = []
        divergences: List[str] = []

        if workspace_dir is None:
            # Infer from db_path: db is at <workspace>/memory/memory.db
            workspace_dir = self.db_path.parent.parent
        workspace_dir = Path(workspace_dir)
        memory_dir = workspace_dir / "memory"

        for collection, backend_count in backend_collections.items():
            file_path = memory_dir / collection
            file_count = 0
            if file_path.exists():
                try:
                    with open(file_path, encoding="utf-8") as f:
                        file_count = sum(1 for line in f if line.strip())
                except Exception:
                    file_count = -1  # unreadable

            entry = {
                "collection": collection,
                "backend_count": backend_count,
                "file_count": file_count,
            }
            comparisons.append(entry)

            if file_count >= 0 and backend_count != file_count:
                divergences.append(
                    f"{collection}: backend={backend_count}, file={file_count}"
                )

        return {
            "consistent": len(divergences) == 0,
            "comparisons": comparisons,
            "divergences": divergences,
        }
