from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from memory_center.core.storage.runtime import RuntimeStore

_MISSING = object()
_JSON_FILE_CACHE: dict[tuple[str, int, int], Any] = {}
_MCP_INVOCATIONS_FILE = "mcp-invocations.jsonl"
_MCP_AUDIT_RETENTION_DAYS = 30
_MCP_AUDIT_MAX_RECORDS = 100_000

# These payloads are large, deterministic runtime indexes. SQLite is their
# canonical store, so a second JSON copy only adds rebuild I/O and disk usage.
RUNTIME_ONLY_INDEXES = frozenset(
    {
        "file-index.json",
        "java-symbol-index.json",
        "api-index.json",
        "feign-index.json",
        "mq-index.json",
        "config-index.json",
        "service-topology.json",
        "contract-snapshot.json",
        "contract-diff.json",
        "semantic-node-index.json",
    }
)


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


def _parse_record_timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mcp_audit_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=_MCP_AUDIT_RETENTION_DAYS)).isoformat()


def _read_tail_lines(path: Path, limit: int) -> list[str]:
    """读取 JSONL 末尾有限行，避免审计读取扫描完整大文件。"""
    if limit <= 0:
        return []
    block_size = 64 * 1024
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        blocks: list[bytes] = []
        newlines = 0
        while position > 0 and newlines <= limit:
            read_size = min(block_size, position)
            position -= read_size
            handle.seek(position)
            block = handle.read(read_size)
            blocks.append(block)
            newlines += block.count(b"\n")
    return b"".join(reversed(blocks)).decode("utf-8", errors="replace").splitlines()[-limit:]


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
        self.index_lock_file = self.base_dir / "index.lock"
        self.artifact_lock_file = self.base_dir / "artifacts.lock"
        self.audit_lock_file = self.base_dir / "audit.lock"
        self.reindex_lock_file = self.base_dir / "reindex.lock"
        self._memory_backend: RuntimeStore | None = None
        for p in [self.index_dir, self.rules_dir, self.memory_dir, self.refs_dir, self.artifacts_dir, self.instructions_dir, self.graph_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, data: Any) -> None:
        path = self.index_dir / name
        with FileLock(str(self.index_lock_file)):
            self.memory_backend().upsert_index(name, data)
            if name in RUNTIME_ONLY_INDEXES:
                path.unlink(missing_ok=True)
            else:
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            _drop_json_cache(path)

    def read_json(self, name: str, default: Any) -> Any:
        if name in RUNTIME_ONLY_INDEXES:
            return self.read_json_prefer_backend(name, default)
        path = self.index_dir / name
        if not path.exists():
            return default
        try:
            return _read_json_file_cached(path)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return default

    def append_jsonl(self, name: str, item: dict[str, Any]) -> dict[str, Any]:
        path = self.memory_dir / name
        item = dict(item)
        item.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        with FileLock(str(self.audit_lock_file)):
            self.memory_backend().append_record(name, item, record_id=self._infer_record_id(name, item))
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def append_jsonl_batch(self, name: str, items: list[dict[str, Any]]) -> int:
        """Append a collection with one workspace lock and one SQLite transaction."""
        if not items:
            return 0
        path = self.memory_dir / name
        now = datetime.now(timezone.utc).isoformat()
        rows = [dict(item, created_at=item.get("created_at") or now) for item in items]
        with FileLock(str(self.audit_lock_file)):
            self.memory_backend().append_records(
                name,
                rows,
                record_ids=[self._infer_record_id(name, row) for row in rows],
            )
            with path.open("a", encoding="utf-8") as handle:
                handle.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        return len(rows)

    def prune_jsonl(self, name: str, *, created_before: datetime, max_records: int) -> dict[str, int]:
        """删除过期 JSONL 记录并限制条数，同时清理 SQLite 镜像。"""
        if max_records < 1:
            raise ValueError("max_records must be at least 1")
        path = self.memory_dir / name
        cutoff = created_before.astimezone(timezone.utc)
        kept_lines: deque[str] = deque(maxlen=max_records)
        total = expired = invalid = overflow = 0
        with FileLock(str(self.artifact_lock_file)):
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    total += 1
                    try:
                        item = json.loads(line)
                        created_at = _parse_record_timestamp(item.get("created_at", ""))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        invalid += 1
                        continue
                    if created_at < cutoff:
                        expired += 1
                        continue
                    kept_lines.append(line)
                overflow = max(0, total - expired - invalid - len(kept_lines))
                if expired or invalid or overflow:
                    content = "\n".join(kept_lines)
                    path.write_text(content + ("\n" if content else ""), encoding="utf-8")
            self.memory_backend().prune_records(
                name,
                created_before=cutoff.isoformat(),
                max_records=max_records,
            )
        return {
            "total": total,
            "expired": expired,
            "invalid": invalid,
            "overflow": overflow,
            "kept": len(kept_lines),
        }

    def read_jsonl(self, name: str, limit: int = 50) -> list[dict[str, Any]]:
        path = self.memory_dir / name
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        # MCP audit exports may be physically compacted in a background thread.
        # Read a bounded tail and enforce the retention window immediately so a
        # caller never observes expired rows while compaction is in flight.
        tail_limit = max(1, limit)
        cutoff = ""
        if name == _MCP_INVOCATIONS_FILE:
            tail_limit = max(tail_limit, min(4096, tail_limit * 8))
            cutoff = _mcp_audit_cutoff()
        for line in _read_tail_lines(path, tail_limit):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if cutoff and str(item.get("created_at", "") or "") < cutoff:
                    continue
                rows.append(item)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
        return rows[-limit:]

    def find_jsonl(self, name: str, predicate, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.read_jsonl(name, limit=5000)
        matched = [row for row in rows if predicate(row)]
        return matched[-limit:]

    def read_jsonl_prefer_backend(self, name: str, limit: int = 50) -> list[dict[str, Any]]:
        """Read runtime memory records from the canonical SQLite store."""
        return self.read_jsonl_via_backend(name, limit=limit)

    def find_jsonl_prefer_backend(self, name: str, predicate, limit: int = 200) -> list[dict[str, Any]]:
        return self.find_jsonl_via_backend(name, predicate, limit=limit)

    def write_memory_ref_json(self, name: str, data: Any) -> str:
        path = _safe_path(self.memory_dir, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        ref = str(path.relative_to(self.base_dir))
        with FileLock(str(self.artifact_lock_file)):
            self.memory_backend().upsert_ref(ref, data)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return ref

    def read_memory_ref_json(self, ref: str, default: Any = _MISSING) -> Any:
        normalized = ref.replace("\\", "/").lstrip("/")
        if normalized.startswith("memory/"):
            normalized = normalized[len("memory/") :]
        try:
            canonical_ref = str(_safe_path(self.memory_dir, normalized).relative_to(self.base_dir))
            rows = self.memory_backend_query_refs(ref_path=canonical_ref, limit=1).get("refs", [])
        except (OSError, ValueError):
            rows = []
        if not rows:
            return {} if default is _MISSING else default
        payload = rows[0].get("payload")
        return payload if payload is not None else ({} if default is _MISSING else default)

    def write_artifact(self, name: str, content: str) -> Path:
        path = _safe_path(self.artifacts_dir, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.artifact_lock_file)):
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
        with FileLock(str(self.artifact_lock_file)):
            with path.open("a", encoding="utf-8") as f:
                f.write(content)
        return path

    def artifact_exists(self, name: str) -> bool:
        return _safe_path(self.artifacts_dir, name).exists()

    def storage_budget_report(self, *, warning_bytes: int = 8 * 1024**3) -> dict[str, Any]:
        """按存储类别汇总空间、增长治理建议；只读且不扫描源码目录。"""
        categories = {"graph": self.graph_dir, "index": self.index_dir, "artifacts": self.artifacts_dir, "memory": self.memory_dir}
        sizes = {name: sum(path.stat().st_size for path in directory.rglob("*") if path.is_file()) for name, directory in categories.items()}
        total = sum(sizes.values())
        actions = []
        if sizes["graph"] > warning_bytes // 2:
            actions.append("artifact assertion-vacuum --workspace <workspace.yaml> --dry-run")
        if sizes["index"] > warning_bytes // 4:
            actions.append("artifact index-export-cleanup --workspace <workspace.yaml> --dry-run")
        if sizes["memory"] > warning_bytes // 8:
            actions.append("artifact compact-task --workspace <workspace.yaml> --task-id <task-id>")
        return {"categories": sizes, "total_bytes": total, "warning_bytes": warning_bytes, "status": "warning" if total >= warning_bytes else "healthy", "recommended_actions": actions, "next_action": actions[0] if actions else "当前空间在预算内。"}

    @property
    def graph_db_path(self) -> Path:
        return self.graph_dir / "graph.db"

    @property
    def runtime_db_path(self) -> Path:
        """Return the single SQLite fact store for graph, index and memory data."""
        return self.graph_db_path

    def memory_backend(self) -> RuntimeStore:
        if self._memory_backend is None:
            self._memory_backend = RuntimeStore(self.runtime_db_path)
        return self._memory_backend

    def memory_backend_stats(self) -> dict[str, Any]:
        return self.memory_backend().stats()

    def memory_backend_query_records(self, *, collection: str = "", record_id: str = "", created_after: str = "", project: str = "", payload_type: str = "", session_id: str = "", limit: int = 50) -> dict[str, Any]:
        if collection == _MCP_INVOCATIONS_FILE:
            cutoff = _mcp_audit_cutoff()
            created_after = max(created_after, cutoff) if created_after else cutoff
        result = self.memory_backend().query_records(collection=collection, record_id=record_id, created_after=created_after, project=project, payload_type=payload_type, session_id=session_id, limit=limit)
        if collection == _MCP_INVOCATIONS_FILE:
            result["total_count"] = min(int(result.get("total_count", 0) or 0), _MCP_AUDIT_MAX_RECORDS)
        return result

    def read_json_prefer_backend(self, name: str, default: Any) -> Any:
        """Read deterministic runtime state from the canonical SQLite store.

        JSON files remain inspectable exports written by the indexing pipeline;
        they are intentionally not a query fallback. A workspace created by an
        earlier release therefore needs one explicit reindex before use.
        """
        try:
            backend_entry = self.memory_backend().read_index_entry(name)
        except (OSError, ValueError):
            return default
        if backend_entry.get("found"):
            return backend_entry.get("value")
        return default

    def cleanup_runtime_only_index_exports(self, *, apply: bool = False) -> dict[str, Any]:
        """Remove obsolete JSON copies only when SQLite has the canonical payload."""
        candidates: list[dict[str, Any]] = []
        for name in sorted(RUNTIME_ONLY_INDEXES):
            path = self.index_dir / name
            if not path.exists() or not self.memory_backend().read_index_entry(name).get("found"):
                continue
            candidates.append({"name": name, "bytes": path.stat().st_size})
        payload: dict[str, Any] = {
            "apply": apply,
            "candidates": candidates,
            "candidate_bytes": sum(int(item["bytes"]) for item in candidates),
            "removed": [],
            "next_action": "运行 index-export-cleanup --apply 删除 SQLite 已覆盖的大型 JSON 索引导出。"
            if candidates
            else "当前没有可清理的大型 JSON 索引导出。",
        }
        if not apply or not candidates:
            return payload
        with FileLock(str(self.lock_file)):
            for item in candidates:
                path = self.index_dir / str(item["name"])
                if path.exists():
                    path.unlink()
                    _drop_json_cache(path)
                    payload["removed"].append(item)
        payload["next_action"] = "已删除 SQLite 的重复 JSON 索引导出。"
        return payload

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
