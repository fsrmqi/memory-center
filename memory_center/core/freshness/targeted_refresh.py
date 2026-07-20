"""Bounded, query-time graph refresh for recently changed source files."""
from __future__ import annotations

import json
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

from filelock import FileLock

from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.storage.graph import GraphStore
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

from .coordinator import RefreshCoordinator

MAX_REFRESH_FILES = 12
MANIFEST_FILE = "hot-refresh-manifest.json"
DIRTY_JOURNAL_FILE = "dirty-files.jsonl"


def refresh_query_targets(workspace_file: str | Path, query: str, limit: int = MAX_REFRESH_FILES) -> dict[str, Any]:
    """Refresh only stale indexed Java files plausibly related to ``query``."""
    store = WorkspaceStore(workspace_file)
    coordinator = RefreshCoordinator(store.memory_dir)
    return coordinator.run(
        lambda: _refresh_query_targets(store, query, limit),
        lambda: {"checked": 0, "refreshed": False, "files": [], "elapsed_ms": 0.0, "mode": "targeted_overlay", "coalesced": True, "generation": {}},
    )


def _refresh_query_targets(store: WorkspaceStore, query: str, limit: int) -> dict[str, Any]:
    """Refresh bounded paths through the canonical partial reindex pipeline.

    The refresh path must not maintain a smaller, independent graph writer.
    A partial reindex updates every deterministic index and recreates the full
    set of graph facts for a file, including endpoints, Feign, MQ and config
    relationships. It also reconciles paths which were added or deleted since
    the previous index generation.
    """
    started = time.perf_counter()
    manifest = store.read_json(MANIFEST_FILE, {}) or {}
    dirty_rows = store.read_jsonl_prefer_backend(DIRTY_JOURNAL_FILE, limit=200)
    files = store.read_json_prefer_backend("file-index.json", [])
    config = load_workspace_config(store.workspace_file)
    tokens = [part.lower() for part in query.replace("#", " ").replace(".", " ").split() if len(part) > 2]
    candidates: list[dict[str, Any]] = []
    closure_paths: list[str] = []
    try:
        with GraphStore(store.graph_db_path) as graph:
            for node in graph.find_nodes(" ".join(tokens[:6]), types=["File", "Class", "Method"], limit=limit * 4):
                path = str(node.get("file_path", "") or "")
                if path:
                    candidates.append({"path": path})
            # Query-matched files form the first hop; their graph neighbors
            # cover API/Feign/DTO/MQ/config relationships already resolved by
            # the full index, without scanning the complete workspace.
            seed_paths = [str(item.get("path", "") or "") for item in candidates if item.get("path")][:max(1, min(limit, 6))]
            for path in seed_paths:
                closure_paths.extend(graph.file_neighbors(path, limit=8))
    except Exception:
        pass
    for item in files:
        path = str(item.get("path", "") or "")
        if tokens and any(token in path.lower() for token in tokens):
            candidates.append(item)
    dirty_paths = {str(row.get("path", "") or "") for row in dirty_rows}
    candidates.extend(item for item in files if str(item.get("path", "") or "") in dirty_paths)
    candidates.extend({"path": path} for path in dirty_paths)
    candidates.extend({"path": path} for path in closure_paths)

    by_path = {str(item.get("path", "")): item for item in files}
    selected_paths: list[str] = []
    for candidate in candidates:
        path = str(candidate.get("path", "") or "")
        if path and path not in selected_paths:
            selected_paths.append(path)
        if len(selected_paths) >= min(MAX_REFRESH_FILES, max(1, limit)):
            break

    refresh_paths: list[str] = []
    checked: list[str] = []
    states: dict[str, dict[str, Any]] = {}
    for rel in selected_paths:
        item = by_path.get(rel, {})
        abs_path = Path(str(item.get("abs_path", "") or "")) if item else _resolve_workspace_path(config, rel)
        if abs_path is None:
            continue
        checked.append(rel)
        version = manifest.get(rel, {}) if isinstance(manifest, dict) else {}
        state = _source_state(abs_path)
        states[rel] = state
        if _manifest_matches(version, state):
            continue
        if not version and _indexed_state_matches(item, state):
            continue
        refresh_paths.append(rel)

    if refresh_paths:
        reindex_workspace(config, store, paths=refresh_paths)
        with GraphStore(store.graph_db_path) as graph:
            for rel in refresh_paths:
                previous = manifest.get(rel, {}) if isinstance(manifest, dict) else {}
                manifest[rel] = {
                    **states[rel],
                    "generation": int(previous.get("generation", 0) or 0) + 1,
                }
                graph.record_file_generation(rel, manifest[rel]["generation"], str(states[rel].get("content_hash", "")))
        store.write_json(MANIFEST_FILE, manifest)
    return {
        "checked": len(checked),
        "refreshed": bool(refresh_paths),
        "files": refresh_paths,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "mode": "targeted_overlay",
        "coalesced": False,
        "generation": {path: manifest[path]["generation"] for path in refresh_paths},
        "dependency_closure": {"paths": sorted(set(closure_paths))[:24], "depth": 1},
    }


