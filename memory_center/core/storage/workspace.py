from __future__ import annotations

import json
import sqlite3
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
        # java-ir-index is an additive diff-gate diagnostic (678k candidates on
        # large workspaces); keeping a second JSON export on disk doubled its
        # ~342MB footprint. SQLite index_mirror is authoritative, same as
        # java-symbol-index.
        "java-ir-index.json",
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
        # A scoped reindex reads the same large deterministic indexes while
        # merging, rebuilding the graph, and publishing generation shards.
        # Keep one Store-local object copy instead of decoding the Java symbol
        # payload repeatedly. Reads compare SQLite ``updated_at`` first, so a
        # long-lived Store observes publications made by another instance.
        self._runtime_index_cache: dict[str, tuple[str, Any]] = {}
        for p in [self.index_dir, self.rules_dir, self.memory_dir, self.refs_dir, self.artifacts_dir, self.instructions_dir, self.graph_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, data: Any) -> None:
        path = self.index_dir / name
        with FileLock(str(self.index_lock_file)):
            updated_at = self.memory_backend().upsert_index(name, data)
            if name in RUNTIME_ONLY_INDEXES:
                path.unlink(missing_ok=True)
            else:
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            if name in RUNTIME_ONLY_INDEXES:
                self._runtime_index_cache[name] = (updated_at, data)
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
            self._recover_jsonl_export_locked(name)
            record_db_id = self.memory_backend().append_record(name, item, record_id=self._infer_record_id(name, item))
            try:
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            except OSError:
                self._mark_jsonl_export_dirty_locked(name)
                raise
            self._set_jsonl_export_state_locked(name, record_db_id, dirty=False)
        return item

    def append_jsonl_batch(self, name: str, items: list[dict[str, Any]]) -> int:
        """Append a collection with one workspace lock and one SQLite transaction."""
        if not items:
            return 0
        path = self.memory_dir / name
        now = datetime.now(timezone.utc).isoformat()
        rows = [dict(item, created_at=item.get("created_at") or now) for item in items]
        with FileLock(str(self.audit_lock_file)):
            self._recover_jsonl_export_locked(name)
            last_record_db_id = self.memory_backend().append_records(
                name,
                rows,
                record_ids=[self._infer_record_id(name, row) for row in rows],
            )
            try:
                with path.open("a", encoding="utf-8") as handle:
                    handle.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
            except OSError:
                self._mark_jsonl_export_dirty_locked(name)
                raise
            self._set_jsonl_export_state_locked(name, last_record_db_id, dirty=False)
        return len(rows)

    def sync_jsonl_export(self, name: str, *, rebuild: bool = False) -> dict[str, Any]:
        """从 SQLite 权威记录恢复或增量同步一个 JSONL 导出。"""
        with FileLock(str(self.audit_lock_file)):
            return self._sync_jsonl_export_locked(name, rebuild=rebuild)

    def jsonl_export_status(self, name: str) -> dict[str, Any]:
        state = self.memory_backend().jsonl_export_state(name)
        latest = self.memory_backend().latest_record_id(name)
        return {**state, "latest_record_id": latest, "needs_sync": bool(state["dirty"] or state["last_record_id"] != latest)}

    def jsonl_export_health(self, *, limit: int = 100) -> dict[str, Any]:
        """只读汇总 SQLite→JSONL 投影健康，不暴露记录正文。"""
        collections = self.memory_backend().jsonl_record_collections()[:max(1, limit)]
        entries = [self.jsonl_export_status(name) for name in collections]
        unhealthy = [entry for entry in entries if entry["needs_sync"]]
        return {
            "status": "attention" if unhealthy else "pass",
            "collection_count": len(entries),
            "needs_sync_count": len(unhealthy),
            "dirty_count": sum(1 for entry in entries if entry["dirty"]),
            "collections": entries,
            "next_action": "artifact jsonl-export-sync --workspace <workspace.yaml> --collection <name> --apply" if unhealthy else "",
        }

    def _recover_jsonl_export_locked(self, name: str) -> None:
        state = self.memory_backend().jsonl_export_state(name)
        if state["dirty"]:
            self._sync_jsonl_export_locked(name, rebuild=True)

    def _sync_jsonl_export_locked(self, name: str, *, rebuild: bool) -> dict[str, Any]:
        path = self.memory_dir / name
        state = self.memory_backend().jsonl_export_state(name)
        rebuild = rebuild or state["dirty"] or (state["last_record_id"] > 0 and not path.exists()) or (
            state["last_record_id"] == 0 and path.exists()
        )
        after_id = 0 if rebuild else state["last_record_id"]
        rows = self.memory_backend().records_for_jsonl_export(name, after_id=after_id)
        if rebuild:
            temp_path = path.with_suffix(path.suffix + ".tmp")
            try:
                temp_path.write_text("".join(json.dumps(row["payload"], ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
                temp_path.replace(path)
            except OSError:
                temp_path.unlink(missing_ok=True)
                self._mark_jsonl_export_dirty_locked(name)
                raise
        elif rows:
            try:
                with path.open("a", encoding="utf-8") as handle:
                    handle.writelines(json.dumps(row["payload"], ensure_ascii=False) + "\n" for row in rows)
            except OSError:
                self._mark_jsonl_export_dirty_locked(name)
                raise
        latest = self.memory_backend().latest_record_id(name)
        self._set_jsonl_export_state_locked(name, latest, dirty=False)
        return {"collection": name, "rebuild": rebuild, "exported": len(rows), "last_record_id": latest, "dirty": False}

    def _set_jsonl_export_state_locked(self, name: str, last_record_id: int, *, dirty: bool) -> None:
        self.memory_backend().set_jsonl_export_state(
            name,
            last_record_id=last_record_id,
            dirty=dirty,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _mark_jsonl_export_dirty_locked(self, name: str) -> None:
        state = self.memory_backend().jsonl_export_state(name)
        self._set_jsonl_export_state_locked(name, state["last_record_id"], dirty=True)

    def move_jsonl_records_exact(
        self,
        source_name: str,
        archive_name: str,
        source_items: list[dict[str, Any]],
        archive_items: list[dict[str, Any]],
    ) -> int:
        """原子迁移 SQLite 事实记录，并同步重写 JSONL 导出。"""
        if len(source_items) != len(archive_items):
            raise ValueError("source_items and archive_items must have the same length")
        if not source_items:
            return 0
        source_path = self.memory_dir / source_name
        archive_path = self.memory_dir / archive_name
        fingerprints = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in source_items]
        with FileLock(str(self.audit_lock_file)):
            moved = self.memory_backend().move_records_exact(source_name, archive_name, source_items, archive_items)
            with archive_path.open("a", encoding="utf-8") as handle:
                handle.writelines(json.dumps(item, ensure_ascii=False) + "\n" for item in archive_items)
            if source_path.exists():
                pending = list(fingerprints)
                kept: list[str] = []
                for line in source_path.read_text(encoding="utf-8").splitlines():
                    try:
                        fingerprint = json.dumps(json.loads(line), ensure_ascii=False, sort_keys=True)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        kept.append(line)
                        continue
                    if fingerprint in pending:
                        pending.remove(fingerprint)
                    else:
                        kept.append(line)
                if pending:
                    raise RuntimeError("session archive export is missing source records")
                source_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            self._set_jsonl_export_state_locked(
                source_name, self.memory_backend().latest_record_id(source_name), dirty=False
            )
            self._set_jsonl_export_state_locked(
                archive_name, self.memory_backend().latest_record_id(archive_name), dirty=False
            )
        return moved

    def prune_jsonl(self, name: str, *, created_before: datetime, max_records: int) -> dict[str, int]:
        """删除过期 JSONL 记录并限制条数，同时清理 SQLite 镜像。"""
        if max_records < 1:
            raise ValueError("max_records must be at least 1")
        path = self.memory_dir / name
        cutoff = created_before.astimezone(timezone.utc)
        kept_lines: deque[str] = deque(maxlen=max_records)
        total = expired = invalid = overflow = 0
        # JSONL 导出与 SQLite 水位共用 audit 锁，避免 prune 与 append 交叉
        # 造成导出内容和 projection state 漂移。
        with FileLock(str(self.audit_lock_file)):
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
            self._mark_jsonl_export_dirty_locked(name)
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

    def publish_generation_payloads(
        self,
        payloads: list[tuple[str, Any]],
        *,
        publication: dict[str, str] | None = None,
    ) -> None:
        """Atomically publish generation control payloads into the backend.

        All ``index_mirror`` rows in ``payloads`` plus one audit row in
        ``generation_publications`` commit inside a single
        ``BEGIN IMMEDIATE`` transaction (Phase C atomic publish, design doc
        §8.5). On any failure the transaction rolls back and the previous
        active generation pointer stays untouched. The caller is expected
        to already hold the workspace reindex lock.

        The JSON file exports are intentionally NOT written here: keep them
        out of the transaction so a slow disk write can never widen the
        critical section. Callers refresh exports after commit.
        """
        from datetime import datetime, timezone

        conn = sqlite3.connect(str(self.graph_db_path), timeout=30.0)
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                updated_at = datetime.now(timezone.utc).isoformat()
                for name, payload in payloads:
                    conn.execute(
                        """
                        INSERT INTO index_mirror(name, payload_json, updated_at)
                        VALUES(?, ?, ?)
                        ON CONFLICT(name) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at
                        """,
                        (name, json.dumps(payload, ensure_ascii=False), updated_at),
                    )
                if publication:
                    # Table created lazily so legacy databases need no migration.
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS generation_publications ("
                        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                        " published_generation TEXT NOT NULL,"
                        " previous_generation TEXT NOT NULL DEFAULT '',"
                        " publishing_job_id TEXT NOT NULL DEFAULT '',"
                        " mode TEXT NOT NULL DEFAULT '',"
                        " outcome TEXT NOT NULL DEFAULT 'published',"
                        " published_at TEXT NOT NULL DEFAULT '')"
                    )
                    conn.execute(
                        "INSERT INTO generation_publications(published_generation, previous_generation, publishing_job_id, mode, outcome, published_at)"
                        " VALUES(?,?,?,?,?,?)",
                        (
                            str(publication.get("published_generation", "")),
                            str(publication.get("previous_generation", "")),
                            str(publication.get("publishing_job_id", "")),
                            str(publication.get("mode", "")),
                            str(publication.get("outcome", "published")),
                            updated_at,
                        ),
                    )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    def record_publication_outcome(self, publication: dict[str, str]) -> None:
        """Append a non-published outcome row (e.g. publish_smoke_failed)."""
        from datetime import datetime, timezone

        conn = sqlite3.connect(str(self.graph_db_path), timeout=30.0)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS generation_publications ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " published_generation TEXT NOT NULL,"
                " previous_generation TEXT NOT NULL DEFAULT '',"
                " publishing_job_id TEXT NOT NULL DEFAULT '',"
                " mode TEXT NOT NULL DEFAULT '',"
                " outcome TEXT NOT NULL DEFAULT 'published',"
                " published_at TEXT NOT NULL DEFAULT '')"
            )
            conn.execute(
                "INSERT INTO generation_publications(published_generation, previous_generation, publishing_job_id, mode, outcome, published_at)"
                " VALUES(?,?,?,?,?,?)",
                (
                    str(publication.get("published_generation", "")),
                    str(publication.get("previous_generation", "")),
                    str(publication.get("publishing_job_id", "")),
                    str(publication.get("mode", "")),
                    str(publication.get("outcome", "")),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

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
            backend = self.memory_backend()
            updated_at = backend.index_updated_at(name)
            cached = self._runtime_index_cache.get(name)
            if cached is not None and cached[0] == updated_at:
                return cached[1]
            backend_entry = backend.read_index_entry(name)
        except (OSError, ValueError):
            return default
        if backend_entry.get("found"):
            value = backend_entry.get("value")
            if name in RUNTIME_ONLY_INDEXES:
                self._runtime_index_cache[name] = (str(backend_entry.get("updated_at", "") or ""), value)
            return value
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
        if collection == "session-notes.jsonl":
            return str(item.get("note_id", "") or "")
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
