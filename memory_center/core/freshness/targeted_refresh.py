"""Bounded, query-time graph refresh for recently changed source files."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import json
from filelock import FileLock

from ..graph import GraphEdge, GraphNode, GraphStore, edge_id, node_id
from ..indexer import parse_java_symbols, safe_read
from ..store import WorkspaceStore

MAX_REFRESH_FILES = 12
MANIFEST_FILE = "hot-refresh-manifest.json"
DIRTY_JOURNAL_FILE = "dirty-files.jsonl"


def refresh_query_targets(workspace_file: str | Path, query: str, limit: int = MAX_REFRESH_FILES) -> dict[str, Any]:
    """Refresh only stale indexed Java files plausibly related to ``query``."""
    started = time.perf_counter()
    store = WorkspaceStore(workspace_file)
    manifest = store.read_json(MANIFEST_FILE, {}) or {}
    dirty_rows = store.read_jsonl_prefer_backend(DIRTY_JOURNAL_FILE, limit=200)
    files = store.read_json_prefer_backend("file-index.json", [])
    tokens = [part.lower() for part in query.replace("#", " ").replace(".", " ").split() if len(part) > 2]
    candidates: list[dict[str, Any]] = []
    try:
        with GraphStore(store.graph_db_path) as graph:
            for node in graph.find_nodes(" ".join(tokens[:6]), types=["File", "Class", "Method"], limit=limit * 4):
                path = str(node.get("file_path", "") or "")
                if path:
                    candidates.append({"path": path})
    except Exception:
        pass
    for item in files:
        path = str(item.get("path", "") or "")
        if tokens and any(token in path.lower() for token in tokens):
            candidates.append(item)
    dirty_paths = {str(row.get("path", "") or "") for row in dirty_rows}
    candidates.extend(item for item in files if str(item.get("path", "") or "") in dirty_paths)

    by_path = {str(item.get("path", "")): item for item in files}
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        path = str(candidate.get("path", "") or "")
        item = by_path.get(path, candidate)
        if path and item not in selected:
            selected.append(item)
        if len(selected) >= min(MAX_REFRESH_FILES, max(1, limit)):
            break

    refreshed: list[str] = []
    checked: list[str] = []
    graph_mtime = store.graph_db_path.stat().st_mtime_ns if store.graph_db_path.exists() else 0
    for item in selected:
        abs_path = Path(str(item.get("abs_path", "") or ""))
        rel = str(item.get("path", "") or "")
        if not abs_path.exists() or abs_path.suffix != ".java":
            continue
        checked.append(rel)
        version = manifest.get(rel, {}) if isinstance(manifest, dict) else {}
        indexed_mtime = int(version.get("mtime_ns", item.get("source_mtime_ns", graph_mtime)) or graph_mtime)
        stat = abs_path.stat()
        if stat.st_mtime_ns <= indexed_mtime and stat.st_size == int(version.get("size", item.get("source_size", stat.st_size)) or stat.st_size):
            continue
        _refresh_java_graph(store, item, abs_path)
        manifest[rel] = {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size, "generation": int(version.get("generation", 0) or 0) + 1}
        refreshed.append(rel)
    if refreshed:
        store.write_json(MANIFEST_FILE, manifest)
    return {
        "checked": len(checked),
        "refreshed": bool(refreshed),
        "files": refreshed,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "mode": "targeted_overlay",
        "coalesced": False,
        "generation": {path: manifest[path]["generation"] for path in refreshed},
    }


def _refresh_java_graph(store: WorkspaceStore, item: dict[str, Any], source: Path) -> None:
    project = str(item.get("project", "") or "")
    rel = str(item.get("path", "") or "")
    symbol = parse_java_symbols(project, rel, safe_read(source))
    raw = symbol.__dict__
    file_id = node_id("File", rel)
    nodes = [GraphNode(file_id, "File", Path(rel).name, project, rel, metadata={**item, "source_mtime_ns": source.stat().st_mtime_ns, "source_size": source.stat().st_size, "hot_refreshed": True})]
    edges: list[GraphEdge] = []
    for cls in raw.get("classes", []) + raw.get("interfaces", []):
        class_id = node_id("Class", project, cls)
        nodes.append(GraphNode(class_id, "Class", cls, project, rel, int(raw.get("class_lines", {}).get(cls, 0) or 0), metadata={"hot_refreshed": True}))
        edges.append(GraphEdge(edge_id("DECLARES", file_id, class_id), file_id, class_id, "DECLARES"))
        for method in raw.get("methods", []):
            method_id = node_id("Method", project, cls, method)
            nodes.append(GraphNode(method_id, "Method", f"{cls}.{method}", project, rel, int(raw.get("method_lines", {}).get(method, 0) or 0), metadata={"method": method, "hot_refreshed": True}))
            edges.append(GraphEdge(edge_id("DECLARES", class_id, method_id), class_id, method_id, "DECLARES"))
        for injection in raw.get("bean_injections", []):
            target_type = str(injection.get("type", "") or "")
            if target_type:
                target_id = node_id("Class", project, target_type)
                edges.append(GraphEdge(edge_id("INJECTS_BEAN", class_id, target_id), class_id, target_id, "INJECTS_BEAN", 0.8, {"hot_refreshed": True}))
        for call in raw.get("method_calls", []):
            method_name = str(call.get("method_name", "") or "")
            target_class = str(call.get("receiver_type", "") or cls)
            owner_method = str(call.get("owner_method", "") or "")
            source_method = owner_method.split(".")[-1] if owner_method else ""
            if method_name and source_method:
                source_id = node_id("Method", project, cls, source_method)
                target_id = node_id("Method", project, target_class, method_name)
                edges.append(GraphEdge(edge_id("CALLS_METHOD", source_id, target_id), source_id, target_id, "CALLS_METHOD", 0.55, {"hot_refreshed": True, "resolution_level": "targeted_heuristic"}))
    with GraphStore(store.graph_db_path) as graph:
        graph.replace_file_subgraph(rel, nodes, edges)


def record_dirty_files(workspace_file: str | Path, paths: list[str], source: str = "watcher") -> dict[str, Any]:
    """Persist debounced file changes for the next bounded query refresh."""
    store = WorkspaceStore(workspace_file)
    unique = sorted({path.replace("\\", "/").lstrip("/") for path in paths if path})[:200]
    for path in unique:
        store.append_jsonl(DIRTY_JOURNAL_FILE, {"path": path, "source": source})
    compacted = compact_dirty_journal(store) if len(store.read_jsonl_prefer_backend(DIRTY_JOURNAL_FILE, limit=600)) >= 500 else False
    return {"recorded": len(unique), "paths": unique, "compacted": compacted}


def hot_refresh_status(workspace_file: str | Path) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    manifest = store.read_json(MANIFEST_FILE, {}) or {}
    dirty = store.read_jsonl_prefer_backend(DIRTY_JOURNAL_FILE, limit=500)
    return {"manifest_files": len(manifest) if isinstance(manifest, dict) else 0, "dirty_paths": len({str(row.get("path", "") or "") for row in dirty}), "dirty_events": len(dirty), "mode": "targeted_overlay"}


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