def _resolve_workspace_path(config: Any, logical_path: str) -> Path | None:
    """Resolve a workspace logical path, including files absent from file-index."""
    normalized = logical_path.replace("\\", "/").strip("/")
    for service in config.services:
        prefix = config.service_logical_prefix(service)
        if normalized == prefix:
            return config.resolve_service_path(service)
        if normalized.startswith(prefix + "/"):
            return config.resolve_service_path(service) / normalized[len(prefix) + 1 :]
    return None


def _manifest_matches(version: dict[str, Any], state: dict[str, Any]) -> bool:
    if version.get("status", "present") != state["status"]:
        return False
    if state["status"] == "deleted":
        return bool(version)
    return (
        int(version.get("mtime_ns", -1) or -1) == state["mtime_ns"]
        and int(version.get("size", -1) or -1) == state["size"]
        and str(version.get("content_hash", "")) == state["content_hash"]
    )


def _source_state(path: Path) -> dict[str, Any]:
    """Capture a stable source fingerprint; concurrent removal is a deletion."""
    try:
        stat = path.stat()
        return {
            "status": "present",
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
            "content_hash": sha256(path.read_bytes()).hexdigest(),
        }
    except OSError:
        return {"status": "deleted"}


def _indexed_state_matches(item: dict[str, Any], state: dict[str, Any]) -> bool:
    """Use the full-index file metadata as the baseline before first refresh."""
    if not item or state["status"] != "present":
        return False
    return (
        int(item.get("source_mtime_ns", -1) or -1) == state["mtime_ns"]
        and int(item.get("source_size", -1) or -1) == state["size"]
    )


def record_dirty_files(workspace_file: str | Path, paths: list[str], source: str = "watcher") -> dict[str, Any]:
    """Persist debounced file changes for the next bounded query refresh."""
    store = WorkspaceStore(workspace_file)
    unique = sorted({path.replace("\\", "/").lstrip("/") for path in paths if path})[:200]
    try:
        from .invalidation import build_invalidation_plan
        invalidation = build_invalidation_plan(workspace_file, unique)
    except Exception:
        invalidation = {"paths": unique, "impacted_paths": unique, "categories": [], "rules": [], "mode": "unavailable"}
    for path in unique:
        matching = next((item for item in invalidation.get("rules", []) if item.get("path") == path), {})
        store.append_jsonl(DIRTY_JOURNAL_FILE, {"path": path, "source": source, "invalidation": matching})
    stale_assertions = store.memory_backend().mark_assertions_stale(unique)
    compacted = compact_dirty_journal(store) if len(store.read_jsonl_prefer_backend(DIRTY_JOURNAL_FILE, limit=600)) >= 500 else False
    return {"recorded": len(unique), "paths": unique, "compacted": compacted, "invalidation": invalidation, "stale_assertions": stale_assertions}


def hot_refresh_status(workspace_file: str | Path) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    manifest = store.read_json(MANIFEST_FILE, {}) or {}
    dirty = store.read_jsonl_prefer_backend(DIRTY_JOURNAL_FILE, limit=500)
    summary = store.read_json("hot-refresh-summary.json", {}) or {}
    from .change_reports import pending_change_impact_reports, recent_change_impact_reports
    from .daemon import watcher_daemon_status

    return {
        "manifest_files": len(manifest) if isinstance(manifest, dict) else 0,
        "dirty_paths": len({str(row.get("path", "") or "") for row in dirty}),
        "dirty_events": len(dirty),
        "mode": "targeted_overlay",
        "compacted_at": summary.get("compacted_at"),
        "compacted_generation_count": summary.get("generation_count", 0),
        "watcher": watcher_daemon_status(workspace_file),
        "recent_change_reports": recent_change_impact_reports(workspace_file, limit=3),
        "pending_change_reports": pending_change_impact_reports(workspace_file, limit=5),
    }


def compact_dirty_journal(store: WorkspaceStore) -> bool:
    """Keep only the newest dirty event per path without touching code indexes."""
    rows = store.read_jsonl_prefer_backend(DIRTY_JOURNAL_FILE, limit=5000)
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        path = str(row.get("path", "") or "")
        if path:
            latest[path] = row
    path = store.memory_dir / DIRTY_JOURNAL_FILE
    with FileLock(str(store.lock_file)):
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in latest.values()), encoding="utf-8")
    return len(rows) != len(latest)


def compact_hot_refresh_overlay(workspace_file: str | Path) -> dict[str, Any]:
    """Compact the mutable refresh journal into a stable generation snapshot."""
    store = WorkspaceStore(workspace_file)
    manifest = store.read_json(MANIFEST_FILE, {}) or {}
    dirty = store.read_jsonl_prefer_backend(DIRTY_JOURNAL_FILE, limit=5000)
    compact_dirty_journal(store)
    summary = {
        "mode": "targeted_overlay",
        "compacted_at": int(time.time()),
        "generation_count": len(manifest) if isinstance(manifest, dict) else 0,
        "max_generation": max((int(value.get("generation", 0) or 0) for value in manifest.values()), default=0) if isinstance(manifest, dict) else 0,
        "dirty_events_before": len(dirty),
    }
    store.write_json("hot-refresh-summary.json", summary)
    return summary
