from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from filelock import FileLock

from .memory_backend import MemoryBackendStore


def _safe_path(base: Path, name: str) -> Path:
    resolved_base = base.resolve()
    candidate = (resolved_base / name).resolve()
    if not candidate.is_relative_to(resolved_base):
        raise ValueError(f"invalid path: {name}")
    return candidate


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
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_json(self, name: str, default: Any) -> Any:
        path = self.index_dir / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return default

    def append_jsonl(self, name: str, item: Dict[str, Any]) -> None:
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

    def read_jsonl(self, name: str, limit: int = 50) -> List[Dict[str, Any]]:
        path = self.memory_dir / name
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
        return rows

    def find_jsonl(self, name: str, predicate, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self.read_jsonl(name, limit=5000)
        matched = [row for row in rows if predicate(row)]
        return matched[-limit:]

    def write_memory_ref_json(self, name: str, data: Any) -> str:
        path = _safe_path(self.memory_dir, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_file)):
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        ref = str(path.relative_to(self.base_dir))
        try:
            self.memory_backend().upsert_ref(ref, data)
        except Exception:
            pass
        return ref

    def read_memory_ref_json(self, ref: str, default: Any = None) -> Any:
        default = {} if default is None else default
        normalized = ref.replace("\\", "/").lstrip("/")
        if normalized.startswith("memory/"):
            normalized = normalized[len("memory/") :]
        path = _safe_path(self.memory_dir, normalized)
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return default

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

    def memory_backend_stats(self) -> Dict[str, Any]:
        return self.memory_backend().stats()

    def memory_backend_query_records(self, *, collection: str = "", record_id: str = "", created_after: str = "", limit: int = 50) -> Dict[str, Any]:
        return self.memory_backend().query_records(collection=collection, record_id=record_id, created_after=created_after, limit=limit)

    def memory_backend_query_refs(self, *, ref_path: str = "", limit: int = 50) -> Dict[str, Any]:
        return self.memory_backend().query_refs(ref_path=ref_path, limit=limit)

    def read_jsonl_via_backend(self, name: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.memory_backend_query_records(collection=name, limit=limit).get("records", [])
        return [item.get("payload", {}) for item in rows if isinstance(item.get("payload", {}), dict)]

    def find_jsonl_via_backend(self, name: str, predicate, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self.read_jsonl_via_backend(name, limit=5000)
        matched = [row for row in rows if predicate(row)]
        return matched[-limit:]

    def _infer_record_id(self, collection: str, item: Dict[str, Any]) -> str:
        if collection == "write-receipts.jsonl":
            return str(item.get("receipt_id", "") or item.get("receipt_ref", "") or "")
        if collection == "session-events.jsonl":
            return str(item.get("session_id", "") or "") + ":" + str(item.get("event_type", "") or "")
        if collection == "session-summaries.jsonl":
            return str(item.get("session_id", "") or "")
        if collection == "handoff-history.jsonl":
            return str(item.get("session_id", "") or "") + ":" + str(item.get("normalized_model", "") or "")
        if collection == "cross-service-task-memory.jsonl":
            return str(item.get("task", "") or "")
        return ""
