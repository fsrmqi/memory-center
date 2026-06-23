from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generic, TypeVar

from filelock import FileLock

from .memory_backend import MemoryBackendStore

_MISSING = object()
T = TypeVar("T")
_JSON_FILE_CACHE: dict[tuple[str, int, int], Any] = {}


@dataclass(frozen=True)
class ReadResult(Generic[T]):
    value: T
    source: str
    fallback_used: bool = False
    fallback_reason: str = ""
    consistency_status: str = "unknown"

    def diagnostics(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "consistency_status": self.consistency_status,
        }


def _safe_path(base: Path, name: str) -> Path:
    resolved_base = base.resolve()
    candidate = (resolved_base / name).resolve()
    if not candidate.is_relative_to(resolved_base):
        raise ValueError(f"invalid path: {name}")
    return candidate


def _read_json_file_cached(path: Path) -> Any:
    stat = path.stat()
    cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _JSON_FILE_CACHE.get(cache_key, _MISSING)
    if cached is not _MISSING:
        return cached
    value = json.loads(path.read_text(encoding="utf-8"))
    _JSON_FILE_CACHE[cache_key] = value
    return value


def _drop_json_cache(path: Path) -> None:
    path_text = str(path)
    stale_keys = [key for key in _JSON_FILE_CACHE if key[0] == path_text]
    for key in stale_keys:
        _JSON_FILE_CACHE.pop(key, None)


class WorkspaceStore:
    def __init__(self, workspace_file: str | Path):
        self.workspace_file = Path(workspace_file).expanduser().resolve()
        self.base_dir = self.workspace_file.parent
        self.index_dir = self.base_dir / "index"
        self.rules_dir = self.base_dir / "rules"
        self.memory_dir = self.base_dir / "memory"
        self.refs_dir = self.memory_dir / "refs"
        self.artifacts_dir = self.base_dir / "artifacts"
        self.instructions_dir = self.base_dir / "instructions"
        self.graph_dir = self.base_dir / "graph"
        self.lock_file = self.base_dir / "store.lock"
        self._memory_backend: MemoryBackendStore | None = None
        for p in [self.index_dir, self.rules_dir, self.memory_dir, self.refs_dir, self.artifacts_dir, self.instructions_dir, self.graph_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, data: Any) -> None:
        path = self.index_dir / name
        with FileLock(str(self.lock_file)):
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            _drop_json_cache(path)
            try:
                self.memory_backend().upsert_index(name, data)
            except Exception:
                pass

    def read_json(self, name: str, default: Any) -> Any:
        path = self.index_dir / name
        if not path.exists():
            return default
        try:
            return _read_json_file_cached(path)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Corrupt JSON file — try backend before falling back to default
            backend_val = self.memory_backend().read_index(name)
            if backend_val is not None:
                return backend_val
            return default

    def append_jsonl(self, name: str, item: dict[str, Any]) -> None:
        path = self.memory_dir / name
        item = dict(item)
        item.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        with FileLock(str(self.lock_file)):
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            try:
                self.memory_backend().append_record(name, item, record_id=self._infer_record_id(name, item))
            except Exception:
                pass

    def read_jsonl(self, name: str, limit: int = 50) -> list[dict[str, Any]]:
        path = self.memory_dir / name
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
        return rows

    def find_jsonl(self, name: str, predicate, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.read_jsonl(name, limit=5000)
        matched = [row for row in rows if predicate(row)]
        return matched[-limit:]

    def read_jsonl_prefer_backend(self, name: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.read_jsonl_observed(name, limit=limit).value

    def find_jsonl_prefer_backend(self, name: str, predicate, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.find_jsonl_via_backend(name, predicate, limit=limit)
        return rows or self.find_jsonl(name, predicate, limit=limit)

    def write_memory_ref_json(self, name: str, data: Any) -> str:
        path = _safe_path(self.memory_dir, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_file)):
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            ref = str(path.relative_to(self.base_dir))
            try:
                self.memory_backend().upsert_ref(ref, data)
            except Exception:
                pass
        return ref

    def read_memory_ref_json(self, ref: str, default: Any = _MISSING) -> Any:
        normalized = ref.replace("\\", "/").lstrip("/")
        if normalized.startswith("memory/"):
            normalized = normalized[len("memory/") :]
        path = _safe_path(self.memory_dir, normalized)
        if not path.exists():
            return {} if default is _MISSING else default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return {} if default is _MISSING else default

    def write_artifact(self, name: str, content: str) -> Path:
        path = _safe_path(self.artifacts_dir, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_file)):
            path.write_text(content, encoding="utf-8")
        return path

    def read_artifact(self, name: str, default: str = "") -> str:
        path = _safe_path(self.artifacts_dir, name)
        if not path.exists():
            return default
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return default

    def append_artifact(self, name: str, content: str) -> Path:
        path = _safe_path(self.artifacts_dir, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_file)):
            with path.open("a", encoding="utf-8") as f:
                f.write(content)
        return path

    def artifact_exists(self, name: str) -> bool:
        return _safe_path(self.artifacts_dir, name).exists()

    @property
    def graph_db_path(self) -> Path:
        return self.graph_dir / "graph.db"

    @property
    def memory_db_path(self) -> Path:
        return self.memory_dir / "memory.db"

    def memory_backend(self) -> MemoryBackendStore:
        if self._memory_backend is None:
            self._memory_backend = MemoryBackendStore(self.memory_db_path)
        return self._memory_backend

    def memory_backend_stats(self) -> dict[str, Any]:
        return self.memory_backend().stats()

    def memory_backend_query_records(self, *, collection: str = "", record_id: str = "", created_after: str = "", project: str = "", payload_type: str = "", session_id: str = "", limit: int = 50) -> dict[str, Any]:
        return self.memory_backend().query_records(collection=collection, record_id=record_id, created_after=created_after, project=project, payload_type=payload_type, session_id=session_id, limit=limit)

    def read_json_prefer_backend(self, name: str, default: Any) -> Any:
        """Read deterministic index on the hot path.

        The public diagnostics API still uses read_json_observed() for backend/file
        consistency checks. Hot query paths avoid that dual-read cost and use the
        file as the current fact source, with backend fallback when the file is
        missing or corrupt.
        """
        path = self.index_dir / name
        if path.exists():
            return self.read_json(name, default)
        try:
            backend_entry = self.memory_backend().read_index_entry(name)
        except Exception:
            return default
        if backend_entry.get("found"):
            return backend_entry.get("value")
        return default

    def read_json_observed(self, name: str, default: Any) -> ReadResult[Any]:
        path = self.index_dir / name
        file_exists = path.exists()
        file_value = self.read_json(name, default) if file_exists else default
        try:
            backend_entry = self.memory_backend().read_index_entry(name)
        except Exception as exc:
            return ReadResult(
                file_value,
                "file" if file_exists else "default",
                fallback_used=True,
                fallback_reason=f"backend_unavailable:{type(exc).__name__}",
                consistency_status="backend_unavailable",
            )
        if not backend_entry.get("found"):
            return ReadResult(
                file_value,
                "file" if file_exists else "default",
                fallback_used=file_exists,
                fallback_reason="backend_missing",
                consistency_status="file_only" if file_exists else "missing",
            )
        backend_value = backend_entry.get("value")
        if not file_exists:
            return ReadResult(backend_value, "backend", consistency_status="backend_only")
        if backend_value == file_value:
            return ReadResult(backend_value, "backend", consistency_status="consistent")
        return ReadResult(
            file_value,
            "file",
            fallback_used=True,
            fallback_reason="backend_stale",
            consistency_status="diverged",
        )

    def read_jsonl_observed(self, name: str, limit: int = 50) -> ReadResult[list[dict[str, Any]]]:
        file_path = self.memory_dir / name
        file_exists = file_path.exists()
        file_rows = self.read_jsonl(name, limit=limit)
        try:
            query = self.memory_backend_query_records(collection=name, limit=limit)
            records = list(reversed(query.get("records", [])))
            backend_rows = [item.get("payload", {}) for item in records if isinstance(item.get("payload"), dict)]
            total_count = int(query.get("total_count", len(backend_rows)) or 0)
        except Exception as exc:
            return ReadResult(
                file_rows,
                "file" if file_exists else "default",
                fallback_used=True,
                fallback_reason=f"backend_unavailable:{type(exc).__name__}",
                consistency_status="backend_unavailable",
            )
        if total_count == 0:
            return ReadResult(
                file_rows,
                "file" if file_exists else "default",
                fallback_used=file_exists,
                fallback_reason="backend_missing",
                consistency_status="file_only" if file_exists else "missing",
            )
        if not file_exists:
            return ReadResult(backend_rows, "backend", consistency_status="backend_only")
        expected_count = len(self.read_jsonl(name, limit=500000))
        if total_count < expected_count:
            return ReadResult(file_rows, "file", True, "backend_partial", "diverged")
        if backend_rows == file_rows:
            return ReadResult(backend_rows, "backend", consistency_status="consistent")
        return ReadResult(file_rows, "file", True, "backend_stale", "diverged")

    def memory_backend_query_refs(self, *, ref_path: str = "", limit: int = 50) -> dict[str, Any]:
        return self.memory_backend().query_refs(ref_path=ref_path, limit=limit)

    def read_jsonl_via_backend(self, name: str, limit: int = 50, session_id: str = "") -> list[dict[str, Any]]:
        rows = self.memory_backend_query_records(collection=name, session_id=session_id, limit=limit).get("records", [])
        return [item.get("payload", {}) for item in reversed(rows) if isinstance(item.get("payload"), dict)]

    def find_jsonl_via_backend(self, name: str, predicate, limit: int = 200, session_id: str = "") -> list[dict[str, Any]]:
        rows = self.read_jsonl_via_backend(name, limit=5000, session_id=session_id)
        matched = [row for row in rows if predicate(row)]
        return matched[-limit:]

    def _infer_record_id(self, collection: str, item: dict[str, Any]) -> str:
        if collection == "write-receipts.jsonl":
            return str(item.get("receipt_id", "") or item.get("receipt_ref", "") or "")
        if collection == "session-events.jsonl":
            return str(item.get("session_id", "") or "") + ":" + str(item.get("event_type", "") or "")
        if collection == "session-summaries.jsonl":
            return str(item.get("session_id", "") or "")
        if collection == "handoff-history.jsonl":
            return str(item.get("session_id", "") or "") + ":" + str(item.get("normalized_model", "") or "") + ":" + str(item.get("created_at", "") or "")
        if collection == "cross-service-task-memory.jsonl":
            return str(item.get("task", "") or "")
        if collection == "artifact-write-audit.jsonl":
            return str(item.get("created_at", "") or "") + ":" + str(item.get("artifact_name", "") or "")
        if collection == "token-gain-log.jsonl":
            return str(item.get("tool_name", "") or "") + ":" + str(item.get("created_at", "") or "")
        # Generic fallback: use first available identifier field
        for key in ("id", "task", "session_id", "receipt_id", "name"):
            val = item.get(key)
            if val:
                return str(val)
        return ""
